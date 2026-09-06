from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import browser_extension_transport as transport
from speckit_powerpack import desktop_browser_bridge as desktop
from speckit_powerpack import windows_browser_bridge as winbridge


def _env() -> desktop.DesktopEnvironment:
    return desktop.DesktopEnvironment("linux", "windows", True, "Windows", "WSLg/Wayland")


def test_detect_browsers_promotes_edge_and_chrome_to_extension(monkeypatch):
    monkeypatch.setattr(
        transport,
        "_ORIGINAL_DETECT_BROWSERS",
        lambda env=None: [
            desktop.BrowserCandidate("msedge", "Microsoft Edge", "edge.exe", "channel-cdp", "msedge"),
            desktop.BrowserCandidate("chrome", "Google Chrome", "chrome.exe", "channel-cdp", "chrome"),
            desktop.BrowserCandidate("firefox", "Firefox", "firefox.exe", "manual-only"),
        ],
    )

    values = transport._detect_browsers_extension_first(_env())
    assert values[0].automation == "extension-attach"
    assert values[0].inspect_url == transport.PLAYWRIGHT_EXTENSION_URL
    assert values[1].automation == "extension-attach"
    assert values[2].automation == "manual-only"


def test_extension_attach_uses_explicit_edge_channel(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env=None: None)
    monkeypatch.setattr(
        desktop,
        "_host_pwcli",
        lambda args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "ok", ""),
    )
    browser = desktop.BrowserCandidate(
        "msedge", "Microsoft Edge", "edge.exe", "extension-attach", "msedge"
    )

    session = transport._attach_existing_browser(profile="ds1david", browser=browser, env=_env())

    assert session == "speckit-powerpack-ds1david"
    assert calls == [["-s=speckit-powerpack-ds1david", "attach", "--extension=msedge"]]


def test_extension_attach_uses_default_extension_flag_for_stable_chrome(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env=None: None)
    monkeypatch.setattr(
        desktop,
        "_host_pwcli",
        lambda args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "ok", ""),
    )
    browser = desktop.BrowserCandidate(
        "chrome", "Google Chrome", "chrome.exe", "extension-attach", "chrome"
    )

    transport._attach_existing_browser(profile="webflow", browser=browser, env=_env())

    assert calls == [["-s=speckit-powerpack-webflow", "attach", "--extension"]]


def test_windows_cmd_starts_from_windows_local_cwd_and_temp_workspace(monkeypatch, tmp_path):
    captured = {}
    system32 = tmp_path / "Windows" / "System32"
    system32.mkdir(parents=True)

    monkeypatch.setattr(winbridge, "is_wsl", lambda: True)
    monkeypatch.setattr(transport, "Path", lambda value: system32 if value == "/mnt/c/Windows/System32" else Path(value))

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(argv, 0, b"v24.19.0\r\n", b"")

    monkeypatch.setattr(transport.subprocess, "run", fake_run)

    proc = transport._windows_cmd_local_cwd(["node", "--version"], timeout=30)

    assert proc.returncode == 0
    assert proc.stdout.strip() == "v24.19.0"
    assert captured["cwd"] == str(system32)
    command = captured["argv"][-1]
    assert 'cd /d "%TEMP%"' in command
    assert 'cd /d "speckit-powerpack-playwright"' in command
    assert "node --version" in command
