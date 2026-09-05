from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "src" / "speckit_powerpack" / "assets"
PRESET = ASSETS / "presets" / "powerpack-core"


def test_implement_review_has_single_canonical_asset():
    commands = PRESET / "commands"
    assert (commands / "speckit.implement-review.md").is_file()
    assert not (commands / "speckit.implement-review-v2.md").exists()
    preset = (PRESET / "preset.yml").read_text(encoding="utf-8")
    assert 'file: "commands/speckit.implement-review.md"' in preset
    assert "implement-review-v2" not in preset


def test_debt_and_full_cycle_commands_are_packaged():
    commands = PRESET / "commands"
    expected = [
        "speckit.full-cycle.md",
        "speckit.debt-create.md",
        "speckit.debt-list.md",
        "speckit.debt-consult.md",
        "speckit.debt-start.md",
        "speckit.debt-close.md",
    ]
    for filename in expected:
        assert (commands / filename).is_file(), filename


def test_review_defaults_require_platform_scoped_web_profiles():
    review = json.loads((ASSETS / "config" / "default-review.json").read_text(encoding="utf-8"))
    assert review["schema_version"] == 2
    assert review["chatgpt_web"]["profile_scope"] == "platform"
    assert review["deep_review"]["schema_version"] == "2.0"
    assert review["deep_review"]["validate_previous_findings"] is True


def test_technical_debt_policy_forbids_review_escape_hatch():
    debt = json.loads((ASSETS / "config" / "default-technical-debt.json").read_text(encoding="utf-8"))
    policy = debt["creation_policy"]
    assert policy["forbid_active_review_findings"] is True
    assert policy["forbid_active_convergence_gaps"] is True
    assert policy["forbid_blockers"] is True
