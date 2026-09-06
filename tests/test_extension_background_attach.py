from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import desktop_browser_bridge as desktop
from speckit_powerpack import extension_background_attach as attach
from speckit_powerpack import windows_argv_transport as wintransport
from speckit_powerpack import windows_browser_bridge as winbridge


def _env() -> desktop.DesktopEnvironment:
    return desktop.DesktopEnvironment("linux", "windows", True, "Windows", "WSLg/Wayland")


def _edge() -> desktop.BrowserCandidate:
    return desktop.BrowserCandidate(
        "msedge", "Microsoft Edge", "msedge.exe", "extension-attach", "msedge"
    )


class _RunningProcess:
    def poll(self):
        return None

    def terminate(self):
        pass


def test_reuses_already_live_extension_session(monkeypatch):
    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env=None: None)
    monkeypatch.setattr(attach, "_session_live", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        wintransport,
        "start_windows_cmd_argv",
        lambda args: (_ for _ in ()).throw(AssertionError("attach should not be started")),
    )

    session = attach._attach_existing_browser(
        profile="chatgpt-review",
        browser=_edge(),
        env=_env(),
    )

    assert session == "speckit-powerpack-chatgpt-review"


def test_starts_extension_attach_in_background_and_returns_when_session_is_live(monkeypatch):
    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env=None: None)
    probes = iter([False, False, True])
    monkeypatch.setattr(attach, "_session_live", lambda *args, **kwargs: next(probes))
    monkeypatch.setattr(attach.time, "sleep", lambda seconds: None)
    commands = []

    def fake_start(args):
        commands.append(list(args))
        return _RunningProcess()

    monkeypatch.setattr(wintransport, "start_windows_cmd_argv", fake_start)

    session = attach._attach_existing_browser(
        profile="chatgpt-review",
        browser=_edge(),
        env=_env(),
    )

    assert session == "speckit-powerpack-chatgpt-review"
    assert commands == [[
        "npx.cmd",
        "--yes",
        winbridge.PLAYWRIGHT_CLI_PACKAGE,
        "-s=speckit-powerpack-chatgpt-review",
        "attach",
        "--extension=msedge",
    ]]


def test_native_or_non_extension_paths_keep_original_attach(monkeypatch):
    expected = "original-session"
    monkeypatch.setattr(attach, "_ORIGINAL_ATTACH", lambda **kwargs: expected)
    browser = desktop.BrowserCandidate(
        "brave", "Brave", "brave.exe", "endpoint-cdp", None
    )

    result = attach._attach_existing_browser(
        profile="review",
        browser=browser,
        cdp_endpoint="http://127.0.0.1:9222",
        env=_env(),
    )

    assert result == expected
