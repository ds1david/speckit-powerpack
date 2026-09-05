from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

MODULE_PATH = Path(__file__).parents[1] / "src" / "speckit_powerpack" / "assets" / "runtime" / "powerpack_runtime.py"
spec = importlib.util.spec_from_file_location("powerpack_runtime", MODULE_PATH)
rt = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(rt)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / ".specify").mkdir()
    feature = root / "specs" / "001-demo"
    feature.mkdir(parents=True)
    (feature / "spec.md").write_text("# Spec\n")
    (feature / "plan.md").write_text("# Plan\n")
    (feature / "tasks.md").write_text("# Tasks\n")
    (root / "README.md").write_text("hello\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")
    return root, feature


def test_checklist_predecessor_requires_receipt_not_artifact(tmp_path: Path):
    root, feature = repo(tmp_path)
    (feature / "checklists").mkdir()
    (feature / "checklists" / "requirements.md").write_text("- [ ] CHK001 quality\n")
    result = rt.evaluate_receipt(root, feature, "checklist", {"COMPLETED"}, require_current=False)
    assert result["ok"] is False
    assert result["reason"] == "MISSING_RECEIPT"


def test_receipts_are_isolated_by_spec(tmp_path: Path):
    root, feature = repo(tmp_path)
    other = root / "specs" / "002-other"
    other.mkdir()
    for name in ("spec.md", "plan.md", "tasks.md"):
        (other / name).write_text(name)
    data = rt.load_feature_state(root, feature)
    data["steps"]["implement"] = {"status": "COMPLETED"}
    rt.save_feature_state(root, feature, data)
    result = rt.evaluate_receipt(root, other, "implement", {"COMPLETED"}, require_current=False)
    assert result["ok"] is False


def test_implement_delta_ignores_preexisting_dirty_file(tmp_path: Path, monkeypatch):
    root, feature = repo(tmp_path)
    (root / "dirty.txt").write_text("before\n")
    monkeypatch.chdir(root)
    args = type("Args", (), {"feature_dir": str(feature)})()
    assert rt.cmd_implement_begin(args) == 0
    (feature / "tasks.md").write_text("# Tasks\nchanged\n")
    assert rt.cmd_implement_end(args) == 0
    changed = rt.latest_implement_files(root, feature)
    assert "specs/001-demo/tasks.md" in changed
    assert "dirty.txt" not in changed


def test_implement_delta_detects_second_change_to_dirty_file(tmp_path: Path, monkeypatch):
    root, feature = repo(tmp_path)
    path = root / "README.md"
    path.write_text("dirty-before\n")
    monkeypatch.chdir(root)
    args = type("Args", (), {"feature_dir": str(feature)})()
    rt.cmd_implement_begin(args)
    path.write_text("changed-during-implement\n")
    rt.cmd_implement_end(args)
    assert "README.md" in rt.latest_implement_files(root, feature)


def test_documentation_only_gate_is_not_applicable(tmp_path: Path):
    root, _ = repo(tmp_path)
    result = rt.gate_for_project(root, ["docs/guide.md", "README.md"])
    assert result["status"] == "NOT_APPLICABLE"


