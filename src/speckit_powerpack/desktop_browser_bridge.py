from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from . import windows_browser_bridge as winbridge


PLAYWRIGHT_CLI_PACKAGE = "@playwright/cli@latest"


class DesktopBrowserBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesktopEnvironment:
    runtime_os: str
    host_scope: str
    is_wsl: bool
    desktop: str | None
    display_server: str | None


@dataclass(frozen=True)
class BrowserCandidate:
    browser_id: str
    label: str
    executable: str | None
    automation: str
    cdp_channel: str | None = None
    inspect_url: str | None = None
    host_scope: str = "linux"

    @property
    def automatable_existing_context(self) -> bool:
        return self.automation in {"channel-cdp", "endpoint-cdp"}


WINDOWS_APP_PATHS = {
    "msedge.exe": [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    ],
    "chrome.exe": [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    ],
    "firefox.exe": [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
    ],
    "opera.exe": [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
    ],
    "brave.exe": [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe",
    ],
}


def detect_environment() -> DesktopEnvironment:
    if winbridge.is_wsl():
        display = "WSLg/Wayland" if os.environ.get("WAYLAND_DISPLAY") else "WSLg/X11" if os.environ.get("DISPLAY") else None
        return DesktopEnvironment("linux", "windows", True, "Windows", display)
    if sys.platform.startswith("linux"):
        desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION")
        display = "Wayland" if os.environ.get("WAYLAND_DISPLAY") else "X11" if os.environ.get("DISPLAY") else None
        return DesktopEnvironment("linux", "linux", False, desktop, display)
    if sys.platform == "darwin":
        return DesktopEnvironment("macos", "macos", False, "macOS", None)
    if sys.platform.startswith("win"):
        return DesktopEnvironment("windows", "windows", False, "Windows", None)
    return DesktopEnvironment(sys.platform, sys.platform, False, None, None)


