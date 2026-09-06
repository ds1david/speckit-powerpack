from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

SCHEMA_VERSION = "2.0"
MANIFEST_SCHEMA_VERSION = "1.0"
FRONTS = (
    "SPEC_COMPLIANCE",
    "BEHAVIORAL_REGRESSION",
    "ARCHITECTURE_AND_CONTRACTS",
    "STATE_CONCURRENCY_AND_FAILURES",
    "PERSISTENCE_DETERMINISM_IDEMPOTENCY",
    "TESTS_AND_COMPOSITION_ROOT",
    "DOCUMENTATION_AND_OPERABILITY",
    "SECURITY_AND_SCOPE",
)
FRONT_STATUSES = {"PASS", "FINDINGS", "BLOCKED", "NOT_APPLICABLE"}
REQUIREMENT_STATUSES = {"PASS", "PARTIAL", "FAIL", "NOT_APPLICABLE"}
BASELINE_RESULTS = {"PRESERVED", "CHANGED_AS_SPECIFIED", "REGRESSION", "NOT_APPLICABLE"}
PREVIOUS_FINDING_STATUSES = {"RESOLVED", "PARTIALLY_RESOLVED", "NOT_RESOLVED", "REGRESSED"}
VERDICTS = {"APPROVED", "CHANGES_REQUIRED", "BLOCKED"}
CHALLENGE_RESULTS = {"SURVIVED", "FINDING", "BLOCKED", "NOT_APPLICABLE"}
FINDING_FIELDS = {
    "id", "severity", "category", "title", "file", "line", "evidence",
    "failure_scenario", "behavioral_impact", "required_change", "acceptance_criteria",
}
CONTEXT_FIELDS = {"spec_id", "base_ref", "base_sha", "merge_base", "head_sha", "snapshot_sha256"}
HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
REQUIREMENT_ID = re.compile(r"\b((?:FR|NFR|REQ|SC|AC|UC)-?\d{1,4})\b", re.IGNORECASE)
REPEATED_PREFIX = "BLOCKED_REPEATED_FINDING:"
MANIFEST_PREFIX = "BLOCKED_REVIEW_CONTEXT:"
DEFAULT_MANIFEST_RELATIVE = Path(".specify/powerpack/runtime/review-context.json")
DEFAULT_WEB_PROMPT_RELATIVE = Path(".specify/powerpack/runtime/web-review-prompt.txt")
DEFAULT_ESCAPE_LOG_RELATIVE = Path(".specify/powerpack/runtime/review-escapes.jsonl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return data


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _run(root: Path, *argv: str) -> str:
    proc = subprocess.run(list(argv), cwd=str(root), text=True, capture_output=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "command failed").strip()
        raise RuntimeError(f"{' '.join(argv)}: {detail}")
    return proc.stdout.strip()


def find_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".specify").is_dir():
            return candidate
    return None


