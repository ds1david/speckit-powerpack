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
