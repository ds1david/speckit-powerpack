#!/usr/bin/env python3
"""Project-local SpecKit PowerPack runtime.

Stdlib-only by design. This module is installed into `.specify/powerpack/bin/`
and is the single source of truth for workflow receipts, implement deltas,
review convergence state, quality-gate discovery, executor routing, and
usage-limit checkpoints.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable

DOC_EXTENSIONS = {
    ".md", ".mdx", ".txt", ".rst", ".adoc", ".pdf", ".png", ".jpg",
    ".jpeg", ".gif", ".svg", ".webp",
}
DOC_DIRS = {"docs", "doc", "documentation"}
REVIEW_LINE = re.compile(
    r"^- \[(?P<done>[ xX])\] (?P<id>REV-[0-9a-f]{10}) "
    r"\[REVIEW\]\[(?P<status>[A-Z_]+)\]\[(?P<provider>[^\]]+)\]"
    r"\[(?P<severity>[^\]]+)\] (?P<title>.*?) \| evidence: (?P<evidence>.*?)"
    r" \| source-round: (?P<round>\d+)(?: \| resolution: (?P<resolution>.*))?$"
)
LIMIT_PATTERNS = (
    "usage limit", "rate limit", "rate_limit", "too many requests", "429",
    "limit reached", "quota exceeded", "resets at", "reset at", "try again later",
    "you've hit", "you have hit",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(argv: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), text=True, capture_output=True, check=check)


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".specify").is_dir():
            return candidate
    raise SystemExit("BLOCKED: .specify directory not found; this is not an initialized Spec Kit project.")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_feature_dir(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = (root / path).resolve()
        if not path.is_dir():
            raise SystemExit(f"BLOCKED: feature directory does not exist: {path}")
        return path

    bash = root / ".specify" / "scripts" / "bash" / "check-prerequisites.sh"
    if bash.is_file() and shutil.which("bash"):
        proc = run(["bash", str(bash), "--json"], root)
        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                value = data.get("FEATURE_DIR") or data.get("feature_dir")
                if value:
                    return Path(value).resolve()
            except json.JSONDecodeError:
                pass

    ps = root / ".specify" / "scripts" / "powershell" / "check-prerequisites.ps1"
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if ps.is_file() and pwsh:
        proc = run([pwsh, "-NoProfile", "-File", str(ps), "-Json"], root)
        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                value = data.get("FEATURE_DIR") or data.get("feature_dir")
                if value:
                    return Path(value).resolve()
            except json.JSONDecodeError:
                pass

    branch = run(["git", "branch", "--show-current"], root).stdout.strip()
    specs = root / "specs"
    if branch and specs.is_dir():
        candidate = specs / branch
        if candidate.is_dir():
            return candidate.resolve()
        matches = sorted(path for path in specs.glob(f"{branch}*") if path.is_dir())
        if len(matches) == 1:
            return matches[0].resolve()

    raise SystemExit("BLOCKED: could not resolve current feature directory. Pass --feature-dir explicitly.")


def feature_key(root: Path, feature: Path) -> str:
    try:
        raw = feature.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raw = feature.name
    return raw.replace("/", "__").replace("\\", "__")


def feature_id(root: Path, feature: Path) -> str:
    try:
        return feature.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return feature.name


def powerpack_dir(root: Path) -> Path:
    return root / ".specify" / "powerpack"


def state_path(root: Path, feature: Path) -> Path:
    return powerpack_dir(root) / "state" / f"{feature_key(root, feature)}.json"


def review_state_path(root: Path, feature: Path) -> Path:
    return powerpack_dir(root) / "runtime" / "reviews" / f"{feature_key(root, feature)}.json"


def limit_state_path(root: Path) -> Path:
    return powerpack_dir(root) / "runtime" / "limit-checkpoint.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"BLOCKED: corrupt PowerPack state file: {path}: {exc}")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git_head(root: Path) -> str | None:
    proc = run(["git", "rev-parse", "HEAD"], root)
    return proc.stdout.strip() if proc.returncode == 0 else None


def intent_files(feature: Path, step: str) -> list[Path]:
    names = ["spec.md", "plan.md"]
    if step in {"tasks", "analyze", "implement", "converge", "implement-review"}:
        names.append("tasks.md")
    files = [feature / name for name in names if (feature / name).is_file()]
    if step in {"checklist", "checklist-converge"}:
        checklist_dir = feature / "checklists"
        if checklist_dir.is_dir():
            files.extend(sorted(checklist_dir.glob("*.md")))
    return files


def intent_fingerprint(feature: Path, step: str) -> str:
    h = hashlib.sha256()
    for path in intent_files(feature, step):
        h.update(path.name.encode())
        h.update(sha_file(path).encode())
    return h.hexdigest()


def load_feature_state(root: Path, feature: Path) -> dict[str, Any]:
    return read_json(
        state_path(root, feature),
        {"schema_version": 2, "feature": feature_id(root, feature), "steps": {}, "implement_runs": []},
    )


def save_feature_state(root: Path, feature: Path, data: dict[str, Any]) -> None:
    write_json(state_path(root, feature), data)


def checklist_artifact_evidence(feature: Path) -> bool:
    directory = feature / "checklists"
    if not directory.is_dir():
        return False
    for file in directory.glob("*.md"):
        text = file.read_text(encoding="utf-8", errors="replace").lower()
        if "- [ ]" in text or "- [x]" in text:
            return True
    return False


def cmd_state_mark(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    if args.step == "checklist" and not checklist_artifact_evidence(feature):
        print("BLOCKED: checklist receipt cannot be recorded because no checklist artifact exists.")
        return 3
    data = load_feature_state(root, feature)
    data["steps"][args.step] = {
        "status": args.status,
        "recorded_at": utc_now(),
        "intent_sha256": intent_fingerprint(feature, args.step),
        "git_head": git_head(root),
    }
    save_feature_state(root, feature, data)
    print(json.dumps({"step": args.step, "status": args.status, "feature": feature_id(root, feature)}))
    return 0


def evaluate_receipt(
    root: Path,
    feature: Path,
    step: str,
    allowed: set[str],
    *,
    require_current: bool,
) -> dict[str, Any]:
    receipt = load_feature_state(root, feature).get("steps", {}).get(step)
    if receipt is None:
        return {"ok": False, "step": step, "reason": "MISSING_RECEIPT"}
    if allowed and receipt.get("status") not in allowed:
        return {
            "ok": False,
            "step": step,
            "reason": "STATUS_MISMATCH",
            "actual": receipt.get("status"),
            "required": sorted(allowed),
        }
    if require_current:
        current = intent_fingerprint(feature, step)
        if receipt.get("intent_sha256") != current:
            return {
                "ok": False,
                "step": step,
                "reason": "STALE_INTENT",
                "recorded": receipt.get("intent_sha256"),
                "current": current,
            }
    return {"ok": True, "step": step, "status": receipt.get("status")}


def cmd_state_check(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    result = evaluate_receipt(
        root,
        feature,
        args.step,
        set(args.require_status or []),
        require_current=args.require_current,
    )
    result["feature"] = feature_id(root, feature)
    print(json.dumps(result))
    return 0 if result["ok"] else 4


def default_prerequisites() -> dict[str, list[dict[str, Any]]]:
    return {
        "checklist-converge": [{"step": "checklist", "statuses": ["COMPLETED"]}],
        "implement-review": [{"step": "implement", "statuses": ["COMPLETED"]}],
    }


def cmd_prereq_check(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    config_path = powerpack_dir(root) / "prerequisites.json"
    config = read_json(config_path, {"mode": "strict", "steps": default_prerequisites()})
    if config.get("mode") in {"off", "disabled"}:
        print(json.dumps({"ok": True, "step": args.step, "mode": config.get("mode")}))
        return 0
    requirements = config.get("steps", {}).get(args.step, default_prerequisites().get(args.step, []))
    results: list[dict[str, Any]] = []
    for req in requirements:
        result = evaluate_receipt(
            root,
            feature,
            str(req.get("step")),
            set(req.get("statuses") or []),
            require_current=False,
        )
        results.append(result)
        if not result["ok"]:
            print(json.dumps({
                "ok": False,
                "step": args.step,
                "feature": feature_id(root, feature),
                "failed_requirement": result,
                "next_action": f"speckit-{req.get('step')}",
            }))
            return 9
    print(json.dumps({"ok": True, "step": args.step, "feature": feature_id(root, feature), "requirements": results}))
    return 0


def git_candidate_files(root: Path) -> list[str]:
    proc = run(["git", "ls-files", "-co", "--exclude-standard", "-z"], root)
    if proc.returncode != 0:
        return []
    return sorted({item for item in proc.stdout.split("\0") if item})


def workspace_snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in git_candidate_files(root):
        path = root / raw
        if path.is_file() and not raw.startswith(".specify/powerpack/"):
            try:
                result[raw] = sha_file(path)
            except OSError:
                continue
    return result


def snapshot_delta(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def cmd_implement_begin(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    data = load_feature_state(root, feature)
    runs = data.setdefault("implement_runs", [])
    if any(item.get("status") == "RUNNING" for item in runs):
        print("BLOCKED: an implement run is already RUNNING for this SPEC.")
        return 12
    run_id = datetime.now(timezone.utc).strftime("impl-%Y%m%dT%H%M%S%fZ")
    runs.append({
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": utc_now(),
        "before": workspace_snapshot(root),
        "git_head_before": git_head(root),
    })
    save_feature_state(root, feature, data)
    print(json.dumps({"run_id": run_id, "feature": feature_id(root, feature), "status": "RUNNING"}))
    return 0


def cmd_implement_end(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    data = load_feature_state(root, feature)
    running = [item for item in data.get("implement_runs", []) if item.get("status") == "RUNNING"]
    if not running:
        print("BLOCKED: no RUNNING implement receipt exists for this SPEC.")
        return 13
    item = running[-1]
    after = workspace_snapshot(root)
    changed = snapshot_delta(item.get("before", {}), after)
    item.update({
        "status": "COMPLETED",
        "completed_at": utc_now(),
        "changed_files": changed,
        "git_head_after": git_head(root),
    })
    item.pop("before", None)
    data["steps"]["implement"] = {
        "status": "COMPLETED",
        "recorded_at": utc_now(),
        "intent_sha256": intent_fingerprint(feature, "implement"),
        "git_head": git_head(root),
        "run_id": item["run_id"],
        "changed_files": changed,
    }
    save_feature_state(root, feature, data)
    print(json.dumps({
        "run_id": item["run_id"],
        "feature": feature_id(root, feature),
        "status": "COMPLETED",
        "changed_files": changed,
    }, ensure_ascii=False))
    return 0


def latest_implement_files(root: Path, feature: Path) -> list[str]:
    runs = [item for item in load_feature_state(root, feature).get("implement_runs", []) if item.get("status") == "COMPLETED"]
    return list(runs[-1].get("changed_files", [])) if runs else []


def is_documentation_only(paths: Iterable[str]) -> bool:
    paths = list(paths)
    if not paths:
        return True
    for raw in paths:
        path = Path(raw)
        parts = {part.lower() for part in path.parts}
        suffix = path.suffix.lower()
        if suffix in DOC_EXTENSIONS:
            continue
        if parts & DOC_DIRS and suffix not in {".sh", ".ps1", ".py", ".js", ".ts"}:
            continue
        if ".specify" in parts and suffix in DOC_EXTENSIONS:
            continue
        return False
    return True


def read_quality_config(root: Path) -> dict[str, Any]:
    return read_json(powerpack_dir(root) / "quality-gates.json", {})


def gate_for_project(root: Path, files: list[str]) -> dict[str, Any]:
    if is_documentation_only(files):
        return {"status": "NOT_APPLICABLE", "reason": "documentation-only", "command": None, "changed_files": files}
    custom = read_quality_config(root).get("custom_command")
    if isinstance(custom, list) and custom and all(isinstance(item, str) for item in custom):
        return {"status": "REQUIRED", "reason": "configured", "command": custom, "changed_files": files}
    if (root / "pom.xml").is_file():
        executable = str(root / "mvnw") if (root / "mvnw").is_file() else (shutil.which("mvn") or "mvn")
        return {"status": "REQUIRED", "reason": "maven", "command": [executable, "-B", "verify"], "changed_files": files}
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        executable = str(root / "gradlew") if (root / "gradlew").is_file() else (shutil.which("gradle") or "gradle")
        return {"status": "REQUIRED", "reason": "gradle", "command": [executable, "check"], "changed_files": files}
    if (root / "package.json").is_file():
        package = read_json(root / "package.json", {})
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        script = next((name for name in ("verify", "check", "test") if name in scripts), None)
        if script:
            if (root / "pnpm-lock.yaml").is_file():
                command = ["pnpm", "run", script]
            elif (root / "yarn.lock").is_file():
                command = ["yarn", script]
            elif (root / "bun.lockb").is_file() or (root / "bun.lock").is_file():
                command = ["bun", "run", script]
            else:
                command = ["npm", "run", script]
            return {"status": "REQUIRED", "reason": "node", "command": command, "changed_files": files}
    if (root / "tox.ini").is_file():
        return {"status": "REQUIRED", "reason": "tox", "command": ["tox"], "changed_files": files}
    if (root / "pyproject.toml").is_file() or (root / "pytest.ini").is_file():
        return {"status": "REQUIRED", "reason": "python", "command": [sys.executable, "-m", "pytest"], "changed_files": files}
    if list(root.glob("*.sln")) or list(root.glob("*.csproj")):
        return {"status": "REQUIRED", "reason": "dotnet", "command": ["dotnet", "test"], "changed_files": files}
    if (root / "go.mod").is_file():
        return {"status": "REQUIRED", "reason": "go", "command": ["go", "test", "./..."], "changed_files": files}
    if (root / "Cargo.toml").is_file():
        return {"status": "REQUIRED", "reason": "rust", "command": ["cargo", "test"], "changed_files": files}
    if (root / ".project").is_file() or (root / ".classpath").is_file():
        return {
            "status": "BLOCKED_CONFIGURATION",
            "reason": "eclipse-project-without-deterministic-build-gate",
            "command": None,
            "changed_files": files,
            "next_action": "Configure .specify/powerpack/quality-gates.json custom_command.",
        }
    return {
        "status": "BLOCKED_CONFIGURATION",
        "reason": "unknown-project-architecture",
        "command": None,
        "changed_files": files,
        "next_action": "Configure .specify/powerpack/quality-gates.json custom_command.",
    }


def cmd_gate_detect(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    result = gate_for_project(root, latest_implement_files(root, feature))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] != "BLOCKED_CONFIGURATION" else 7


def cmd_gate_run(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    result = gate_for_project(root, latest_implement_files(root, feature))
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "NOT_APPLICABLE":
        return 0
    if result["status"] == "BLOCKED_CONFIGURATION":
        return 7
    return subprocess.run(result["command"], cwd=str(root)).returncode


def read_model_routing(root: Path) -> dict[str, Any]:
    return read_json(powerpack_dir(root) / "model-routing.json", {})


def detect_executor(root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    env = {key.upper(): value for key, value in os.environ.items()}
    if env.get("CODEX_SESSION_ID") or env.get("CODEX_HOME") or env.get("SPECKIT_POWERPACK_EXECUTOR", "").lower() == "codex":
        return "codex"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE") or env.get("CLAUDE_CODE_ENTRYPOINT") or env.get("SPECKIT_POWERPACK_EXECUTOR", "").lower() == "claude":
        return "claude"
    configured = str(read_model_routing(root).get("active_integration") or "").lower()
    if configured in {"claude", "codex"}:
        return configured
    return "unknown"


def review_route(root: Path, executor: str) -> dict[str, Any]:
    profile = {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh", "sandbox": "read-only"}
    if executor == "claude":
        return {
            "status": "READY",
            "executor": executor,
            "reviewer_mode": "external-codex",
            "spawn_required": True,
            "spawn_target": "codex exec",
            "recursive_spawn_forbidden": True,
            **profile,
        }
    if executor == "codex":
        return {
            "status": "READY",
            "executor": executor,
            "reviewer_mode": "local-codex-session",
            "spawn_required": False,
            "spawn_target": None,
            "recursive_spawn_forbidden": True,
            **profile,
        }
    return {
        "status": "BLOCKED",
        "executor": executor,
        "reason": "unsupported-or-undetected-executor",
        "next_action": "Invoke from Claude Code or Codex, or pass --executor explicitly.",
        **profile,
    }


def cmd_review_route(args: argparse.Namespace) -> int:
    root = find_root()
    executor = detect_executor(root, args.executor)
    result = review_route(root, executor)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "READY" else 15


def load_review_state(root: Path, feature: Path) -> dict[str, Any]:
    return read_json(review_state_path(root, feature), {
        "schema_version": 1,
        "feature": feature_id(root, feature),
        "status": "IDLE",
        "round": 0,
        "head_sha": None,
        "mode": "interactive",
        "executor": None,
        "web_project": None,
        "headless": False,
        "last_updated": None,
    })


def save_review_state(root: Path, feature: Path, data: dict[str, Any]) -> None:
    data["last_updated"] = utc_now()
    write_json(review_state_path(root, feature), data)


def cmd_review_start(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    prereq = evaluate_receipt(root, feature, "implement", {"COMPLETED"}, require_current=False)
    if not prereq["ok"]:
        print(json.dumps({"status": "BLOCKED", "reason": "missing-implement-predecessor", "detail": prereq}))
        return 9
    executor = detect_executor(root, args.executor)
    route = review_route(root, executor)
    if route["status"] != "READY":
        print(json.dumps(route))
        return 15
    state = load_review_state(root, feature)
    state.update({
        "status": "READY_FOR_REVIEW",
        "round": max(0, int(state.get("round", 0))),
        "head_sha": git_head(root),
        "mode": args.mode,
        "executor": executor,
        "reviewer_route": route,
        "web_project": args.project_url,
        "headless": args.headless,
    })
    save_review_state(root, feature, state)
    print(json.dumps(state, ensure_ascii=False))
    return 0


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def finding_identity(provider: str, finding: dict[str, Any]) -> str:
    canonical = "|".join([
        provider.lower(),
        normalize_text(finding.get("title") or finding.get("summary")).lower(),
        normalize_text(finding.get("file") or finding.get("path") or finding.get("location")).lower(),
        normalize_text(finding.get("line")).lower(),
    ])
    return "REV-" + sha_bytes(canonical.encode("utf-8"))[:10]


def read_tasks(feature: Path) -> tuple[Path, str]:
    path = feature / "tasks.md"
    if not path.exists():
        raise SystemExit(f"BLOCKED: tasks.md not found for feature: {feature}")
    return path, path.read_text(encoding="utf-8")


def parse_review_tasks(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        match = REVIEW_LINE.match(line)
        if match:
            result[match.group("id")] = match.groupdict(default="")
    return result


def ensure_review_section(text: str) -> str:
    marker = "## PowerPack Review Findings"
    if marker in text:
        return text
    suffix = "" if text.endswith("\n") else "\n"
    return text + suffix + "\n## PowerPack Review Findings\n\n"


def load_findings_payload(path: str) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        findings = raw.get("findings", [])
        if isinstance(findings, list):
            return [item for item in findings if isinstance(item, dict)]
    raise SystemExit("BLOCKED: findings JSON must be a list or an object with a 'findings' list.")


def review_task_line(fid: str, provider: str, finding: dict[str, Any], round_no: int) -> str:
    severity = normalize_text(finding.get("severity") or finding.get("priority") or "UNSPECIFIED").upper()
    title = normalize_text(finding.get("title") or finding.get("summary") or "Untitled finding")
    evidence = normalize_text(finding.get("evidence") or finding.get("details") or finding.get("description") or "not provided")
    return f"- [ ] {fid} [REVIEW][PENDING][{provider}][{severity}] {title} | evidence: {evidence} | source-round: {round_no}"


def cmd_review_ingest(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    state = load_review_state(root, feature)
    if state.get("status") not in {"READY_FOR_REVIEW", "REVIEWING", "FINDINGS_PENDING", "READY_FOR_NEXT_ROUND"}:
        print(json.dumps({"status": "BLOCKED", "reason": "review-run-not-started"}))
        return 16
    findings = load_findings_payload(args.findings_json)
    round_no = int(state.get("round", 0)) + 1
    tasks_path, text = read_tasks(feature)
    text = ensure_review_section(text)
    existing = parse_review_tasks(text)
    added: list[str] = []
    duplicates: list[str] = []
    for finding in findings:
        fid = finding_identity(args.provider, finding)
        if fid in existing:
            duplicates.append(fid)
            continue
        text += review_task_line(fid, args.provider, finding, round_no) + "\n"
        existing[fid] = {}
        added.append(fid)
    tasks_path.write_text(text, encoding="utf-8")
    state.update({
        "round": round_no,
        "head_sha": git_head(root),
        "status": "FINDINGS_PENDING" if findings else "REVIEW_APPROVED",
        "last_provider": args.provider,
        "last_findings_added": added,
        "last_findings_duplicates": duplicates,
    })
    save_review_state(root, feature, state)
    print(json.dumps({
        "round": round_no,
        "provider": args.provider,
        "added": added,
        "duplicates": duplicates,
        "finding_count": len(findings),
        "status": state["status"],
    }, ensure_ascii=False))
    return 0


def rewrite_task_status(text: str, ids: set[str], status: str, resolution: str | None = None) -> tuple[str, list[str]]:
    changed: list[str] = []
    output: list[str] = []
    for line in text.splitlines():
        match = REVIEW_LINE.match(line)
        if not match or match.group("id") not in ids:
            output.append(line)
            continue
        done = "x" if status == "RESOLVED" else " "
        base = (
            f"- [{done}] {match.group('id')} [REVIEW][{status}]"
            f"[{match.group('provider')}][{match.group('severity')}] {match.group('title')}"
            f" | evidence: {match.group('evidence')} | source-round: {match.group('round')}"
        )
        if resolution:
            base += f" | resolution: {normalize_text(resolution)}"
        elif match.group("resolution"):
            base += f" | resolution: {match.group('resolution')}"
        output.append(base)
        changed.append(match.group("id"))
    return "\n".join(output) + ("\n" if text.endswith("\n") else ""), changed


def current_review_tasks(feature: Path) -> dict[str, dict[str, str]]:
    _, text = read_tasks(feature)
    return parse_review_tasks(text)


def cmd_review_status(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    state = load_review_state(root, feature)
    tasks = current_review_tasks(feature)
    counts: dict[str, int] = {}
    rows: list[dict[str, str]] = []
    for fid, item in tasks.items():
        status = item["status"]
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "id": fid,
            "status": status,
            "provider": item["provider"],
            "severity": item["severity"],
            "title": item["title"],
        })
    print(json.dumps({"review": state, "counts": counts, "findings": rows}, ensure_ascii=False, indent=2))
    return 0


def cmd_review_select(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    path, text = read_tasks(feature)
    tasks = parse_review_tasks(text)
    pending = {fid for fid, item in tasks.items() if item["status"] == "PENDING"}
    if args.all:
        selected = pending
    else:
        selected = set(args.id or [])
        unknown = selected - pending
        if unknown:
            print(json.dumps({"status": "BLOCKED", "reason": "ids-not-pending", "ids": sorted(unknown)}))
            return 17
    if not selected:
        print(json.dumps({"status": "NOOP", "selected": []}))
        return 0
    rewritten, changed = rewrite_task_status(text, selected, "SELECTED")
    path.write_text(rewritten, encoding="utf-8")
    state = load_review_state(root, feature)
    state["status"] = "BATCH_SELECTED"
    state["selected_ids"] = changed
    save_review_state(root, feature, state)
    print(json.dumps({"status": "BATCH_SELECTED", "selected": changed}))
    return 0


def cmd_review_mark_implemented(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    path, text = read_tasks(feature)
    tasks = parse_review_tasks(text)
    ids = set(args.id or []) or {fid for fid, item in tasks.items() if item["status"] == "SELECTED"}
    invalid = {fid for fid in ids if tasks.get(fid, {}).get("status") != "SELECTED"}
    if invalid:
        print(json.dumps({"status": "BLOCKED", "reason": "ids-not-selected", "ids": sorted(invalid)}))
        return 18
    rewritten, changed = rewrite_task_status(text, ids, "IMPLEMENTED", args.evidence)
    path.write_text(rewritten, encoding="utf-8")
    state = load_review_state(root, feature)
    state["status"] = "BATCH_IMPLEMENTED"
    state["implemented_ids"] = changed
    save_review_state(root, feature, state)
    print(json.dumps({"status": "BATCH_IMPLEMENTED", "implemented": changed}))
    return 0


def cmd_review_resolve(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    path, text = read_tasks(feature)
    tasks = parse_review_tasks(text)
    ids = set(args.id or []) or {fid for fid, item in tasks.items() if item["status"] == "IMPLEMENTED"}
    invalid = {fid for fid in ids if tasks.get(fid, {}).get("status") != "IMPLEMENTED"}
    if invalid:
        print(json.dumps({"status": "BLOCKED", "reason": "ids-not-implemented", "ids": sorted(invalid)}))
        return 19
    rewritten, changed = rewrite_task_status(text, ids, "RESOLVED", args.evidence)
    path.write_text(rewritten, encoding="utf-8")
    remaining = [fid for fid, item in parse_review_tasks(rewritten).items() if item["status"] != "RESOLVED"]
    state = load_review_state(root, feature)
    state["status"] = "READY_FOR_NEXT_ROUND" if not remaining else "FINDINGS_PENDING"
    state["resolved_ids"] = changed
    save_review_state(root, feature, state)
    print(json.dumps({"status": state["status"], "resolved": changed, "remaining": remaining}))
    return 0


def cmd_review_abort(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    path = review_state_path(root, feature)
    existed = path.exists()
    if existed:
        path.unlink()
    parent = path.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
    print(json.dumps({
        "status": "ABORTED",
        "local_review_state_removed": existed,
        "tasks_preserved": True,
        "auth_preserved": True,
        "project_bindings_preserved": True,
    }))
    return 0


def cmd_model_route(args: argparse.Namespace) -> int:
    root = find_root()
    data = read_model_routing(root)
    profile = data.get("stages", {}).get(args.stage, "inherit")
    integration = args.integration or data.get("active_integration")
    model = data.get("integrations", {}).get(integration, {}).get(profile)
    print(json.dumps({
        "stage": args.stage,
        "profile": profile,
        "integration": integration,
        "model": model,
        "applied": False,
        "instruction": "Apply only when the active agent supports safe model switching/delegation.",
    }))
    return 0


def classify_limit(text: str) -> dict[str, Any]:
    normalized = normalize_text(text).lower()
    matched = [pattern for pattern in LIMIT_PATTERNS if pattern in normalized]
    return {
        "is_limit": bool(matched),
        "matched": matched,
        "classification": "SESSION_OR_USAGE_LIMIT" if matched else "OTHER",
    }


def cmd_limit_classify(args: argparse.Namespace) -> int:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = args.text or ""
    result = classify_limit(text)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["is_limit"] else 1


def cmd_limit_checkpoint(args: argparse.Namespace) -> int:
    root = find_root()
    payload = {
        "schema_version": 1,
        "status": "PAUSED_LIMIT",
        "executor": args.executor,
        "summary": normalize_text(args.summary),
        "resume_argv": args.resume_argv,
        "refresh_at": args.refresh_at,
        "created_at": utc_now(),
    }
    write_json(limit_state_path(root), payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_limit_status(args: argparse.Namespace) -> int:
    root = find_root()
    path = limit_state_path(root)
    print(json.dumps(read_json(path, {"status": "NONE"}), ensure_ascii=False, indent=2))
    return 0


def cmd_limit_clear(args: argparse.Namespace) -> int:
    root = find_root()
    path = limit_state_path(root)
    existed = path.exists()
    if existed:
        path.unlink()
    print(json.dumps({"status": "CLEARED", "removed": existed}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="powerpack-runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    state = sub.add_parser("state")
    ssub = state.add_subparsers(dest="state_command", required=True)
    p = ssub.add_parser("mark"); p.add_argument("step"); p.add_argument("--status", default="COMPLETED"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_state_mark)
    p = ssub.add_parser("check"); p.add_argument("step"); p.add_argument("--feature-dir"); p.add_argument("--require-status", action="append"); p.add_argument("--require-current", action="store_true"); p.set_defaults(func=cmd_state_check)

    prereq = sub.add_parser("prereq")
    psub = prereq.add_subparsers(dest="prereq_command", required=True)
    p = psub.add_parser("check"); p.add_argument("--step", required=True); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_prereq_check)

    implement = sub.add_parser("implement")
    isub = implement.add_subparsers(dest="implement_command", required=True)
    p = isub.add_parser("begin"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_implement_begin)
    p = isub.add_parser("end"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_implement_end)

    gate = sub.add_parser("gate")
    gsub = gate.add_subparsers(dest="gate_command", required=True)
    p = gsub.add_parser("detect"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_gate_detect)
    p = gsub.add_parser("run"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_gate_run)

    model = sub.add_parser("model")
    msub = model.add_subparsers(dest="model_command", required=True)
    p = msub.add_parser("route"); p.add_argument("--stage", required=True); p.add_argument("--integration"); p.set_defaults(func=cmd_model_route)

    review = sub.add_parser("review")
    rsub = review.add_subparsers(dest="review_command", required=True)
    p = rsub.add_parser("route"); p.add_argument("--executor", choices=["claude", "codex"]); p.set_defaults(func=cmd_review_route)
    p = rsub.add_parser("start"); p.add_argument("--feature-dir"); p.add_argument("--executor", choices=["claude", "codex"]); p.add_argument("--mode", choices=["interactive", "auto"], default="interactive"); p.add_argument("--project-url"); p.add_argument("--headless", action=argparse.BooleanOptionalAction, default=False); p.set_defaults(func=cmd_review_start)
    p = rsub.add_parser("ingest"); p.add_argument("--feature-dir"); p.add_argument("--provider", required=True); p.add_argument("--findings-json", required=True); p.set_defaults(func=cmd_review_ingest)
    p = rsub.add_parser("status"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_review_status)
    p = rsub.add_parser("select"); p.add_argument("--feature-dir"); p.add_argument("--all", action="store_true"); p.add_argument("--id", action="append"); p.set_defaults(func=cmd_review_select)
    p = rsub.add_parser("mark-implemented"); p.add_argument("--feature-dir"); p.add_argument("--id", action="append"); p.add_argument("--evidence"); p.set_defaults(func=cmd_review_mark_implemented)
    p = rsub.add_parser("resolve"); p.add_argument("--feature-dir"); p.add_argument("--id", action="append"); p.add_argument("--evidence", required=True); p.set_defaults(func=cmd_review_resolve)
    p = rsub.add_parser("abort"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_review_abort)

    limit = sub.add_parser("limit")
    lsub = limit.add_subparsers(dest="limit_command", required=True)
    p = lsub.add_parser("classify"); p.add_argument("--text"); p.add_argument("--file"); p.set_defaults(func=cmd_limit_classify)
    p = lsub.add_parser("checkpoint"); p.add_argument("--executor", choices=["claude", "codex"], required=True); p.add_argument("--summary", required=True); p.add_argument("--resume-argv", action="append", required=True); p.add_argument("--refresh-at"); p.set_defaults(func=cmd_limit_checkpoint)
    p = lsub.add_parser("status"); p.set_defaults(func=cmd_limit_status)
    p = lsub.add_parser("clear"); p.set_defaults(func=cmd_limit_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
