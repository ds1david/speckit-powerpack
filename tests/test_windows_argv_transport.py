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
    assert "Get-Command $exe" in script
    assert "& $resolved @rest" in script
    assert "Set-Location -LiteralPath $workspace" in script
    # The JS expression is intentionally not interpolated directly into the
    # PowerShell source; it is encapsulated inside Base64 JSON argv.
    assert expression not in script


def test_playwright_preflight_uses_real_npx_path_instead_of_standalone_node_gate(monkeypatch):
    calls = []

    def fake_windows_cmd(args, *, timeout=180):
        calls.append((list(args), timeout))
        return subprocess.CompletedProcess(args, 0, "Usage: playwright-cli", "")

    monkeypatch.setattr(transport, "windows_cmd_argv", fake_windows_cmd)
    transport.ensure_windows_playwright_cli()

    assert calls == [
        (["npx.cmd", "--yes", winbridge.PLAYWRIGHT_CLI_PACKAGE, "--help"], 180)
    ]


def test_playwright_preflight_reports_observed_node_and_real_npx_error(monkeypatch):
    def fake_windows_cmd(args, *, timeout=180):
        if list(args)[:1] == ["node"]:
            return subprocess.CompletedProcess(args, 0, "v24.19.0\r\n", "")
        return subprocess.CompletedProcess(args, 1, "", "npx failed")

    monkeypatch.setattr(transport, "windows_cmd_argv", fake_windows_cmd)

    try:
        transport.ensure_windows_playwright_cli()
        raise AssertionError("expected WindowsBrowserBridgeError")
    except winbridge.WindowsBrowserBridgeError as exc:
        message = str(exc)
        assert "v24.19.0" in message
        assert "npx failed" in message


def test_apply_replaces_entire_windows_browser_tool_boundary(monkeypatch):
    original_cmd = winbridge._windows_cmd
    original_node_version = winbridge.windows_node_version
    original_node_compatible = winbridge.windows_node_compatible
    original_ensure = winbridge.ensure_windows_playwright_cli
    monkeypatch.setattr(transport, "_APPLIED", False)
    try:
        transport.apply()
        assert winbridge._windows_cmd is transport.windows_cmd_argv
        assert winbridge.windows_node_version is transport.windows_node_version
        assert winbridge.windows_node_compatible is transport.windows_node_compatible
        assert winbridge.ensure_windows_playwright_cli is transport.ensure_windows_playwright_cli
    finally:
        winbridge._windows_cmd = original_cmd
        winbridge.windows_node_version = original_node_version
        winbridge.windows_node_compatible = original_node_compatible
        winbridge.ensure_windows_playwright_cli = original_ensure
