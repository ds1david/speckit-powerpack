from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from speckit_powerpack import cli


def test_install_support_materializes_customizable_project_contract(tmp_path: Path):
    (tmp_path / ".specify").mkdir()
    cli.install_support(tmp_path, "claude")

    base = tmp_path / ".specify" / "powerpack"
    assert (base / "bin" / "powerpack.py").is_file()
    assert (base / "bin" / "capabilities.py").is_file()
    assert (base / "bin" / "review_protocol.py").is_file()
    assert (base / "bin" / "debt.py").is_file()
    assert (base / "bin" / "full_cycle.py").is_file()
    assert (base / "deep-review-protocol.md").is_file()
    assert (base / "technical-debt-policy.md").is_file()
    assert (base / "technical-debt-template.md").is_file()

    review = json.loads((base / "review.json").read_text(encoding="utf-8"))
    assert review["chatgpt_web"]["profile_scope"] == "platform"

    debt = json.loads((base / "technical-debt.json").read_text(encoding="utf-8"))
    assert debt["template_path"] == ".specify/powerpack/technical-debt-template.md"

    full_cycle = json.loads((base / "full-cycle.json").read_text(encoding="utf-8"))
    assert full_cycle["behavior"]["same_spec_only"] is True
    assert full_cycle["behavior"]["allow_debt_escape_hatch"] is False

    update = json.loads((base / "update.json").read_text(encoding="utf-8"))
    assert update["auto_check_on_install"] is True
    assert update["confirmation_required"] is True
    assert update["force"]["destructive_git_operations"] is False

    routing = json.loads((base / "model-routing.json").read_text(encoding="utf-8"))
    assert routing["active_integration"] == "claude"
    assert routing["stages"]["debt-list"] == "economical"


def test_install_support_preserves_project_config_until_explicit_reset(tmp_path: Path):
    (tmp_path / ".specify").mkdir()
    cli.install_support(tmp_path, "claude")
    base = tmp_path / ".specify" / "powerpack"
    review_path = base / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["custom_marker"] = "keep-me"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    cli.install_support(tmp_path, "codex")
    assert json.loads(review_path.read_text(encoding="utf-8"))["custom_marker"] == "keep-me"

    cli.install_support(tmp_path, "codex", overwrite_config=True)
    assert "custom_marker" not in json.loads(review_path.read_text(encoding="utf-8"))
