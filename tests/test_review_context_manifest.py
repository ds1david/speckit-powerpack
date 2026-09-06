from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "src" / "speckit_powerpack" / "assets" / "runtime" / "powerpack_review_protocol.py"
spec = importlib.util.spec_from_file_location("powerpack_review_protocol_manifest", MODULE_PATH)
assert spec and spec.loader
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


def manifest() -> dict:
    return {
        "schema_version": "1.0",
        "review_context": {
            "spec_id": "specs/001-test",
            "base_ref": "main",
            "base_sha": "a" * 40,
            "merge_base": "a" * 40,
            "head_sha": "b" * 40,
            "snapshot_sha256": "c" * 64,
        },
        "spec_artifacts": ["specs/001-test/spec.md"],
        "requirements": ["FR-001"],
        "changed_files": ["src/a.py"],
        "required_context_files": ["specs/001-test/spec.md", "src/a.py"],
    }


def review(*, verdict: str = "APPROVED", findings=None) -> dict:
    findings = [] if findings is None else findings
    fronts = []
    for name in protocol.FRONTS:
        status = "PASS"
        if verdict == "CHANGES_REQUIRED" and name == "SPEC_COMPLIANCE":
            status = "FINDINGS"
        if verdict == "BLOCKED" and name == "SPEC_COMPLIANCE":
            status = "BLOCKED"
        fronts.append({"name": name, "status": status, "evidence": ["concrete file/behavior evidence"]})
    return {
        "schema_version": "2.0",
        "reviewer": "codex-sol",
        "round": 1,
        "verdict": verdict,
        "summary": "summary",
        "review_context": manifest()["review_context"],
        "coverage": {
            "changed_files": ["src/a.py"],
            "inspected_files": ["src/a.py", "specs/001-test/spec.md"],
            "inspection_evidence": [
                {"file": "src/a.py", "evidence": "read complete change and production call path"}
            ],
            "requirements": [
                {"id": "FR-001", "status": "PASS", "evidence": ["spec and implementation evidence"]}
            ],
            "baseline_scenarios": [
                {"scenario": "happy path", "result": "PRESERVED", "evidence": ["behavior/test evidence"]}
            ],
            "previous_findings": [],
            "fronts": fronts,
            "verdict_challenge": {
                "strongest_counterexample": "duplicate concurrent delivery",
                "result": "SURVIVED" if verdict == "APPROVED" else "FINDING",
                "evidence": ["state transition and test evidence"],
            },
            "context_gaps": [],
        },
        "findings": findings,
    }


def test_manifest_bound_review_is_valid():
    assert protocol.validate_review(review(), manifest=manifest()) == []


def test_manifest_rejects_partial_requirement_coverage():
    current = review()
    current["coverage"]["requirements"] = []
    errors = protocol.validate_review(current, manifest=manifest())
    assert any("requirements coverage must exactly match manifest" in error for error in errors)
    assert protocol.classify_errors(errors) == "BLOCKED_REVIEW_CONTEXT"


def test_manifest_rejects_changed_file_set_drift():
    current = review()
    current["coverage"]["changed_files"] = ["src/a.py", "src/not-in-snapshot.py"]
    current["coverage"]["inspected_files"].append("src/not-in-snapshot.py")
    errors = protocol.validate_review(current, manifest=manifest())
    assert any("changed_files must exactly match manifest" in error for error in errors)


def test_manifest_rejects_missing_changed_file_evidence():
    current = review()
    current["coverage"]["inspection_evidence"] = []
    errors = protocol.validate_review(current, manifest=manifest())
    assert any("every changed file requires inspection evidence" in error for error in errors)


def test_project_only_context_gap_blocks_approval():
    current = review()
    current["coverage"]["context_gaps"] = ["Project conversation adds a retry invariant absent from repository evidence"]
    errors = protocol.validate_review(current, manifest=manifest())
    assert any("context_gaps" in error for error in errors)


def test_web_prompt_binds_exact_snapshot():
    prompt = protocol.web_prompt(manifest())
    assert "mandatory independent ChatGPT Project Web" in prompt
    assert "exact `head_sha`" in prompt
    assert "FR-001" in prompt
    assert "context_gaps" in prompt


def test_manifest_builder_uses_git_snapshot(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".specify").mkdir()
    feature = repo / "specs" / "001-test"
    feature.mkdir(parents=True)
    (feature / "spec.md").write_text("Requirement **FR-001** must work.\n", encoding="utf-8")
    (repo / "src").mkdir()
    target = repo / "src" / "a.py"
    target.write_text("print(1)\n", encoding="utf-8")

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "PowerPack Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "001-test"], cwd=repo, check=True, capture_output=True)
    target.write_text("print(2)\n", encoding="utf-8")

    built = protocol.build_manifest(repo, feature, "main")
    assert built["requirements"] == ["FR-001"]
    assert built["changed_files"] == ["src/a.py"]
    assert built["required_context_files"] == ["specs/001-test/spec.md", "src/a.py"]
    assert len(built["review_context"]["snapshot_sha256"]) == 64
