from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from speckit_powerpack import cli


def test_config_paths_are_native(tmp_path: Path):
    assert cli.default_config_base(system="Windows", env={"APPDATA": str(tmp_path / "app")}, home=tmp_path) == tmp_path / "app"
    assert cli.default_config_base(system="Windows", env={}, home=tmp_path) == tmp_path / "AppData" / "Roaming"
    assert cli.default_config_base(system="Darwin", env={}, home=tmp_path) == tmp_path / "Library" / "Application Support"
    assert cli.default_config_base(system="Linux", env={}, home=tmp_path) == tmp_path / ".config"


def test_xdg_override_is_platform_independent(tmp_path: Path):
    xdg = tmp_path / "xdg"
    for system in ("Windows", "Darwin", "Linux"):
        assert cli.default_config_base(system=system, env={"XDG_CONFIG_HOME": str(xdg)}, home=tmp_path) == xdg


def test_browser_profiles_are_platform_scoped(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli, "global_root", lambda: tmp_path)
    windows = cli.profile_dir("review", system="Windows")
    linux = cli.profile_dir("review", system="Linux")
    macos = cli.profile_dir("review", system="Darwin")
    assert windows == tmp_path / "browser-profiles" / "windows" / "review"
    assert linux == tmp_path / "browser-profiles" / "linux" / "review"
    assert macos == tmp_path / "browser-profiles" / "macos" / "review"
    assert len({windows, linux, macos}) == 3


def test_legacy_global_profile_migrates_only_to_current_platform():
    data = {
        "active_profile": "legacy",
        "projects": {"default": {"url": "https://chatgpt.com/g/g-p-test/project", "profile": "legacy"}},
    }
    migrated = cli._migrate_global_config(data, current_platform="linux")
    assert migrated["active_profiles"] == {"linux": "legacy"}
    assert migrated["projects"]["default"]["bindings"]["linux"]["profile"] == "legacy"
    assert "windows" not in migrated["projects"]["default"]["bindings"]


def test_version_parser_and_minimum_contract():
    assert cli.parse_version("0.14.3") == (0, 14, 3)
    assert cli.parse_version("Spec Kit CLI: 1.0.4") == (1, 0, 4)
    assert cli.spec_kit_compatible("0.14.3") is False
    assert cli.spec_kit_compatible("1.0.0") is True
    assert cli.spec_kit_compatible("1.0.4") is True


def test_spec_kit_bootstrap_uses_pinned_git_package_and_force(monkeypatch):
    calls = []
    specify_checks = iter([None, "/usr/bin/specify"])

    def fake_which(name):
        if name == "specify":
            return next(specify_checks)
        if name == "uv":
            return "/usr/bin/uv"
        return None

    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli, "specify_version", lambda binary: "1.0.4")
    monkeypatch.setattr(cli, "run", lambda argv, **kwargs: calls.append(argv))
    assert cli.ensure_specify(True) == "/usr/bin/specify"
    assert calls == [[
        "/usr/bin/uv",
        "tool",
        "install",
        "--force",
        f"git+{cli.SPECKIT_REPO}@{cli.SPECKIT_TESTED_TAG}",
    ]]


def test_incompatible_existing_spec_kit_is_upgraded_when_bootstrap_enabled(monkeypatch):
    calls = []
    versions = iter(["0.14.3", "1.0.4"])

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else "/usr/bin/specify")
    monkeypatch.setattr(cli, "specify_version", lambda binary: next(versions))
    monkeypatch.setattr(cli, "run", lambda argv, **kwargs: calls.append(argv))

    assert cli.ensure_specify(True) == "/usr/bin/specify"
    assert calls == [[
        "/usr/bin/uv",
        "tool",
        "install",
        "--force",
        f"git+{cli.SPECKIT_REPO}@{cli.SPECKIT_TESTED_TAG}",
    ]]


def test_incompatible_existing_spec_kit_blocks_without_bootstrap(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/specify" if name == "specify" else None)
    monkeypatch.setattr(cli, "specify_version", lambda binary: "0.14.3")
    try:
        cli.ensure_specify(False)
    except cli.PowerPackError as exc:
        assert "--bootstrap-speckit" in str(exc)
        assert ">= 1.0.0" in str(exc)
    else:
        raise AssertionError("incompatible Spec Kit should block")


def test_mandatory_web_review_policy_migrates_existing_config_without_faking_consent(tmp_path: Path):
    path = tmp_path / "review.json"
    path.write_text('{"chatgpt_web":{"enabled":false,"project_alias":"existing"}}', encoding="utf-8")
    cli.enforce_mandatory_web_review(path)
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert data["chatgpt_web"]["required"] is True
    assert data["chatgpt_web"]["enabled"] is True
    assert data["chatgpt_web"]["project_alias"] == "existing"
    assert data["chatgpt_web"]["authorization"] is None
