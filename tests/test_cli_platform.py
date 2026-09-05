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
