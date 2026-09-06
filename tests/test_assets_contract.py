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
    assert (ASSETS / "runtime" / "powerpack_debt.py").is_file()
    assert (ASSETS / "runtime" / "powerpack_full_cycle.py").is_file()


def test_update_command_and_policy_are_packaged():
    extension = ASSETS / "extensions" / "powerpack-tools"
    manifest = (extension / "extension.yml").read_text(encoding="utf-8")
    assert (extension / "commands" / "update.md").is_file()
    assert 'name: "speckit.powerpack-tools.update"' in manifest
    update = json.loads((ASSETS / "config" / "default-update.json").read_text(encoding="utf-8"))
    assert update["auto_check_on_install"] is True
    assert update["confirmation_required"] is True
    assert update["force"]["destructive_git_operations"] is False


def test_review_defaults_require_platform_scoped_web_accounts_and_projects():
    review = json.loads((ASSETS / "config" / "default-review.json").read_text(encoding="utf-8"))
    assert review["schema_version"] == 3
    web = review["chatgpt_web"]
    assert web["required"] is True
    assert web["enabled"] is True
    assert web["profile_scope"] == "platform"
    assert web["headless"] is False
    assert web["authorization"] is None
    assert web["account_label"] is None
    assert web["project_name"] is None
    assert review["deep_review"]["schema_version"] == "2.0"
    assert review["deep_review"]["validate_previous_findings"] is True
    assert review["deep_review"]["full_snapshot_each_round"] is True
    assert review["deep_review"]["adversarial_verdict_challenge"] is True


def test_playwright_is_core_dependency_and_web_review_cli_is_entrypoint():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dependencies = ["playwright>=1.55,<2"]' in pyproject
    assert 'speckit-powerpack = "speckit_powerpack.cli_web_review:main"' in pyproject
    assert (ROOT / "src" / "speckit_powerpack" / "cli_browser_accounts.py").is_file()
    assert (ROOT / "src" / "speckit_powerpack" / "cli_web_review.py").is_file()
    assert (ROOT / "src" / "speckit_powerpack" / "desktop_browser_bridge.py").is_file()
    assert (ROOT / "src" / "speckit_powerpack" / "web_review_smoke.py").is_file()


def test_deep_review_protocol_and_validator_are_packaged():
    assert (ASSETS / "review" / "deep-review-protocol.md").is_file()
    assert (ASSETS / "runtime" / "powerpack_review_protocol.py").is_file()


def test_technical_debt_policy_forbids_review_escape_hatch():
    debt = json.loads((ASSETS / "config" / "default-technical-debt.json").read_text(encoding="utf-8"))
    policy = debt["creation_policy"]
    assert policy["forbid_active_review_findings"] is True
    assert policy["forbid_active_convergence_gaps"] is True
    assert policy["forbid_blockers"] is True
    assert policy["powerpack_policy_is_minimum_floor"] is True
    assert debt["storage_format"] == "markdown-v1"
    assert debt["template_path"] == ".specify/powerpack/technical-debt-template.md"
    assert (ASSETS / "policies" / "technical-debt.md").is_file()
    assert (ASSETS / "templates" / "technical-debt-backlog.md").is_file()


def test_full_cycle_defaults_preserve_safety_invariants():
    config = json.loads((ASSETS / "config" / "default-full-cycle.json").read_text(encoding="utf-8"))
    assert config["schema_version"] == 2
    assert config["behavior"]["same_spec_only"] is True
    assert config["behavior"]["stop_on_blocked"] is True
    assert config["behavior"]["allow_debt_escape_hatch"] is False
    assert config["behavior"]["explicit_initial_implement_required"] is True
    assert config["behavior"]["implement_review_owns_convergence"] is True
    assert config["phases"]["implement"] is True
    assert config["phases"]["implement_review"] is True
    assert "converge" not in config["phases"]


def test_implement_review_contract_starts_from_explicit_implement_then_converges():
    text = (PRESET / "commands" / "speckit.implement-review.md").read_text(encoding="utf-8")
    assert "speckit-implement\n  -> speckit-implement-review" in text
    assert "MUST NOT perform the initial implementation" in text
    assert "first productive action after readiness and predecessor gates is `speckit-converge`" in text
    assert "BLOCKED_BUDGET" in text
    assert "gpt-5.6-terra/high" in text
    assert "gpt-5.6-sol/xhigh/read-only" in text
    assert "NEVER launch another `codex` CLI recursively" in text


def test_implement_review_requires_explicit_browser_account_identity_and_dual_approval():
    text = (PRESET / "commands" / "speckit.implement-review.md").read_text(encoding="utf-8")
    assert "speckit-powerpack doctor --strict-review" in text
    assert "desktop-browser-context" in text
    assert "isolated-playwright" in text
    assert "account_label" in text
    assert "No automatic fallback" in text
    assert "try another browser/account" in text
    assert "same Project may have multiple account bindings" in text
    assert "mandatory ChatGPT Project Web review" in text
    assert "Both final approvals must refer to the same final snapshot" in text
    assert "Codex-only completion path" in text


def test_model_routing_covers_workflows_without_changing_review_profile():
    routing = json.loads((ASSETS / "config" / "default-model-routing.json").read_text(encoding="utf-8"))
    assert routing["schema_version"] == 2
    assert routing["stages"]["full-cycle"] == "orchestration"
    assert routing["stages"]["implement-review"] == "orchestration"
    assert routing["stages"]["converge"] == "semantic_gate"
    assert routing["stages"]["debt-list"] == "economical"
    assert routing["stages"]["debt-consult"] == "economical"
    assert routing["stages"]["powerpack-update"] == "economical"
    assert routing["integrations"]["claude"]["economical"] == "haiku"
    assert routing["integrations"]["codex"]["economical"] == "gpt-5.6-luna"
    assert routing["integrations"]["codex"]["coding"] == "gpt-5.6-terra"
    assert routing["integrations"]["codex"]["orchestration"] == "gpt-5.6-terra"
    assert routing["integrations"]["codex"]["semantic_gate"] == "gpt-5.6-sol"
    assert routing["integrations"]["codex"]["reviewer"] == "gpt-5.6-sol"
    assert routing["effort"]["codex"]["coding"] == "high"
    assert routing["effort"]["codex"]["reviewer"] == "xhigh"
    assert routing["reviewer_contract"]["codex"] == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "sandbox": "read-only",
    }