def test_maven_gate_is_detected(tmp_path: Path):
    root, _ = repo(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    result = rt.gate_for_project(root, ["src/main/java/App.java"])
    assert result["reason"] == "maven"
    assert result["command"][-2:] == ["-B", "verify"]


def test_gradle_gate_is_detected(tmp_path: Path):
    root, _ = repo(tmp_path)
    (root / "build.gradle").write_text("")
    result = rt.gate_for_project(root, ["src/main/java/App.java"])
    assert result["reason"] == "gradle"
    assert result["command"][-1] == "check"


def test_eclipse_without_cli_gate_blocks(tmp_path: Path):
    root, _ = repo(tmp_path)
    (root / ".project").write_text("<projectDescription/>")
    result = rt.gate_for_project(root, ["src/App.java"])
    assert result["status"] == "BLOCKED_CONFIGURATION"
    assert "eclipse" in result["reason"]


def test_claude_routes_to_one_external_codex():
    result = rt.review_route(Path("."), "claude")
    assert result["reviewer_mode"] == "external-codex"
    assert result["spawn_required"] is True
    assert result["reasoning_effort"] == "xhigh"
    assert result["sandbox"] == "read-only"


def test_codex_routes_to_current_session_without_recursion():
    result = rt.review_route(Path("."), "codex")
    assert result["reviewer_mode"] == "local-codex-session"
    assert result["spawn_required"] is False
    assert result["recursive_spawn_forbidden"] is True
    assert result["reasoning_effort"] == "xhigh"


def test_unknown_executor_blocks():
    assert rt.review_route(Path("."), "unknown")["status"] == "BLOCKED"


def test_finding_identity_is_stable():
    finding = {"title": "Null race", "file": "src/A.java", "line": 42}
    assert rt.finding_identity("codex", finding) == rt.finding_identity("codex", dict(finding))


def test_ingested_finding_can_be_selected_implemented_and_resolved(tmp_path: Path, monkeypatch):
    root, feature = repo(tmp_path)
    monkeypatch.chdir(root)
    state = rt.load_feature_state(root, feature)
    state["steps"]["implement"] = {"status": "COMPLETED"}
    rt.save_feature_state(root, feature, state)
    review = rt.load_review_state(root, feature)
    review["status"] = "READY_FOR_REVIEW"
    rt.save_review_state(root, feature, review)
    payload = root / "review.json"
    payload.write_text(json.dumps({"findings": [{"title": "Race", "severity": "high", "evidence": "A.java:10"}]}))
    ingest = type("Args", (), {"feature_dir": str(feature), "provider": "codex", "findings_json": str(payload)})()
    assert rt.cmd_review_ingest(ingest) == 0
    tasks = rt.current_review_tasks(feature)
    fid = next(iter(tasks))
    select = type("Args", (), {"feature_dir": str(feature), "all": False, "id": [fid]})()
    assert rt.cmd_review_select(select) == 0
    impl = type("Args", (), {"feature_dir": str(feature), "id": [fid], "evidence": "fixed A.java"})()
    assert rt.cmd_review_mark_implemented(impl) == 0
    resolve = type("Args", (), {"feature_dir": str(feature), "id": [fid], "evidence": "tests pass"})()
    assert rt.cmd_review_resolve(resolve) == 0
    assert rt.current_review_tasks(feature)[fid]["status"] == "RESOLVED"


def test_repeated_finding_is_deduplicated(tmp_path: Path, monkeypatch):
    root, feature = repo(tmp_path)
    monkeypatch.chdir(root)
    review = rt.load_review_state(root, feature)
    review["status"] = "READY_FOR_REVIEW"
    rt.save_review_state(root, feature, review)
    payload = root / "review.json"
    payload.write_text(json.dumps({"findings": [{"title": "Race", "file": "A.java", "line": 1}]}))
    args = type("Args", (), {"feature_dir": str(feature), "provider": "codex", "findings_json": str(payload)})()
    rt.cmd_review_ingest(args)
    rt.cmd_review_ingest(args)
    assert len(rt.current_review_tasks(feature)) == 1


def test_abort_removes_ephemeral_state_but_preserves_tasks(tmp_path: Path, monkeypatch):
    root, feature = repo(tmp_path)
    monkeypatch.chdir(root)
    review = rt.load_review_state(root, feature)
    review["status"] = "FINDINGS_PENDING"
    rt.save_review_state(root, feature, review)
    before = (feature / "tasks.md").read_text()
    args = type("Args", (), {"feature_dir": str(feature)})()
    assert rt.cmd_review_abort(args) == 0
    assert not rt.review_state_path(root, feature).exists()
    assert (feature / "tasks.md").read_text() == before


def test_limit_classifier_detects_usage_limit():
    result = rt.classify_limit("You've hit your usage limit. Resets at 08:00.")
    assert result["is_limit"] is True
    assert result["classification"] == "SESSION_OR_USAGE_LIMIT"


def test_non_limit_error_is_not_misclassified():
    assert rt.classify_limit("Compilation failed: symbol not found")["is_limit"] is False
