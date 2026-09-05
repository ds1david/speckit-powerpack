from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from speckit_powerpack import cli


def args(tmp_path: Path, **overrides):
    values = {
        "path": str(tmp_path),
        "check": False,
        "yes": False,
        "force": False,
        "project_only": False,
        "reset_config": False,
        "repository": None,
        "ref": None,
        "integration": None,
        "bootstrap_speckit": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_current_update_is_noop_without_force(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "project_update_config", lambda path: {})
    monkeypatch.setattr(cli, "check_update_safe", lambda cfg: {
        "status": "CURRENT",
        "repository": "https://github.com/ds1david/speckit-powerpack.git",
        "ref": "main",
        "installed_commit": "a" * 40,
        "remote_commit": "a" * 40,
    })
    called = []
    monkeypatch.setattr(cli, "apply_self_update", lambda repository, ref: called.append((repository, ref)))
    cli.cmd_update(args(tmp_path))
    assert called == []


def test_project_only_force_reset_requires_explicit_yes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "project_update_config", lambda path: {})
    monkeypatch.setattr(cli, "check_update_safe", lambda cfg: {"status": "CHECK_FAILED", "error": "offline"})
    try:
        cli.cmd_update(args(tmp_path, project_only=True, force=True, reset_config=True, yes=False))
    except cli.PowerPackError as exc:
        assert "--reset-config requires explicit --yes" in str(exc)
    else:
        raise AssertionError("reset-config must require explicit yes")


def test_project_only_force_refreshes_managed_assets_and_can_reset_config(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(cli, "project_update_config", lambda path: {})
    monkeypatch.setattr(cli, "check_update_safe", lambda cfg: {"status": "CHECK_FAILED", "error": "offline"})
    monkeypatch.setattr(cli, "project_integration", lambda path: "claude")
    monkeypatch.setattr(
        cli,
        "install_powerpack",
        lambda path, integration, initialize, bootstrap, overwrite_config=False: calls.append({
            "path": path,
            "integration": integration,
            "initialize": initialize,
            "bootstrap": bootstrap,
            "overwrite_config": overwrite_config,
        }),
    )
    cli.cmd_update(args(tmp_path, project_only=True, force=True, reset_config=True, yes=True))
    assert calls == [{
        "path": str(tmp_path.resolve()),
        "integration": "claude",
        "initialize": False,
        "bootstrap": False,
        "overwrite_config": True,
    }]


def test_force_self_update_does_not_require_project_git_mutation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "project_update_config", lambda path: {})
    monkeypatch.setattr(cli, "check_update_safe", lambda cfg: {
        "status": "UNKNOWN_INSTALLED_SOURCE",
        "repository": "https://github.com/ds1david/speckit-powerpack.git",
        "ref": "main",
    })
    monkeypatch.setattr(cli, "apply_self_update", lambda repository, ref: {
        "status": "UPDATED",
        "repository": repository,
        "ref": ref,
        "argv": ["uv", "tool", "install"],
    })
    cli.cmd_update(args(tmp_path, force=True, yes=True))
    # No .specify directory exists, so the command performs only the CLI
    # reinstall path and has no reason to invoke any repository Git mutation.
    assert not (tmp_path / ".specify").exists()


def test_installer_auto_update_decline_continues_current_cli(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "project_update_config", lambda path: {"enabled": True, "auto_check_on_install": True})
    monkeypatch.setattr(cli, "check_update_safe", lambda cfg: {
        "status": "UPDATE_AVAILABLE",
        "repository": "https://github.com/ds1david/speckit-powerpack.git",
        "ref": "main",
        "installed_commit": "a" * 40,
        "remote_commit": "b" * 40,
    })
    monkeypatch.setattr(cli, "confirm_update", lambda prompt, assume_yes=False: False)
    called = []
    monkeypatch.setattr(cli, "apply_self_update", lambda repository, ref: called.append((repository, ref)))
    cli.maybe_auto_update("install", Namespace(path=str(tmp_path), no_update_check=False, yes_update=False))
    assert called == []