def _run(argv: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DesktopBrowserBridgeError(f"Required command is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DesktopBrowserBridgeError(f"Command timed out: {argv[0]}") from exc


def _powershell(script: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    executable = "powershell.exe" if shutil.which("powershell.exe") else "powershell"
    return _run([executable, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def _windows_find_executable(executable: str) -> str | None:
    registry_paths = WINDOWS_APP_PATHS.get(executable, [])
    registry_literal = ",".join(f"'{path}'" for path in registry_paths)
    script = rf"""
$c = Get-Command '{executable}' -ErrorAction SilentlyContinue
if ($c -and $c.Source) {{ Write-Output $c.Source; exit 0 }}
$paths = @({registry_literal})
foreach ($p in $paths) {{
  try {{
    $key = Get-Item -Path $p -ErrorAction Stop
    $value = $key.GetValue('')
    if ($value -and (Test-Path $value)) {{ Write-Output $value; exit 0 }}
  }} catch {{}}
}}
$common = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${{env:ProgramFiles(x86)}}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${{env:ProgramFiles(x86)}}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Mozilla Firefox\firefox.exe",
  "${{env:ProgramFiles(x86)}}\Mozilla Firefox\firefox.exe",
  "$env:LOCALAPPDATA\Programs\Opera\opera.exe",
  "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe",
  "$env:ProgramFiles\BraveSoftware\Brave-Browser\Application\brave.exe"
)
foreach ($candidate in $common) {{
  if ($candidate -and (Split-Path $candidate -Leaf) -ieq '{executable}' -and (Test-Path $candidate)) {{
    Write-Output $candidate
    exit 0
  }}
}}
exit 1
"""
    try:
        proc = _powershell(script, timeout=30)
    except DesktopBrowserBridgeError:
        return None
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or "").strip().splitlines()
    return lines[0].strip() if lines else None


def _mac_app_exists(name: str) -> bool:
    return Path("/Applications", f"{name}.app").exists() or Path.home().joinpath("Applications", f"{name}.app").exists()


def detect_browsers(env: DesktopEnvironment | None = None) -> list[BrowserCandidate]:
    env = env or detect_environment()
    values: list[BrowserCandidate] = []

    if env.host_scope == "windows":
        checks = [
            ("msedge", "Microsoft Edge", "msedge.exe", "channel-cdp", "msedge", "edge://inspect/#remote-debugging"),
            ("chrome", "Google Chrome", "chrome.exe", "channel-cdp", "chrome", "chrome://inspect/#remote-debugging"),
            ("opera", "Opera", "opera.exe", "endpoint-cdp", None, None),
            ("brave", "Brave", "brave.exe", "endpoint-cdp", None, None),
            ("firefox", "Mozilla Firefox", "firefox.exe", "manual-only", None, None),
        ]
        for browser_id, label, exe_name, automation, channel, inspect in checks:
            executable = _windows_find_executable(exe_name)
            if executable:
                values.append(BrowserCandidate(browser_id, label, executable, automation, channel, inspect, "windows"))
        return values

    if env.host_scope == "linux":
        checks = [
            ("msedge", "Microsoft Edge", ["microsoft-edge", "microsoft-edge-stable"], "channel-cdp", "msedge", "edge://inspect/#remote-debugging"),
            ("chrome", "Google Chrome", ["google-chrome", "google-chrome-stable"], "channel-cdp", "chrome", "chrome://inspect/#remote-debugging"),
            ("chromium", "Chromium", ["chromium", "chromium-browser"], "endpoint-cdp", None, None),
            ("opera", "Opera", ["opera"], "endpoint-cdp", None, None),
            ("brave", "Brave", ["brave-browser", "brave"], "endpoint-cdp", None, None),
            ("firefox", "Mozilla Firefox", ["firefox"], "manual-only", None, None),
        ]
        for browser_id, label, names, automation, channel, inspect in checks:
            executable = next((shutil.which(name) for name in names if shutil.which(name)), None)
            if executable:
                values.append(BrowserCandidate(browser_id, label, executable, automation, channel, inspect, "linux"))
        return values

    if env.host_scope == "macos":
        checks = [
            ("chrome", "Google Chrome", "Google Chrome", "channel-cdp", "chrome", "chrome://inspect/#remote-debugging"),
            ("msedge", "Microsoft Edge", "Microsoft Edge", "channel-cdp", "msedge", "edge://inspect/#remote-debugging"),
            ("opera", "Opera", "Opera", "endpoint-cdp", None, None),
            ("brave", "Brave", "Brave Browser", "endpoint-cdp", None, None),
            ("firefox", "Mozilla Firefox", "Firefox", "manual-only", None, None),
        ]
        for browser_id, label, app, automation, channel, inspect in checks:
            if _mac_app_exists(app):
                values.append(BrowserCandidate(browser_id, label, app, automation, channel, inspect, "macos"))
        return values

    return values


def browser_by_id(browser_id: str, candidates: list[BrowserCandidate] | None = None) -> BrowserCandidate | None:
    for candidate in candidates or detect_browsers():
        if candidate.browser_id == browser_id:
            return candidate
    return None


def open_url(url: str, *, browser: BrowserCandidate | None = None, env: DesktopEnvironment | None = None) -> None:
    env = env or detect_environment()
    if env.host_scope == "windows":
        if browser and browser.executable:
            exe = browser.executable.replace("'", "''")
            target = url.replace("'", "''")
            script = f"Start-Process -FilePath '{exe}' -ArgumentList @('{target}')"
        else:
            target = url.replace("'", "''")
            script = f"Start-Process '{target}'"
        proc = _powershell(script, timeout=30)
        if proc.returncode != 0:
            raise DesktopBrowserBridgeError((proc.stderr or proc.stdout or "Could not open Windows browser").strip())
        return

    if env.host_scope == "linux":
        if browser and browser.executable:
            try:
                subprocess.Popen([browser.executable, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                raise DesktopBrowserBridgeError(f"Could not open {browser.label}: {exc}") from exc
            return
        opener = shutil.which("xdg-open") or shutil.which("gio") or shutil.which("kde-open5") or shutil.which("kde-open")
        if not opener:
            raise DesktopBrowserBridgeError("No desktop URL opener found (xdg-open/gio/kde-open).")
        argv = [opener, "open", url] if Path(opener).name == "gio" else [opener, url]
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise DesktopBrowserBridgeError(f"Could not open desktop URL: {exc}") from exc
        return

    if env.host_scope == "macos":
        argv = ["open"]
        if browser and browser.executable:
            argv += ["-a", browser.executable]
        argv.append(url)
        proc = _run(argv, timeout=30)
        if proc.returncode != 0:
            raise DesktopBrowserBridgeError((proc.stderr or proc.stdout or "Could not open macOS browser").strip())
        return

    raise DesktopBrowserBridgeError(f"Unsupported desktop host scope: {env.host_scope}")


def _node_command(env: DesktopEnvironment) -> tuple[str, str]:
    if env.host_scope == "windows" and not env.is_wsl:
        return (shutil.which("node.exe") or shutil.which("node") or "node.exe", shutil.which("npx.cmd") or "npx.cmd")
    return (shutil.which("node") or "node", shutil.which("npx") or "npx")


def _local_node_compatible(env: DesktopEnvironment) -> bool:
    node, npx = _node_command(env)
    if not shutil.which(node) and not Path(node).exists():
        return False
    if not shutil.which(npx) and not Path(npx).exists():
        return False
    try:
        proc = _run([node, "--version"], timeout=15)
    except DesktopBrowserBridgeError:
        return False
    match = re.search(r"(\d+)", proc.stdout or proc.stderr or "")
    return bool(proc.returncode == 0 and match and int(match.group(1)) >= 20)


def ensure_host_playwright_cli(env: DesktopEnvironment | None = None) -> None:
    env = env or detect_environment()
    if env.host_scope == "windows" and env.is_wsl:
        try:
            winbridge.ensure_windows_playwright_cli()
        except winbridge.WindowsBrowserBridgeError as exc:
            raise DesktopBrowserBridgeError(str(exc)) from exc
        return
    if not _local_node_compatible(env):
        raise DesktopBrowserBridgeError(
            f"{env.host_scope} browser-context mode requires Node.js 20+ and npx in the browser host environment."
        )
    _, npx = _node_command(env)
    proc = _run([npx, "--yes", PLAYWRIGHT_CLI_PACKAGE, "--help"], timeout=180)
    if proc.returncode != 0:
        raise DesktopBrowserBridgeError((proc.stderr or proc.stdout or "Could not prepare Playwright CLI").strip())


def _host_pwcli(args: list[str], *, env: DesktopEnvironment | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = env or detect_environment()
    if env.host_scope == "windows" and env.is_wsl:
        try:
            return winbridge._pwcli(args, timeout=timeout)
        except winbridge.WindowsBrowserBridgeError as exc:
            raise DesktopBrowserBridgeError(str(exc)) from exc
    ensure_host_playwright_cli(env)
    _, npx = _node_command(env)
    proc = _run([npx, "--yes", PLAYWRIGHT_CLI_PACKAGE, *args], timeout=timeout)
    if proc.returncode != 0:
        raise DesktopBrowserBridgeError((proc.stderr or proc.stdout or "Playwright CLI command failed").strip())
    return proc


def open_remote_debugging_settings(browser: BrowserCandidate, *, env: DesktopEnvironment | None = None) -> None:
    if browser.automation != "channel-cdp" or not browser.inspect_url:
        return
    open_url(browser.inspect_url, browser=browser, env=env)


def attach_existing_browser(
    *,
    profile: str,
    browser: BrowserCandidate,
    cdp_endpoint: str | None = None,
    env: DesktopEnvironment | None = None,
) -> str:
    env = env or detect_environment()
    ensure_host_playwright_cli(env)
    session = winbridge.session_name_for(profile)
    if browser.automation == "manual-only":
        raise DesktopBrowserBridgeError(
            f"{browser.label} can be used to open/login manually, but Playwright cannot attach to its existing branded Firefox context. "
            "Choose Chrome/Edge or another Chromium browser exposing a CDP endpoint for automated Web review."
        )
    if browser.automation == "channel-cdp":
        target = browser.cdp_channel
    elif browser.automation == "endpoint-cdp":
        target = cdp_endpoint
        if not target:
            raise DesktopBrowserBridgeError(
                f"{browser.label} requires a Chromium CDP endpoint (for example http://127.0.0.1:9222)."
            )
    else:
        raise DesktopBrowserBridgeError(f"Unsupported automation mode: {browser.automation}")
    try:
        _host_pwcli(["attach", f"--cdp={target}", f"-s={session}"], env=env, timeout=120)
    except DesktopBrowserBridgeError as exc:
        if browser.automation == "channel-cdp":
            raise DesktopBrowserBridgeError(
                f"Could not attach to {browser.label}. Open {browser.inspect_url}, enable 'Allow remote debugging for this browser instance', "
                f"keep the browser running and approve any browser confirmation dialog, then retry. Underlying error: {exc}"
            ) from exc
        raise
    return session


def open_chatgpt_tab(session: str, *, env: DesktopEnvironment | None = None) -> None:
    _host_pwcli([f"-s={session}", "tab-new", "https://chatgpt.com/"], env=env, timeout=120)


def _eval_json(session: str, expression: str, *, env: DesktopEnvironment | None = None) -> dict:
    marker = "POWERPACK_JSON:"
    wrapped = f"() => '{marker}' + JSON.stringify(({expression})())"
    proc = _host_pwcli([f"-s={session}", "eval", wrapped], env=env, timeout=120)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(re.escape(marker) + r"(\{.*\})", text)
    if not match:
        raise DesktopBrowserBridgeError("Playwright CLI returned no machine-readable browser evidence.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DesktopBrowserBridgeError("Could not parse browser validation evidence.") from exc
    if not isinstance(value, dict):
        raise DesktopBrowserBridgeError("Expected object browser evidence.")
    return value


def _eval_json_array(session: str, expression: str, *, env: DesktopEnvironment | None = None) -> list[dict]:
    marker = "POWERPACK_JSON:"
    wrapped = f"() => '{marker}' + JSON.stringify(({expression})())"
    proc = _host_pwcli([f"-s={session}", "eval", wrapped], env=env, timeout=120)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(re.escape(marker) + r"(\[.*\])", text)
    if not match:
        raise DesktopBrowserBridgeError("Playwright CLI returned no project-list evidence.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DesktopBrowserBridgeError("Could not parse project-list evidence.") from exc
    return [item for item in value if isinstance(item, dict)]


def chatgpt_login_evidence(session: str, *, env: DesktopEnvironment | None = None) -> dict:
    expression = r"""() => {
      const path = (location.pathname || '').toLowerCase();
      const loginRoute = path.includes('/auth') || path.includes('/login') || path.includes('/signin');
      const loginLink = !!document.querySelector('a[href*="/auth/login"], a[href*="/login"], button[data-testid*="login"]');
      const composer = !!document.querySelector('textarea, [contenteditable="true"]');
      return {
        href: location.href,
        title: document.title,
        loginRoute,
        loginLink,
        composer,
        authenticated: location.hostname.endsWith('chatgpt.com') && !loginRoute && !loginLink && composer
      };
    }"""
    return _eval_json(session, expression, env=env)


def validate_existing_chatgpt_session(
    *,
    profile: str,
    browser: BrowserCandidate,
    cdp_endpoint: str | None = None,
    open_tab: bool = True,
    env: DesktopEnvironment | None = None,
) -> dict:
    env = env or detect_environment()
    session = attach_existing_browser(profile=profile, browser=browser, cdp_endpoint=cdp_endpoint, env=env)
    if open_tab:
        open_chatgpt_tab(session, env=env)
    evidence = chatgpt_login_evidence(session, env=env)
    if not evidence.get("authenticated"):
        raise DesktopBrowserBridgeError(
            "The selected desktop browser is reachable, but ChatGPT is not authenticated in that automation context. "
            "Log in to the intended account in that browser, wait for the normal ChatGPT composer, then retry."
        )
    return {
        **evidence,
        "session_name": session,
        "browser_id": browser.browser_id,
        "browser_label": browser.label,
        "automation": browser.automation,
        "host_scope": env.host_scope,
    }


def discover_projects(
    *,
    profile: str,
    browser: BrowserCandidate,
    cdp_endpoint: str | None = None,
    env: DesktopEnvironment | None = None,
) -> list[dict]:
    env = env or detect_environment()
    session = attach_existing_browser(profile=profile, browser=browser, cdp_endpoint=cdp_endpoint, env=env)
    open_chatgpt_tab(session, env=env)
    print(f"ChatGPT opened in {browser.label} ({env.host_scope}).")
    print("Expand/load the Projects list if necessary, then press Enter here to scan visible Project links.")
    input()
    expression = r"""() => {
      const values = new Map();
      for (const a of document.querySelectorAll('a[href]')) {
        try {
          const u = new URL(a.href, location.href);
          if (!u.hostname.endsWith('chatgpt.com')) continue;
          if (!u.pathname.replace(/\/$/, '').endsWith('/project')) continue;
          const url = u.origin + u.pathname.replace(/\/$/, '');
          const name = (a.innerText || a.textContent || '').trim() || u.pathname.split('/').filter(Boolean).slice(-2)[0];
          values.set(url, {name, url});
        } catch (_) {}
      }
      return Array.from(values.values());
    }"""
    return _eval_json_array(session, expression, env=env)


def capture_project_from_url(
    *,
    profile: str,
    browser: BrowserCandidate,
    url: str,
    cdp_endpoint: str | None = None,
    prompt: str | None = None,
    env: DesktopEnvironment | None = None,
) -> dict:
    env = env or detect_environment()
    session = attach_existing_browser(profile=profile, browser=browser, cdp_endpoint=cdp_endpoint, env=env)
    _host_pwcli([f"-s={session}", "tab-new", url], env=env, timeout=120)
    if prompt:
        print(prompt)
        input()
    evidence = _eval_json(session, r"""() => ({href: location.href, title: document.title})""", env=env)
    href = str(evidence.get("href") or "")
    if not re.match(r"^https://(www\.)?chatgpt\.com/.+/project(?:[/?#].*)?$", href):
        raise DesktopBrowserBridgeError("The current browser tab is not a ChatGPT Project.")
    normalized = href.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    name = str(evidence.get("title") or "").strip() or normalized.split("/")[-2]
    return {"name": name, "url": normalized}
