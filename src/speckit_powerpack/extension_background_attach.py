from __future__ import annotations

import subprocess
import time

from . import browser_extension_transport as extension
from . import desktop_browser_bridge as desktop
from . import windows_argv_transport as wintransport
from . import windows_browser_bridge as winbridge


_ORIGINAL_ATTACH = extension._attach_existing_browser
_APPLIED = False


def _session_live(
    session: str,
    *,
    env: desktop.DesktopEnvironment,
    timeout: int = 20,
) -> bool:
    try:
        desktop._host_pwcli(
            [f"-s={session}", "tab-list"],
            env=env,
            timeout=timeout,
        )
        return True
    except desktop.DesktopBrowserBridgeError:
        return False


def _terminate_quietly(proc: subprocess.Popen[bytes]) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
    except OSError:
        pass


def _attach_existing_browser(
    *,
    profile: str,
    browser: desktop.BrowserCandidate,
    cdp_endpoint: str | None = None,
    env: desktop.DesktopEnvironment | None = None,
) -> str:
    env = env or desktop.detect_environment()

    if not (
        browser.automation == "extension-attach"
        and env.host_scope == "windows"
        and env.is_wsl
    ):
        return _ORIGINAL_ATTACH(
            profile=profile,
            browser=browser,
            cdp_endpoint=cdp_endpoint,
            env=env,
        )

    desktop.ensure_host_playwright_cli(env)
    session = winbridge.session_name_for(profile)

    # A previous interactive attempt may have established the Playwright daemon
    # even if the parent npx/PowerShell process never returned to the WSL caller.
    # Reuse only when the named session itself proves that it is responsive.
    if _session_live(session, env=env, timeout=12):
        return session

    channel = browser.cdp_channel or browser.browser_id
    extension_arg = "--extension" if channel == "chrome" else f"--extension={channel}"
    argv = [
        "npx.cmd",
        "--yes",
        winbridge.PLAYWRIGHT_CLI_PACKAGE,
        f"-s={session}",
        "attach",
        extension_arg,
    ]

    try:
        proc = wintransport.start_windows_cmd_argv(argv)
    except winbridge.WindowsBrowserBridgeError as exc:
        raise desktop.DesktopBrowserBridgeError(str(exc)) from exc

    print("Aguardando a Playwright Extension confirmar a sessão do navegador...")
    deadline = time.monotonic() + 120
    last_rc: int | None = None
    while time.monotonic() < deadline:
        if _session_live(session, env=env, timeout=12):
            return session

        last_rc = proc.poll()
        if last_rc is not None and last_rc != 0:
            # Give the daemon a short grace period: the launcher may exit after
            # spawning it, while the named session becomes reachable moments later.
            for _ in range(3):
                time.sleep(1)
                if _session_live(session, env=env, timeout=12):
                    return session
            raise desktop.DesktopBrowserBridgeError(
                f"Playwright Extension attach exited with code {last_rc} before session '{session}' became live. "
                "Keep the selected browser open, confirm the extension connection page, and retry."
            )
        time.sleep(2)

    _terminate_quietly(proc)
    raise desktop.DesktopBrowserBridgeError(
        f"Playwright Extension was authorized, but session '{session}' did not become responsive within 120 seconds. "
        "The PowerPack did not switch browser/backend. Retry the same reviewer after confirming the extension banner remains active."
    )


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    # The configure workflow calls the module-local function while validate,
    # Project binding and smoke-test call desktop.attach_existing_browser.
    # Keep both entry points on the same readiness-probed transport.
    extension._attach_existing_browser = _attach_existing_browser
    desktop.attach_existing_browser = _attach_existing_browser