def resolve_feature_dir(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        resolved = (path if path.is_absolute() else root / path).resolve()
        if not resolved.is_dir():
            raise RuntimeError(f"feature directory does not exist: {resolved}")
        return resolved
    branch = _run(root, "git", "branch", "--show-current")
    specs = root / "specs"
    direct = specs / branch
    if direct.is_dir():
        return direct.resolve()
    matches = sorted(path for path in specs.glob(f"{branch}*") if path.is_dir()) if specs.is_dir() else []
    if len(matches) == 1:
        return matches[0].resolve()
    raise RuntimeError("could not resolve feature directory; pass --feature-dir explicitly")


def finding_fingerprint(finding: dict[str, Any]) -> str:
    canonical = "|".join([
        _norm(finding.get("category")),
        _norm(finding.get("title")),
        _norm(finding.get("file")),
        _norm(finding.get("line")),
        _norm(finding.get("failure_scenario")),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _spec_artifacts(root: Path, feature: Path) -> list[str]:
    paths: list[Path] = []
    for name in ("spec.md", "plan.md", "tasks.md", "research.md", "data-model.md", "quickstart.md"):
        candidate = feature / name
        if candidate.is_file():
            paths.append(candidate)
    for dirname in ("contracts", "checklists"):
        directory = feature / dirname
        if directory.is_dir():
            paths.extend(sorted(path for path in directory.rglob("*") if path.is_file()))
    result: list[str] = []
    for path in paths:
        try:
            result.append(path.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            result.append(path.resolve().as_posix())
    return sorted(dict.fromkeys(result))


def _requirement_ids(root: Path, artifacts: list[str]) -> list[str]:
    ids: set[str] = set()
    for raw in artifacts:
        path = root / raw
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".rst", ".adoc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ids.update(match.group(1).upper() for match in REQUIREMENT_ID.finditer(text))
    return sorted(ids)


def _detect_base_ref(root: Path, explicit: str | None) -> str:
    if explicit:
        _run(root, "git", "rev-parse", "--verify", explicit)
        return explicit
    for ref in ("origin/main", "main", "origin/master", "master"):
        proc = subprocess.run(["git", "rev-parse", "--verify", ref], cwd=str(root), text=True, capture_output=True)
        if proc.returncode == 0:
            return ref
    raise RuntimeError("could not detect base ref; pass --base-ref explicitly")


def _changed_files(root: Path, merge_base: str) -> list[str]:
    proc = subprocess.run(["git", "diff", "--name-only", "-z", merge_base], cwd=str(root), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"git diff failed").decode(errors="replace").strip())
    changed = {item.decode(errors="replace") for item in proc.stdout.split(b"\0") if item}
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=str(root),
        capture_output=True,
    )
    if untracked.returncode == 0:
        changed.update(item.decode(errors="replace") for item in untracked.stdout.split(b"\0") if item)
    return sorted(changed)


def _snapshot_digest(root: Path, identity: dict[str, Any], changed: list[str], artifacts: list[str]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for raw in sorted(set(changed) | set(artifacts)):
        h.update(raw.encode("utf-8"))
        path = root / raw
        if path.is_file():
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        else:
            h.update(b"<missing-or-deleted>")
    return h.hexdigest()


def build_manifest(root: Path, feature: Path, base_ref: str | None = None) -> dict[str, Any]:
    root, feature = root.resolve(), feature.resolve()
    selected_base = _detect_base_ref(root, base_ref)
    base_sha = _run(root, "git", "rev-parse", selected_base)
    head_sha = _run(root, "git", "rev-parse", "HEAD")
    merge_base = _run(root, "git", "merge-base", base_sha, head_sha)
    changed = _changed_files(root, merge_base)
    artifacts = _spec_artifacts(root, feature)
    try:
        spec_id = feature.relative_to(root).as_posix()
    except ValueError:
        spec_id = feature.name
    requirements = _requirement_ids(root, artifacts)
    identity = {
        "spec_id": spec_id,
        "base_ref": selected_base,
        "base_sha": base_sha,
        "merge_base": merge_base,
        "head_sha": head_sha,
    }
    digest = _snapshot_digest(root, identity, changed, artifacts)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "review_context": {**identity, "snapshot_sha256": digest},
        "spec_artifacts": artifacts,
        "requirements": requirements,
        "changed_files": changed,
        "required_context_files": sorted(dict.fromkeys([*artifacts, *changed])),
        "policy": {
            "changed_files_exact_match": True,
            "requirements_exact_match": bool(requirements),
            "spec_artifacts_must_be_inspected": True,
            "inspection_evidence_required": True,
            "verdict_challenge_required": True,
            "context_gaps_block_approval": True,
            "manifest_freshness_required": True,
        },
    }


def _manifest_path_from_cwd() -> Path | None:
    root = find_project_root()
    return root / DEFAULT_MANIFEST_RELATIVE if root else None


def load_manifest_for_validation(explicit: str | None) -> dict[str, Any] | None:
    if explicit:
        return load_json(Path(explicit))
    auto = _manifest_path_from_cwd()
    return load_json(auto) if auto and auto.is_file() else None


def validate_manifest_freshness(manifest: dict[str, Any], root: Path | None = None) -> list[str]:
    """Prove that a persisted manifest still describes the current repository/workspace."""
    project_root = root or find_project_root()
    if project_root is None:
        return [f"{MANIFEST_PREFIX} cannot prove manifest freshness because project root is unavailable"]
    project_root = project_root.resolve()
    context = manifest.get("review_context")
    if not isinstance(context, dict):
        return [f"{MANIFEST_PREFIX} manifest review_context is missing"]
    spec_id = str(context.get("spec_id") or "").strip()
    base_ref = str(context.get("base_ref") or "").strip()
    if not spec_id or not base_ref:
        return [f"{MANIFEST_PREFIX} manifest spec_id/base_ref is incomplete"]
    feature = (project_root / spec_id).resolve()
    try:
        feature.relative_to(project_root)
    except ValueError:
        return [f"{MANIFEST_PREFIX} manifest spec_id resolves outside project root: {spec_id}"]
    if not feature.is_dir():
        return [f"{MANIFEST_PREFIX} manifest feature directory no longer exists: {spec_id}"]
    try:
        current = build_manifest(project_root, feature, base_ref)
    except RuntimeError as exc:
        return [f"{MANIFEST_PREFIX} cannot recompute current snapshot: {exc}"]

    errors: list[str] = []
    expected_context = manifest.get("review_context") if isinstance(manifest.get("review_context"), dict) else {}
    current_context = current["review_context"]
    for field in sorted(CONTEXT_FIELDS):
        if current_context.get(field) != expected_context.get(field):
            errors.append(
                f"{MANIFEST_PREFIX} manifest is stale: current review_context.{field} "
                f"is {current_context.get(field)!r}, manifest has {expected_context.get(field)!r}"
            )
    for field in ("spec_artifacts", "requirements", "changed_files", "required_context_files"):
        current_values = _list(current.get(field))
        manifest_values = _list(manifest.get(field))
        if current_values != manifest_values:
            errors.append(f"{MANIFEST_PREFIX} manifest is stale: current {field} differs from persisted manifest")
    return errors


def validate_manifest_bound_review(review: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"{MANIFEST_PREFIX} manifest schema_version must be {MANIFEST_SCHEMA_VERSION}"]
    expected_context = manifest.get("review_context") if isinstance(manifest.get("review_context"), dict) else {}
    actual_context = review.get("review_context") if isinstance(review.get("review_context"), dict) else {}
    for field in sorted(CONTEXT_FIELDS):
        if actual_context.get(field) != expected_context.get(field):
            errors.append(
                f"{MANIFEST_PREFIX} review_context.{field} does not match manifest "
                f"(expected={expected_context.get(field)!r}, actual={actual_context.get(field)!r})"
            )
    coverage = review.get("coverage") if isinstance(review.get("coverage"), dict) else {}
    actual_changed = {str(item) for item in _list(coverage.get("changed_files"))}
    expected_changed = {str(item) for item in _list(manifest.get("changed_files"))}
    if actual_changed != expected_changed:
        errors.append(
            f"{MANIFEST_PREFIX} coverage.changed_files must exactly match manifest; "
            f"missing={sorted(expected_changed - actual_changed)}, extra={sorted(actual_changed - expected_changed)}"
        )
    inspected = {str(item) for item in _list(coverage.get("inspected_files"))}
    required_context = {str(item) for item in _list(manifest.get("required_context_files"))}
    missing_context = sorted(required_context - inspected)
    if missing_context:
        errors.append(f"{MANIFEST_PREFIX} required context files were not inspected: {', '.join(missing_context)}")
    expected_requirements = {str(item) for item in _list(manifest.get("requirements"))}
    actual_requirements = {
        str(item.get("id"))
        for item in _list(coverage.get("requirements"))
        if isinstance(item, dict) and item.get("id")
    }
    if expected_requirements and actual_requirements != expected_requirements:
        errors.append(
            f"{MANIFEST_PREFIX} requirements coverage must exactly match manifest; "
            f"missing={sorted(expected_requirements - actual_requirements)}, "
            f"extra={sorted(actual_requirements - expected_requirements)}"
        )
    evidence_by_file: set[str] = set()
    for index, item in enumerate(_list(coverage.get("inspection_evidence"))):
        if not isinstance(item, dict):
            errors.append(f"{MANIFEST_PREFIX} coverage.inspection_evidence[{index}] must be an object")
            continue
        raw_file = str(item.get("file") or "")
        evidence = str(item.get("evidence") or "").strip()
        if raw_file:
            evidence_by_file.add(raw_file)
        if not raw_file or len(evidence) < 8:
            errors.append(f"{MANIFEST_PREFIX} coverage.inspection_evidence[{index}] requires file and concrete evidence")
    missing_evidence = sorted(expected_changed - evidence_by_file)
    if missing_evidence:
        errors.append(f"{MANIFEST_PREFIX} every changed file requires inspection evidence: {', '.join(missing_evidence)}")
    challenge = coverage.get("verdict_challenge")
    if not isinstance(challenge, dict):
        errors.append(f"{MANIFEST_PREFIX} coverage.verdict_challenge is required")
    else:
        result = challenge.get("result")
        if result not in CHALLENGE_RESULTS:
            errors.append(f"{MANIFEST_PREFIX} coverage.verdict_challenge.result is invalid")
        if not str(challenge.get("strongest_counterexample") or "").strip():
            errors.append(f"{MANIFEST_PREFIX} coverage.verdict_challenge.strongest_counterexample is required")
        if not _list(challenge.get("evidence")):
            errors.append(f"{MANIFEST_PREFIX} coverage.verdict_challenge.evidence must not be empty")
        if review.get("verdict") == "APPROVED" and result not in {"SURVIVED", "NOT_APPLICABLE"}:
            errors.append(f"{MANIFEST_PREFIX} APPROVED requires verdict challenge SURVIVED or NOT_APPLICABLE")
    context_gaps = coverage.get("context_gaps")
    if not isinstance(context_gaps, list):
        errors.append(f"{MANIFEST_PREFIX} coverage.context_gaps must be a list")
    elif review.get("verdict") == "APPROVED" and context_gaps:
        errors.append(f"{MANIFEST_PREFIX} APPROVED is forbidden while context_gaps is non-empty")
    return errors


def validate_review(
    review: dict[str, Any],
    previous: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if review.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    verdict = review.get("verdict")
    if verdict not in VERDICTS:
        errors.append(f"verdict must be one of {sorted(VERDICTS)}")

    context = review.get("review_context")
    if not isinstance(context, dict):
        errors.append("review_context must be an object")
        context = {}
    for field in sorted(CONTEXT_FIELDS):
        if not context.get(field):
            errors.append(f"review_context.{field} is required")
    for field in ("base_sha", "merge_base", "head_sha"):
        value = context.get(field)
        if value and not HEX40.match(str(value)):
            errors.append(f"review_context.{field} must be a full 40-character Git SHA")
    digest = context.get("snapshot_sha256")
    if digest and not HEX64.match(str(digest)):
        errors.append("review_context.snapshot_sha256 must be a 64-character SHA-256 digest")

    coverage = review.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
        coverage = {}
    changed = _list(coverage.get("changed_files"))
    inspected = _list(coverage.get("inspected_files"))
    requirements = _list(coverage.get("requirements"))
    baselines = _list(coverage.get("baseline_scenarios"))
    previous_findings = _list(coverage.get("previous_findings"))
    fronts = _list(coverage.get("fronts"))

    if not changed:
        errors.append("coverage.changed_files must not be empty")
    if not inspected:
        errors.append("coverage.inspected_files must not be empty")
    missing_inspection = sorted(set(changed) - set(inspected))
    if missing_inspection:
        errors.append("every changed file must be inspected: " + ", ".join(missing_inspection))
    if context.get("spec_id") and not requirements:
        errors.append("coverage.requirements must not be empty when spec_id is present")
    if not baselines:
        errors.append("coverage.baseline_scenarios must not be empty")

    for index, item in enumerate(requirements):
        if not isinstance(item, dict) or item.get("status") not in REQUIREMENT_STATUSES:
            errors.append(f"coverage.requirements[{index}].status is invalid")
        elif not _list(item.get("evidence")):
            errors.append(f"coverage.requirements[{index}].evidence must not be empty")
    for index, item in enumerate(baselines):
        if not isinstance(item, dict) or item.get("result") not in BASELINE_RESULTS:
            errors.append(f"coverage.baseline_scenarios[{index}].result is invalid")
        elif not _list(item.get("evidence")):
            errors.append(f"coverage.baseline_scenarios[{index}].evidence must not be empty")

    front_names: list[str] = []
    for index, item in enumerate(fronts):
        if not isinstance(item, dict):
            errors.append(f"coverage.fronts[{index}] must be an object")
            continue
        name, status = item.get("name"), item.get("status")
        if name:
            front_names.append(str(name))
        if status not in FRONT_STATUSES:
            errors.append(f"coverage.fronts[{index}].status is invalid")
        if not _list(item.get("evidence")):
            errors.append(f"coverage.fronts[{index}].evidence must not be empty")
    if set(front_names) != set(FRONTS) or len(front_names) != len(FRONTS):
        errors.append("coverage.fronts must contain every required review front exactly once")

    findings = _list(review.get("findings"))
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        missing = sorted(field for field in FINDING_FIELDS if field not in finding)
        if missing:
            errors.append(f"findings[{index}] missing fields: {', '.join(missing)}")
        if not _list(finding.get("acceptance_criteria")):
            errors.append(f"findings[{index}].acceptance_criteria must not be empty")

    seen_previous: set[str] = set()
    prior_status_by_id: dict[str, str] = {}
    for index, item in enumerate(previous_findings):
        if not isinstance(item, dict):
            errors.append(f"coverage.previous_findings[{index}] must be an object")
            continue
        item_id = item.get("id")
        if item_id:
            seen_previous.add(str(item_id))
            prior_status_by_id[str(item_id)] = str(item.get("status") or "")
        if item.get("status") not in PREVIOUS_FINDING_STATUSES:
            errors.append(f"coverage.previous_findings[{index}].status is invalid")
        if not _list(item.get("evidence")):
            errors.append(f"coverage.previous_findings[{index}].evidence must not be empty")

    if previous is not None:
        previous_items = [item for item in _list(previous.get("findings")) if isinstance(item, dict)]
        expected = {str(item.get("id")) for item in previous_items if item.get("id")}
        if seen_previous != expected:
            errors.append("coverage.previous_findings must contain exactly every finding id from the previous review")
        resolved_fingerprints: dict[str, str] = {}
        for item in previous_items:
            item_id = str(item.get("id") or "")
            if item_id and prior_status_by_id.get(item_id) == "RESOLVED":
                resolved_fingerprints[finding_fingerprint(item)] = item_id
        for current in findings:
            if not isinstance(current, dict):
                continue
            fingerprint = finding_fingerprint(current)
            if fingerprint in resolved_fingerprints:
                previous_id = resolved_fingerprints[fingerprint]
                errors.append(
                    f"{REPEATED_PREFIX} previous finding {previous_id} was declared RESOLVED "
                    f"but materially reappeared as {current.get('id')}"
                )
    elif previous_findings:
        try:
            round_no = int(review.get("round", 1) or 1)
        except (TypeError, ValueError):
            round_no = 1
        if round_no <= 1:
            errors.append("coverage.previous_findings must be empty on the first review round")

    front_statuses = {item.get("status") for item in fronts if isinstance(item, dict)}
    if verdict == "APPROVED":
        if findings:
            errors.append("APPROVED requires findings: []")
        if any(item.get("status") in {"PARTIAL", "FAIL"} for item in requirements if isinstance(item, dict)):
            errors.append("APPROVED does not allow PARTIAL/FAIL requirements")
        if any(item.get("result") == "REGRESSION" for item in baselines if isinstance(item, dict)):
            errors.append("APPROVED does not allow baseline REGRESSION")
        if any(item.get("status") != "RESOLVED" for item in previous_findings if isinstance(item, dict)):
            errors.append("APPROVED requires every previous finding to be RESOLVED")
        if front_statuses - {"PASS", "NOT_APPLICABLE"}:
            errors.append("APPROVED requires every review front to PASS or be NOT_APPLICABLE")
    elif verdict == "CHANGES_REQUIRED":
        if not findings:
            errors.append("CHANGES_REQUIRED requires at least one finding")
        if "FINDINGS" not in front_statuses:
            errors.append("CHANGES_REQUIRED requires at least one FINDINGS review front")
    elif verdict == "BLOCKED" and "BLOCKED" not in front_statuses:
        errors.append("BLOCKED requires at least one BLOCKED review front")

    if manifest is not None:
        errors.extend(validate_manifest_bound_review(review, manifest))
    return errors


def classify_errors(errors: list[str]) -> str:
    if any(error.startswith(REPEATED_PREFIX) for error in errors):
        return "BLOCKED_REPEATED_FINDING"
    if any(error.startswith(MANIFEST_PREFIX) for error in errors):
        return "BLOCKED_REVIEW_CONTEXT"
    return "BLOCKED_REVIEW_CONTRACT" if errors else "VALID"


def cmd_manifest(args: argparse.Namespace) -> int:
    root = find_project_root()
    if not root:
        print(json.dumps({"status": "BLOCKED", "reason": "project-root-not-found"}))
        return 4
    try:
        feature = resolve_feature_dir(root, args.feature_dir)
        manifest = build_manifest(root, feature, args.base_ref)
    except RuntimeError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 4
    output = Path(args.output) if args.output else root / DEFAULT_MANIFEST_RELATIVE
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(
        {"status": "READY", "manifest": str(output), "review_context": manifest["review_context"]},
        ensure_ascii=False,
    ))
    return 0


def _freshness_errors(manifest: dict[str, Any] | None) -> list[str]:
    return validate_manifest_freshness(manifest) if manifest is not None else []


def cmd_validate(args: argparse.Namespace) -> int:
    review = load_json(Path(args.input))
    previous = load_json(Path(args.previous)) if args.previous else None
    manifest = load_manifest_for_validation(args.manifest)
    errors = validate_review(review, previous, manifest)
    freshness = _freshness_errors(manifest)
    errors.extend(freshness)
    classification = classify_errors(errors)
    print(json.dumps({
        "valid": not errors,
        "classification": classification,
        "schema_version": SCHEMA_VERSION,
        "manifest_bound": manifest is not None,
        "manifest_fresh": manifest is not None and not freshness,
        "verdict": review.get("verdict"),
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    if not errors:
        return 0
    if classification == "BLOCKED_REPEATED_FINDING":
        return 3
    if classification == "BLOCKED_REVIEW_CONTEXT":
        return 4
    return 2


def web_prompt(manifest: dict[str, Any]) -> str:
    embedded = json.dumps(manifest, ensure_ascii=False, indent=2)
    return f"""You are the mandatory independent ChatGPT Project Web code-review gate for SpecKit PowerPack.

Review the repository snapshot described by the immutable REVIEW CONTEXT MANIFEST below. Use the Project-linked repository/GitHub context to inspect the exact head SHA. Do not trust prior approvals, PR summaries, green CI, implementer claims, or conclusions from another reviewer.

Mandatory behavior:
1. Verify exact `head_sha`, `base_sha`, `merge_base`, SPEC artifacts, and every changed file. If exact-snapshot access cannot be proved, return verdict `BLOCKED`; never approve by absence of evidence.
2. Read all `spec_artifacts` and every `changed_file`, then inspect callers/callees/configuration/tests needed for blast radius.
3. Cover every manifest requirement ID exactly once in `coverage.requirements`.
4. Put every manifest `required_context_file` in `coverage.inspected_files`.
5. Add `coverage.inspection_evidence` with one concrete evidence record for every changed file.
6. Execute all eight mandatory review fronts from the PowerPack Deep Review Evidence Protocol.
7. Before the verdict, actively try to break the implementation. Return `coverage.verdict_challenge` with the strongest remaining counterexample and evidence.
8. Return `coverage.context_gaps` as a list. If Project conversation/context contains a material constraint not represented in repository evidence, report it and do not APPROVE. Project-only knowledge must become repository evidence/finding, not hidden reviewer memory.
9. Return exactly one schema `2.0` JSON review object and no prose outside it.

REVIEW CONTEXT MANIFEST:
{embedded}
"""


def cmd_web_prompt(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else _manifest_path_from_cwd()
    if not manifest_path or not manifest_path.is_file():
        print(json.dumps({"status": "BLOCKED", "reason": "review-context-manifest-missing"}))
        return 4
    manifest = load_json(manifest_path)
    freshness = validate_manifest_freshness(manifest)
    if freshness:
        print(json.dumps(
            {"status": "BLOCKED", "reason": "stale-review-context-manifest", "errors": freshness},
            ensure_ascii=False,
        ))
        return 4
    prompt = web_prompt(manifest)
    root = find_project_root()
    output = Path(args.output) if args.output else ((root / DEFAULT_WEB_PROMPT_RELATIVE) if root else None)
    if output:
        if root and not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(prompt, encoding="utf-8")
        print(json.dumps({"status": "READY", "prompt": str(output)}, ensure_ascii=False))
    else:
        print(prompt)
    return 0


def _same_snapshot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    lctx = left.get("review_context") if isinstance(left.get("review_context"), dict) else {}
    rctx = right.get("review_context") if isinstance(right.get("review_context"), dict) else {}
    return all(lctx.get(field) == rctx.get(field) for field in CONTEXT_FIELDS)


def cmd_record_escape(args: argparse.Namespace) -> int:
    sol = load_json(Path(args.sol_review))
    web = load_json(Path(args.web_review))
    manifest = load_manifest_for_validation(args.manifest)
    if manifest is None:
        print(json.dumps({"status": "BLOCKED", "reason": "review-context-manifest-missing"}))
        return 4
    freshness = validate_manifest_freshness(manifest)
    if freshness:
        print(json.dumps(
            {"status": "BLOCKED", "reason": "stale-review-context-manifest", "errors": freshness},
            ensure_ascii=False,
        ))
        return 4
    sol_errors = validate_review(sol, manifest=manifest)
    web_errors = validate_review(web, manifest=manifest)
    if sol_errors or web_errors:
        print(json.dumps({"status": "BLOCKED", "sol_errors": sol_errors, "web_errors": web_errors}, ensure_ascii=False))
        return 4
    if not _same_snapshot(sol, web):
        print(json.dumps({"status": "BLOCKED", "reason": "review-snapshots-differ"}))
        return 4
    web_findings = _list(web.get("findings"))
    if sol.get("verdict") != "APPROVED" or not web_findings:
        print(json.dumps({"status": "NO_ESCAPE", "recorded": False}))
        return 0
    event = {
        "schema_version": 1,
        "recorded_at": utc_now(),
        "snapshot": manifest.get("review_context"),
        "local_reviewer": sol.get("reviewer") or "codex-sol",
        "web_reviewer": web.get("reviewer") or "chatgpt-web",
        "escaped_finding_count": len(web_findings),
        "escaped_findings": [
            {
                "id": item.get("id"),
                "severity": item.get("severity"),
                "category": item.get("category"),
                "title": item.get("title"),
                "file": item.get("file"),
                "line": item.get("line"),
            }
            for item in web_findings
            if isinstance(item, dict)
        ],
    }
    root = find_project_root()
    output = Path(args.output) if args.output else ((root / DEFAULT_ESCAPE_LOG_RELATIVE) if root else None)
    if not output:
        print(json.dumps({"status": "BLOCKED", "reason": "escape-log-output-not-resolved"}))
        return 4
    if root and not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps(
        {"status": "REVIEW_ESCAPE", "recorded": True, "output": str(output), "event": event},
        ensure_ascii=False,
    ))
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    sol = load_json(Path(args.sol_review))
    web = load_json(Path(args.web_review))
    manifest = load_manifest_for_validation(args.manifest)
    if manifest is None:
        print(json.dumps({"status": "BLOCKED", "reason": "review-context-manifest-missing"}))
        return 4
    freshness = validate_manifest_freshness(manifest)
    if freshness:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "stale-review-context-manifest",
            "errors": freshness,
        }, ensure_ascii=False))
        return 4
    sol_errors = validate_review(sol, manifest=manifest)
    web_errors = validate_review(web, manifest=manifest)
    if sol_errors or web_errors:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "invalid-review-contract",
            "errors": {"sol": sol_errors, "web": web_errors},
        }, ensure_ascii=False))
        return 4
    if not _same_snapshot(sol, web):
        print(json.dumps({"status": "BLOCKED", "reason": "review-snapshots-differ"}))
        return 4
    if sol.get("verdict") != "APPROVED" or web.get("verdict") != "APPROVED":
        print(json.dumps({
            "status": "CHANGES_REQUIRED",
            "sol": sol.get("verdict"),
            "web": web.get("verdict"),
        }))
        return 5
    print(json.dumps({"status": "COMPLETE", "snapshot": manifest.get("review_context")}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="powerpack-review-protocol")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("manifest")
    p.add_argument("--feature-dir")
    p.add_argument("--base-ref")
    p.add_argument("--output")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("validate")
    p.add_argument("--input", required=True)
    p.add_argument("--previous")
    p.add_argument("--manifest")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("web-prompt")
    p.add_argument("--manifest")
    p.add_argument("--output")
    p.set_defaults(func=cmd_web_prompt)

    p = sub.add_parser("record-escape")
    p.add_argument("--sol-review", required=True)
    p.add_argument("--web-review", required=True)
    p.add_argument("--manifest")
    p.add_argument("--output")
    p.set_defaults(func=cmd_record_escape)

    p = sub.add_parser("finalize")
    p.add_argument("--sol-review", required=True)
    p.add_argument("--web-review", required=True)
    p.add_argument("--manifest")
    p.set_defaults(func=cmd_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
