from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "src" / "speckit_powerpack" / "assets" / "runtime" / "powerpack_full_cycle.py"
spec = importlib.util.spec_from_file_location("powerpack_full_cycle", MODULE_PATH)
assert spec and spec.loader
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)


def setup_project(tmp_path: Path, *, max_convergence=2, max_review=2):
    powerpack = tmp_path / ".specify" / "powerpack"
    powerpack.mkdir(parents=True)
    feature = tmp_path / "specs" / "001-demo"
    feature.mkdir(parents=True)
    (tmp_path / ".specify" / "feature.json").write_text(json.dumps({"feature_directory": "specs/001-demo"}), encoding="utf-8")
    (powerpack / "full-cycle.json").write_text(json.dumps({
        "mode": "auto",
        "phases": {phase: True for phase in cycle.PHASE_ORDER},
        "limits": {"max_convergence_rounds": max_convergence, "max_review_rounds": max_review},
        "behavior": {"same_spec_only": True, "stop_on_blocked": True, "allow_debt_escape_hatch": False},
    }), encoding="utf-8")
    return feature


def read_state(tmp_path: Path):
    path = next((tmp_path / ".specify" / "powerpack" / "runtime" / "full-cycle").glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def advance_to_implement(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    assert cycle.main(["start"]) == 0
    for phase in ["clarify", "plan", "checklist", "checklist_converge", "tasks", "analyze"]:
        assert cycle.main(["advance", "--phase", phase, "--outcome", "completed"]) == 0
    assert read_state(tmp_path)["current_phase"] == "implement"


def test_full_cycle_returns_to_converge_after_fix_and_counts_attempts(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    advance_to_implement(monkeypatch, tmp_path)
    cycle.main(["advance", "--phase", "implement", "--outcome", "completed"])
    assert cycle.main(["advance", "--phase", "converge", "--outcome", "needs-implementation"]) == 0
    state = read_state(tmp_path)
    assert state["current_phase"] == "implement"
    assert state["return_after_implement"] == "converge"
    assert state["convergence_round"] == 1

    cycle.main(["advance", "--phase", "implement", "--outcome", "completed"])
    assert cycle.main(["advance", "--phase", "converge", "--outcome", "converged"]) == 0
    state = read_state(tmp_path)
    assert state["current_phase"] == "implement_review"
    assert state["convergence_round"] == 2


def test_review_findings_return_to_implementation_then_review_and_count_final_approval(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    advance_to_implement(monkeypatch, tmp_path)
    cycle.main(["advance", "--phase", "implement", "--outcome", "completed"])
    cycle.main(["advance", "--phase", "converge", "--outcome", "converged"])

    assert cycle.main(["advance", "--phase", "implement_review", "--outcome", "findings"]) == 0
    assert read_state(tmp_path)["review_round"] == 1
    cycle.main(["advance", "--phase", "implement", "--outcome", "completed"])
    assert read_state(tmp_path)["current_phase"] == "implement_review"
    cycle.main(["advance", "--phase", "implement_review", "--outcome", "approved"])
    state = read_state(tmp_path)
    assert state["status"] == "DONE"
    assert state["review_round"] == 2


def test_skipped_checklist_also_skips_checklist_converge(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    cycle.main(["start"])
    cycle.main(["advance", "--phase", "clarify", "--outcome", "completed"])
    cycle.main(["advance", "--phase", "plan", "--outcome", "completed"])
    assert cycle.main(["advance", "--phase", "checklist", "--outcome", "skipped"]) == 0
    state = read_state(tmp_path)
    assert state["current_phase"] == "tasks"
    assert any(item["phase"] == "checklist_converge" and item["outcome"] == "skipped" for item in state["history"])


def test_blocked_cycle_requires_explicit_resume_before_advance(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    cycle.main(["start"])
    assert cycle.main(["advance", "--phase", "clarify", "--outcome", "blocked", "--evidence", "need decision"]) == 10
    assert cycle.main(["advance", "--phase", "clarify", "--outcome", "completed"]) == 9
    assert cycle.main(["resume", "--unblock"]) == 0
    assert cycle.main(["advance", "--phase", "clarify", "--outcome", "completed"]) == 0


def test_non_weakenable_cycle_invariants_block_start(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    cfg_path = tmp_path / ".specify" / "powerpack" / "full-cycle.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["behavior"]["allow_debt_escape_hatch"] = True
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert cycle.main(["start"]) == 8
