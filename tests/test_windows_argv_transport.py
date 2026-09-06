from __future__ import annotations

import base64
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import windows_argv_transport as transport
from speckit_powerpack import windows_browser_bridge as winbridge


def test_windows_transport_uses_encoded_powershell_and_preserves_complex_eval(monkeypatch, tmp_path):
    captured = {}
    local = tmp_path / "System32"
    local.mkdir()

    monkeypatch.setattr(winbridge, "is_wsl", lambda: True)
    monkeypatch.setattr(transport, "_windows_local_cwd", lambda: str(local))

    expression = "() => ({href: location.href, title: document.title, text: 'a & b (c)'})"

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(argv, 0, b"ok\r\n", b"")

    monkeypatch.setattr(transport.subprocess, "run", fake_run)

    result = transport.windows_cmd_argv(
        ["npx.cmd", "--yes", "@playwright/cli@latest", "-s=review", "eval", expression]
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
    assert captured["cwd"] == str(local)
    argv = captured["argv"]
    assert argv[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand"]

    script = base64.b64decode(argv[4]).decode("utf-16-le")
    assert "ConvertFrom-Json" in script
    assert "& $exe @rest" in script
    assert "Set-Location -LiteralPath $workspace" in script
    # The JS expression is intentionally not interpolated directly into the
    # PowerShell source; it is encapsulated inside Base64 JSON argv.
    assert expression not in script


def test_apply_replaces_windows_command_boundary(monkeypatch):
    original = winbridge._windows_cmd
    monkeypatch.setattr(transport, "_APPLIED", False)
    try:
        transport.apply()
        assert winbridge._windows_cmd is transport.windows_cmd_argv
    finally:
        winbridge._windows_cmd = original
