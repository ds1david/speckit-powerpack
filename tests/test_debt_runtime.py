from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "src" / "speckit_powerpack" / "assets" / "runtime" / "powerpack_debt.py"
spec = importlib.util.spec_from_file_location("powerpack_debt", MODULE_PATH)
assert spec and spec.loader
debt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(debt)


def setup_project(tmp_path: Path):
    powerpack = tmp_path / ".specify" / "powerpack"
    powerpack.mkdir(parents=True)
    template = powerpack / "technical-debt-template.md"
    template.write_text("# Technical Debt Backlog\n\n## Items\n", encoding="utf-8")
    (powerpack / "technical-debt.json").write_text(json.dumps({
        "storage_format": "markdown-v1",
        "backlog_path": "docs/technical-debt.md",
        "template_path": ".specify/powerpack/technical-debt-template.md",
        "id_prefix": "TD",
        "priorities": ["P1", "P2", "P3"],
        "creation_policy": {
            "forbid_active_review_findings": True,
            "forbid_active_convergence_gaps": True,
            "forbid_blockers": True,
        },
    }), encoding="utf-8")


def create_args(priority="P2", origin_kind="manual"):
    return [
        "create",
        "--title", "Upgrade brittle adapter",
        "--owner", "platform",
        "--description", "Adapter has avoidable coupling",
        "--origin", "manual architecture review",
        "--origin-kind", origin_kind,
        "--impact", "slower safe changes",
        "--priority", priority,
        "--resolution-criteria", "adapter dependency is isolated and tests prove behavior",
        "--deferral-rationale", "non-blocking and outside current SPEC",
        "--evidence", "src/adapter.py",
    ]


def test_create_blocks_p0_and_active_review(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert debt.main(create_args(priority="P0")) == 4
    assert debt.main(create_args(origin_kind="review")) == 4
    assert not (tmp_path / "docs" / "technical-debt.md").exists()


def test_create_deduplicate_start_and_close_require_evidence(monkeypatch, tmp_path: Path):
    setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert debt.main(create_args()) == 0
    assert debt.main(create_args()) == 3

    backlog = tmp_path / "docs" / "technical-debt.md"
    text = backlog.read_text(encoding="utf-8")
    assert "### TD-001 — Upgrade brittle adapter" in text
    assert "**Status:** OPEN" in text

    assert debt.main(["start", "TD-001", "--spec", "specs/010-adapter", "--evidence", "approved work selection"]) == 0
    assert "**Status:** IN_PROGRESS" in backlog.read_text(encoding="utf-8")

    assert debt.main(["close", "TD-001", "--evidence", "tests/test_adapter.py passes"]) == 7
    assert debt.main([
        "close", "TD-001",
        "--criteria-satisfied",
        "--evidence", "dependency isolated; regression tests pass",
        "--gate-status", "PASSED",
    ]) == 0
    final = backlog.read_text(encoding="utf-8")
    assert "**Status:** RESOLVED" in final
    assert "**Readiness:** RESOLVED" in final
