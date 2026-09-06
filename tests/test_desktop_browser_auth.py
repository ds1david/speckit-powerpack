from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import cli_desktop_auth as auth
from speckit_powerpack import desktop_browser_bridge as desktop


def test_parser_keeps_interactive_configure_and_parameterless_reconfigure():
    parser = auth.build_parser()
    configure = parser.parse_args(["review", "auth", "configure"])
    assert configure.func is auth.cmd_auth_configure

    reconfigure = parser.parse_args(["review", "auth", "reconfigure"])
    assert reconfigure.func is auth.cmd_auth_reconfigure
    assert reconfigure.profile is None


def test_wsl_environment_routes_browser_host_to_windows(monkeypatch):
    monkeypatch.setattr(desktop.winbridge, "is_wsl", lambda: True)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    env = desktop.detect_environment()
    assert env.runtime_os == "linux"
    assert env.host_scope == "windows"
    assert env.is_wsl is True
    assert env.display_server == "WSLg/Wayland"


def test_native_linux_environment_keeps_linux_desktop(monkeypatch):
    monkeypatch.setattr(desktop.winbridge, "is_wsl", lambda: False)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    env = desktop.detect_environment()
    assert env.host_scope == "linux"
    assert env.desktop == "KDE"
    assert env.display_server == "Wayland"


def test_browser_capabilities_distinguish_login_only_firefox_from_chromium_attach():
    chrome = desktop.BrowserCandidate("chrome", "Google Chrome", "/chrome", "channel-cdp", "chrome")
    opera = desktop.BrowserCandidate("opera", "Opera", "/opera", "endpoint-cdp")
    firefox = desktop.BrowserCandidate("firefox", "Mozilla Firefox", "/firefox", "manual-only")
    assert chrome.automatable_existing_context is True
    assert opera.automatable_existing_context is True
    assert firefox.automatable_existing_context is False


def test_desktop_account_authorization_does_not_require_powerpack_browser_profile_dir():
    data = {
        "accounts": {
            "linux": {
                "ds1david": {
                    "source": auth.DESKTOP_ACCOUNT_AUTH_SOURCE,
                    "backend": auth.DESKTOP_ACCOUNT_BACKEND,
                    "automation_browser_id": "msedge",
                    "remote_debugging_consent": True,
                }
            }
        }
    }
    assert auth._account_authorized(data, "linux", "ds1david") is True


def test_old_windows_backend_is_read_as_generic_desktop_backend():
    record = {
        "source": auth.previous.WINDOWS_ACCOUNT_AUTH_SOURCE,
        "backend": auth.previous.WINDOWS_ACCOUNT_BACKEND,
        "browser_channel": "msedge",
        "remote_debugging_consent": True,
    }
    assert auth._account_backend(record) == auth.DESKTOP_ACCOUNT_BACKEND


def test_firefox_attach_fails_with_actionable_message(monkeypatch):
    browser = desktop.BrowserCandidate("firefox", "Mozilla Firefox", "/firefox", "manual-only")
    env = desktop.DesktopEnvironment("linux", "linux", False, "GNOME", "Wayland")
    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env=None: None)
    try:
        desktop.attach_existing_browser(profile="review", browser=browser, env=env)
    except desktop.DesktopBrowserBridgeError as exc:
        text = str(exc)
        assert "Firefox" in text
        assert "Chromium" in text
    else:
        raise AssertionError("Firefox existing-context attach must fail closed")


def test_endpoint_browser_requires_explicit_cdp_endpoint(monkeypatch):
    browser = desktop.BrowserCandidate("opera", "Opera", "/opera", "endpoint-cdp")
    env = desktop.DesktopEnvironment("linux", "linux", False, "KDE", "Wayland")
    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env=None: None)
    try:
        desktop.attach_existing_browser(profile="review", browser=browser, env=env)
    except desktop.DesktopBrowserBridgeError as exc:
        assert "CDP endpoint" in str(exc)
    else:
        raise AssertionError("custom Chromium browser without endpoint must fail closed")
