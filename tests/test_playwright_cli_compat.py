from __future__ import annotations

from speckit_powerpack import desktop_browser_bridge as desktop
from speckit_powerpack import playwright_cli_compat as compat


def test_attach_places_global_session_option_before_command(monkeypatch):
    env = desktop.DesktopEnvironment("linux", "linux", False, "KDE", "Wayland")
    browser = desktop.BrowserCandidate(
        browser_id="chrome",
        label="Google Chrome",
        executable="/usr/bin/google-chrome",
        automation="channel-cdp",
        cdp_channel="chrome",
        inspect_url="chrome://inspect/#remote-debugging",
        host_scope="linux",
    )
    calls = []

    monkeypatch.setattr(desktop, "ensure_host_playwright_cli", lambda env: None)
    monkeypatch.setattr(compat.winbridge, "session_name_for", lambda profile: "speckit-powerpack-demo")
    monkeypatch.setattr(
        desktop,
        "_host_pwcli",
        lambda args, **kwargs: calls.append(args),
    )

    session = compat._attach_existing_browser(profile="demo", browser=browser, env=env)

    assert session == "speckit-powerpack-demo"
    assert calls == [["-s=speckit-powerpack-demo", "attach", "--cdp=chrome"]]
