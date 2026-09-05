from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "src" / "speckit_powerpack" / "assets" / "runtime" / "powerpack_review_protocol.py"
spec = importlib.util.spec_from_file_location("powerpack_review_protocol", MODULE_PATH)
assert spec and spec.loader
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


def valid_review(*, verdict: str = "APPROVED", findings=None, previous_findings=None):
    findings = [] if findings is None else findings
    previous_findings = [] if previous_findings is None else previous_findings
    fronts = []
    for name in protocol.FRONTS:
        status = "PASS"
        if verdict == "CHANGES_REQUIRED" and name == "SPEC_COMPLIANCE":
            status = "FINDINGS"
        if verdict == "BLOCKED" and name == "SPEC_COMPLIANCE":
            status = "BLOCKED"
        fronts.append({"name": name, "status": status, "evidence": ["proof"]})
    return {
        "schema_version": "2.0",
        "reviewer": "codex",
        "round": 1,
        "verdict": verdict,
        "summary": "summary",
        "review_context": {
            "spec_id": "spec-001",
            "base_ref": "origin/main",
            "base_sha": "a" * 40,
            "merge_base": "a" * 40,
            "head_sha": "b" * 40,
            "snapshot_sha256": "c" * 64,
        },
        "coverage": {
            "changed_files": ["src/a.py"],
            "inspected_files": ["src/a.py", "tests/test_a.py"],
            "tests_examined": ["tests/test_a.py"],
            "requirements": [{"id": "FR-001", "status": "PASS", "evidence": ["proof"]}],
            "baseline_scenarios": [{
                "scenario": "happy path",
                "base_behavior": "works",
                "head_behavior": "works",
                "result": "PRESERVED",
                "evidence": ["proof"],
            }],
            "previous_findings": previous_findings,
            "verification_limitations": [],
            "fronts": fronts,
        },
        "findings": findings,
    }


def finding(item_id="R001-001"):
    return {
        "id": item_id,
        "severity": "REQUIRED",
        "category": "CORRECTNESS",
        "title": "broken behavior",
        "file": "src/a.py",
        "line": 10,
        "evidence": "proof",
        "failure_scenario": "fails",
        "behavioral_impact": "wrong result",
        "required_change": "fix it",
        "acceptance_criteria": ["test proves fix"],
    }


def test_approved_review_contract_is_valid():
    assert protocol.validate_review(valid_review()) == []


def test_approved_rejects_uninspected_changed_file():
    review = valid_review()
    review["coverage"]["changed_files"].append("src/unseen.py")
    errors = protocol.validate_review(review)
    assert any("every changed file must be inspected" in error for error in errors)


def test_approved_rejects_findings():
    review = valid_review(findings=[finding()])
    errors = protocol.validate_review(review)
    assert "APPROVED requires findings: []" in errors


def test_previous_round_requires_exact_finding_ids_and_resolution():
    previous = valid_review(verdict="CHANGES_REQUIRED", findings=[finding("R001-001")])
    current = valid_review(previous_findings=[{"id": "R001-001", "status": "RESOLVED", "evidence": ["fixed"]}])
    assert protocol.validate_review(current, previous) == []

    current["coverage"]["previous_findings"] = []
    errors = protocol.validate_review(current, previous)
    assert any("exactly every finding id" in error for error in errors)


def test_changes_required_needs_finding_and_findings_front():
    review = valid_review(verdict="CHANGES_REQUIRED", findings=[finding()])
    assert protocol.validate_review(review) == []


def test_resolved_material_finding_reappearing_is_blocked():
    previous = valid_review(verdict="CHANGES_REQUIRED", findings=[finding("R001-001")])
    current = valid_review(
        verdict="CHANGES_REQUIRED",
        findings=[finding("R002-001")],
        previous_findings=[{"id": "R001-001", "status": "RESOLVED", "evidence": ["claimed fixed"]}],
    )
    errors = protocol.validate_review(current, previous)
    assert any(error.startswith(protocol.REPEATED_PREFIX) for error in errors)
    assert protocol.classify_errors(errors) == "BLOCKED_REPEATED_FINDING"


def test_not_resolved_finding_can_remain_without_repeated_resolution_block():
    previous = valid_review(verdict="CHANGES_REQUIRED", findings=[finding("R001-001")])
    current = valid_review(
        verdict="CHANGES_REQUIRED",
        findings=[finding("R002-001")],
        previous_findings=[{"id": "R001-001", "status": "NOT_RESOLVED", "evidence": ["still open"]}],
    )
    errors = protocol.validate_review(current, previous)
    assert not any(error.startswith(protocol.REPEATED_PREFIX) for error in errors)


def test_snapshot_identity_requires_full_hashes():
    review = valid_review()
    review["review_context"]["head_sha"] = "deadbeef"
    review["review_context"]["snapshot_sha256"] = "abcd"
    errors = protocol.validate_review(review)
    assert any("head_sha must be a full 40-character Git SHA" in error for error in errors)
    assert any("snapshot_sha256 must be a 64-character" in error for error in errors)
