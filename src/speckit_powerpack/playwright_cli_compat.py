from __future__ import annotations

from . import desktop_browser_bridge as desktop
from . import windows_browser_bridge as winbridge


def _attach_existing_browser(
    *,
    profile: str,
    browser: desktop.BrowserCandidate,
    cdp_endpoint: str | None = None,
    env: desktop.DesktopEnvironment | None = None,
) -> str:
    """Attach using the documented CLI ordering: -s=<name> attach --cdp=<target>."""
    env = env or desktop.detect_environment()
    desktop.ensure_host_playwright_cli(env)
    session = winbridge.session_name_for(profile)

    if browser.automation == "manual-only":
        raise desktop.DesktopBrowserBridgeError(
            f"{browser.label} can be used for manual login, but its existing branded session "
            "is not attach-compatible with the Chromium/CDP Web-review backend."
        )
    if browser.automation == "channel-cdp":
        target = browser.cdp_channel
        if not target:
            raise desktop.DesktopBrowserBridgeError(f"{browser.label} has no CDP channel configured.")
    elif browser.automation == "endpoint-cdp":
        target = cdp_endpoint
        if not target:
            raise desktop.DesktopBrowserBridgeError(
                f"{browser.label} requires a Chromium CDP endpoint, for example http://127.0.0.1:9222."
            )
    else:
        raise desktop.DesktopBrowserBridgeError(f"Unsupported browser automation mode: {browser.automation}")

    try:
        desktop._host_pwcli(
            [f"-s={session}", "attach", f"--cdp={target}"],
            env=env,
            timeout=120,
        )
    except desktop.DesktopBrowserBridgeError as exc:
        if browser.automation == "channel-cdp":
            raise desktop.DesktopBrowserBridgeError(
                f"Could not attach to {browser.label}. Enable remote debugging in {browser.inspect_url}, "
                f"keep that browser instance running, then retry. Underlying error: {exc}"
            ) from exc
        raise
    return session


def apply() -> None:
    # validate_existing_chatgpt_session/discover/capture look up this module global at
    # call time, so replacing the function here fixes all desktop-browser flows.
    desktop.attach_existing_browser = _attach_existing_browser
