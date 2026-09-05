#!/usr/bin/env python3
"""Project-local SpecKit PowerPack runtime.

Stdlib-only by design so generated Spec Kit skills remain usable even when the
global PowerPack CLI was initially invoked through uvx and is no longer on PATH.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

DOC_EXTENSIONS = {".md", ".mdx", ".txt", ".rst", ".adoc", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
DOC_DIRS = {"docs", "doc", "documentation"}


def run(argv: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), text=True, capture_output=True, check=check)


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".specify").is_dir():
            return candidate
    raise SystemExit("BLOCKED: .specify directory not found; this is not an initialized Spec Kit project.")


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
    if branch:
        candidate = root / "specs" / branch
        if candidate.is_dir():
            return candidate.resolve()
        matches = sorted((root / "specs").glob(f"{branch}*")) if (root / "specs").is_dir() else []
        if len(matches) == 1:
            return matches[0].resolve()

    raise SystemExit("BLOCKED: could not resolve current feature directory. Pass --feature-dir explicitly.")


def feature_key(root: Path, feature: Path) -> str:
    try:
        raw = feature.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raw = feature.name
    return raw.replace("/", "__").replace("\\", "__")


def intent_files(feature: Path, step: str) -> list[Path]:
    names = ["spec.md", "plan.md"]
    if step in {"tasks", "analyze", "implement", "converge", "implement-review"}:
        names.append("tasks.md")
    files = [feature / n for n in names if (feature / n).is_file()]
    if step in {"checklist", "checklist-converge"}:
        checklist_dir = feature / "checklists"
        if checklist_dir.is_dir():
            files += sorted(checklist_dir.glob("*.md"))
    return files


def intent_fingerprint(feature: Path, step: str) -> str:
    h = hashlib.sha256()
    for path in intent_files(feature, step):
        h.update(path.name.encode())
        h.update(sha_file(path).encode())
    return h.hexdigest()


def state_path(root: Path, feature: Path) -> Path:
    return root / ".specify" / "powerpack" / "state" / f"{feature_key(root, feature)}.json"


def load_state(root: Path, feature: Path) -> dict[str, Any]:
    path = state_path(root, feature)
    if not path.exists():
        return {"schema_version": 1, "feature": str(feature), "steps": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise SystemExit(f"BLOCKED: corrupt PowerPack state file: {path}")


def save_state(root: Path, feature: Path, data: dict[str, Any]) -> None:
    path = state_path(root, feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git_head(root: Path) -> str | None:
    proc = run(["git", "rev-parse", "HEAD"], root)
    return proc.stdout.strip() if proc.returncode == 0 else None


def checklist_artifact_evidence(feature: Path) -> bool:
    directory = feature / "checklists"
    if not directory.is_dir():
        return False
    for file in directory.glob("*.md"):
        text = file.read_text(encoding="utf-8", errors="replace")
        if "- [ ]" in text or "- [x]" in text.lower():
            return True
    return False


def cmd_state_mark(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    if args.step == "checklist" and not checklist_artifact_evidence(feature):
        print("BLOCKED: checklist receipt cannot be recorded because no checklist artifact exists.")
        return 3
    data = load_state(root, feature)
    data["steps"][args.step] = {
        "status": args.status,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "intent_sha256": intent_fingerprint(feature, args.step),
        "git_head": git_head(root),
    }
    save_state(root, feature, data)
    print(json.dumps({"step": args.step, "status": args.status, "feature": str(feature)}))
    return 0


def evaluate_receipt(root: Path, feature: Path, step: str, allowed: set[str], *, require_current: bool, allow_artifact_evidence: bool) -> dict[str, Any]:
    data = load_state(root, feature)
    receipt = data.get("steps", {}).get(step)
    if receipt is None and step == "checklist" and allow_artifact_evidence and checklist_artifact_evidence(feature):
        return {"ok": True, "step": step, "status": "ARTIFACT_EVIDENCE", "warning": "Existing checklist artifacts accepted as migration evidence."}
    if receipt is None:
        return {"ok": False, "step": step, "reason": "MISSING_RECEIPT"}
    if allowed and receipt.get("status") not in allowed:
        return {"ok": False, "step": step, "reason": "STATUS_MISMATCH", "actual": receipt.get("status"), "required": sorted(allowed)}
    if require_current:
        current = intent_fingerprint(feature, step)
        if receipt.get("intent_sha256") != current:
            return {"ok": False, "step": step, "reason": "STALE_INTENT", "recorded": receipt.get("intent_sha256"), "current": current}
    return {"ok": True, "step": step, "status": receipt.get("status")}


def cmd_state_check(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    result = evaluate_receipt(root, feature, args.step, set(args.require_status or []), require_current=args.require_current, allow_artifact_evidence=args.allow_artifact_evidence)
    result["feature"] = str(feature)
    print(json.dumps(result))
    return 0 if result["ok"] else 4


def cmd_prereq_check(args: argparse.Namespace) -> int:
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir)
    config_path = root / ".specify" / "powerpack" / "prerequisites.json"
    if not config_path.exists():
        print(json.dumps({"ok": True, "step": args.step, "mode": "missing-config"}))
        return 0
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"ok": False, "step": args.step, "reason": "INVALID_PREREQUISITES_CONFIG"}))
        return 8
    if config.get("mode") in {"off", "disabled"}:
        print(json.dumps({"ok": True, "step": args.step, "mode": config.get("mode")}))
        return 0

    results = []
    for req in config.get("steps", {}).get(args.step, []):
        required_step = req.get("step")
        result = evaluate_receipt(root, feature, required_step, set(req.get("statuses") or []), require_current=True, allow_artifact_evidence=bool(req.get("allow_artifact_evidence")))
        results.append(result)
        if not result["ok"]:
            print(json.dumps({"ok": False, "step": args.step, "feature": str(feature), "failed_requirement": result, "next_action": f"speckit-{required_step}"}))
            return 9
    print(json.dumps({"ok": True, "step": args.step, "feature": str(feature), "requirements": results}))
    return 0


def changed_files(root: Path, base: str | None) -> list[str]:
    if base:
        proc = run(["git", "diff", "--name-only", f"{base}...HEAD"], root)
        if proc.returncode == 0:
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    names: set[str] = set()
    proc = run(["git", "status", "--porcelain"], root)
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            value = line[3:].strip()
            if " -> " in value:
                value = value.split(" -> ", 1)[1]
            if value:
                names.add(value)
    return sorted(names)


def is_documentation_only(paths: list[str]) -> bool:
    if not paths:
        return True
    for raw in paths:
        path = Path(raw)
        parts = {p.lower() for p in path.parts}
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
    path = root / ".specify" / "powerpack" / "quality-gates.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def gate_for_project(root: Path, files: list[str]) -> dict[str, Any]:
    if is_documentation_only(files):
        return {"status": "NOT_APPLICABLE", "reason": "documentation-only", "command": None, "changed_files": files}

    custom = read_quality_config(root).get("custom_command")
    if isinstance(custom, list) and custom and all(isinstance(x, str) for x in custom):
        return {"status": "REQUIRED", "reason": "configured", "command": custom, "changed_files": files}

    if (root / "pom.xml").is_file():
        executable = str(root / "mvnw") if (root / "mvnw").is_file() else (shutil.which("mvn") or "mvn")
        return {"status": "REQUIRED", "reason": "maven", "command": [executable, "-B", "verify"], "changed_files": files}
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        executable = str(root / "gradlew") if (root / "gradlew").is_file() else (shutil.which("gradle") or "gradle")
        return {"status": "REQUIRED", "reason": "gradle", "command": [executable, "check"], "changed_files": files}
    if (root / "package.json").is_file():
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        script = next((x for x in ("verify", "check", "test") if x in scripts), None)
        if script:
            if (root / "pnpm-lock.yaml").is_file(): cmd = ["pnpm", "run", script]
            elif (root / "yarn.lock").is_file(): cmd = ["yarn", script]
            elif (root / "bun.lockb").is_file() or (root / "bun.lock").is_file(): cmd = ["bun", "run", script]
            else: cmd = ["npm", "run", script]
            return {"status": "REQUIRED", "reason": "node", "command": cmd, "changed_files": files}
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
        return {"status": "BLOCKED_CONFIGURATION", "reason": "eclipse-project-without-deterministic-build-gate", "command": None, "changed_files": files, "next_action": "Configure .specify/powerpack/quality-gates.json custom_command."}
    return {"status": "BLOCKED_CONFIGURATION", "reason": "unknown-project-architecture", "command": None, "changed_files": files, "next_action": "Configure .specify/powerpack/quality-gates.json custom_command."}


def cmd_gate_detect(args: argparse.Namespace) -> int:
    root = find_root()
    result = gate_for_project(root, changed_files(root, args.base))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] != "BLOCKED_CONFIGURATION" else 7


def cmd_gate_run(args: argparse.Namespace) -> int:
    root = find_root()
    result = gate_for_project(root, changed_files(root, args.base))
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "NOT_APPLICABLE":
        return 0
    if result["status"] == "BLOCKED_CONFIGURATION":
        return 7
    return subprocess.run(result["command"], cwd=str(root)).returncode


def cmd_model_route(args: argparse.Namespace) -> int:
    root = find_root()
    path = root / ".specify" / "powerpack" / "model-routing.json"
    if not path.exists():
        print(json.dumps({"stage": args.stage, "profile": "inherit", "model": None, "applied": False}))
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    profile = data.get("stages", {}).get(args.stage, "inherit")
    integration = args.integration or data.get("active_integration")
    model = data.get("integrations", {}).get(integration, {}).get(profile)
    print(json.dumps({"stage": args.stage, "profile": profile, "integration": integration, "model": model, "applied": False, "instruction": "Apply this route only if the active agent supports safe model switching or delegated execution; otherwise continue with the current model."}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="powerpack-runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    state = sub.add_parser("state")
    ssub = state.add_subparsers(dest="state_command", required=True)
    p = ssub.add_parser("mark"); p.add_argument("step"); p.add_argument("--status", default="COMPLETED"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_state_mark)
    p = ssub.add_parser("check"); p.add_argument("step"); p.add_argument("--feature-dir"); p.add_argument("--require-status", action="append"); p.add_argument("--require-current", action="store_true"); p.add_argument("--allow-artifact-evidence", action="store_true"); p.set_defaults(func=cmd_state_check)

    prereq = sub.add_parser("prereq")
    psub = prereq.add_subparsers(dest="prereq_command", required=True)
    p = psub.add_parser("check"); p.add_argument("--step", required=True); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_prereq_check)

    gate = sub.add_parser("gate")
    gsub = gate.add_subparsers(dest="gate_command", required=True)
    p = gsub.add_parser("detect"); p.add_argument("--base"); p.set_defaults(func=cmd_gate_detect)
    p = gsub.add_parser("run"); p.add_argument("--base"); p.set_defaults(func=cmd_gate_run)

    model = sub.add_parser("model")
    msub = model.add_subparsers(dest="model_command", required=True)
    p = msub.add_parser("route"); p.add_argument("--stage", required=True); p.add_argument("--integration"); p.set_defaults(func=cmd_model_route)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
