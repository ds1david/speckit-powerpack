from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Iterable


PLAYWRIGHT_CLI_PACKAGE = "@playwright/cli@latest"
WINDOWS_BROWSER_CHANNELS = {
    "edge": "msedge",
    "msedge": "msedge",
    "chrome": "chrome",
}
WINDOWS_INSPECT_URLS = {
    "msedge": "edge://inspect/#remote-debugging",
    "chrome": "chrome://inspect/#remote-debugging",
}
WINDOWS_BROWSER_EXES = {
    "msedge": "msedge.exe",
    "chrome": "chrome.exe",
}


class WindowsBrowserBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowsBrowserSession:
    profile: str
    account_label: str
    browser_channel: str
    session_name: str
    granted_at: str


@dataclass(frozen=True)
class WindowsProjectCandidate:
    name: str
    url: str


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").casefold()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def normalize_browser_channel(value: str) -> str:
    channel = WINDOWS_BROWSER_CHANNELS.get((value or "").strip().casefold())
    if not channel:
        raise WindowsBrowserBridgeError("Browser must be 'edge'/'msedge' or 'chrome'.")
    return channel


def session_name_for(profile: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", profile).strip("-") or "default"
    return f"speckit-powerpack-{safe}"


def _run(argv: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise WindowsBrowserBridgeError(f"Required command is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowsBrowserBridgeError(f"Command timed out: {argv[0]}") from exc


def _windows_cmd(args: Iterable[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    if not is_wsl():
        raise WindowsBrowserBridgeError("Windows browser-context mode is supported from WSL only.")
    payload = subprocess.list2cmdline(list(args))
    workspace = r"%TEMP%\speckit-powerpack-playwright"
    command = f'if not exist "{workspace}" mkdir "{workspace}" & cd /d "{workspace}" & {payload}'
    return _run(["cmd.exe", "/d", "/s", "/c", command], timeout=timeout)


def _powershell(script: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def windows_node_version() -> str | None:
    proc = _windows_cmd(["node", "--version"], timeout=30)
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr).strip() or None


def windows_node_compatible() -> bool:
    value = windows_node_version()
    if not value:
        return False
    match = re.search(r"(\d+)", value)
    return bool(match and int(match.group(1)) >= 20)


def ensure_windows_playwright_cli() -> None:
    if not windows_node_compatible():
        raise WindowsBrowserBridgeError(
            "Windows browser-context mode requires Node.js 20+ installed on Windows and visible from WSL. "
            "Install/update Node.js on Windows, then retry."
        )
    proc = _windows_cmd(["npx.cmd", "--yes", PLAYWRIGHT_CLI_PACKAGE, "--help"], timeout=180)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown npx/@playwright/cli failure").strip()
        raise WindowsBrowserBridgeError("Could not prepare Playwright CLI on Windows: " + detail)


def open_remote_debugging_settings(browser_channel: str) -> None:
    channel = normalize_browser_channel(browser_channel)
    exe = WINDOWS_BROWSER_EXES[channel]
    url = WINDOWS_INSPECT_URLS[channel]
    script = f"Start-Process '{exe}' '{url}'"
    proc = _powershell(script)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "browser could not be opened").strip()
        raise WindowsBrowserBridgeError(f"Could not open {channel} remote-debugging settings: {detail}")


def _pwcli(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    proc = _windows_cmd(["npx.cmd", "--yes", PLAYWRIGHT_CLI_PACKAGE, *args], timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Playwright CLI command failed").strip()
        raise WindowsBrowserBridgeError(detail)
    return proc


def attach_existing_browser(*, profile: str, browser_channel: str) -> str:
    ensure_windows_playwright_cli()
    channel = normalize_browser_channel(browser_channel)
    session = session_name_for(profile)
    try:
        _pwcli(["attach", f"--cdp={channel}", f"-s={session}"], timeout=120)
    except WindowsBrowserBridgeError as exc:
        inspect_url = WINDOWS_INSPECT_URLS[channel]
        raise WindowsBrowserBridgeError(
            f"Could not attach to the running Windows {channel} context. Open {inspect_url} in that browser, "
            "enable 'Allow remote debugging for this browser instance', keep the browser running, and retry. "
            f"Underlying error: {exc}"
        ) from exc
    return session


def _eval_json(session: str, expression: str) -> dict:
    marker = "POWERPACK_JSON:"
    wrapped = f"() => '{marker}' + JSON.stringify(({expression})())"
    proc = _pwcli([f"-s={session}", "eval", wrapped], timeout=120)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(re.escape(marker) + r"(\{.*\}|\[.*\])", text)
    if not match:
        raise WindowsBrowserBridgeError("Playwright CLI returned no machine-readable browser evidence.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise WindowsBrowserBridgeError("Could not parse browser validation evidence.") from exc
    if not isinstance(value, dict):
        raise WindowsBrowserBridgeError("Expected object browser evidence.")
    return value


def _eval_json_array(session: str, expression: str) -> list[dict]:
    marker = "POWERPACK_JSON:"
    wrapped = f"() => '{marker}' + JSON.stringify(({expression})())"
    proc = _pwcli([f"-s={session}", "eval", wrapped], timeout=120)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = re.search(re.escape(marker) + r"(\[.*\])", text)
    if not match:
        raise WindowsBrowserBridgeError("Playwright CLI returned no project-list evidence.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise WindowsBrowserBridgeError("Could not parse project-list evidence.") from exc
    return [item for item in value if isinstance(item, dict)]


def open_chatgpt_tab(session: str) -> None:
    _pwcli([f"-s={session}", "tab-new", "https://chatgpt.com/"], timeout=120)


def chatgpt_login_evidence(session: str) -> dict:
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
    return _eval_json(session, expression)


def validate_existing_windows_chatgpt_session(*, profile: str, browser_channel: str, open_tab: bool = True) -> dict:
    session = attach_existing_browser(profile=profile, browser_channel=browser_channel)
    if open_tab:
        open_chatgpt_tab(session)
    evidence = chatgpt_login_evidence(session)
    if not evidence.get("authenticated"):
        raise WindowsBrowserBridgeError(
            "The attached Windows browser is reachable, but the active ChatGPT tab is not authenticated. "
            "Log in to the intended account in that Windows browser, wait for the normal ChatGPT composer, then retry validation."
        )
    return {**evidence, "session_name": session, "browser_channel": normalize_browser_channel(browser_channel)}


def discover_projects(*, profile: str, browser_channel: str) -> list[WindowsProjectCandidate]:
    session = attach_existing_browser(profile=profile, browser_channel=browser_channel)
    open_chatgpt_tab(session)
    print("ChatGPT opened in your existing Windows browser context.")
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
    items = _eval_json_array(session, expression)
    return [WindowsProjectCandidate(str(i.get("name") or "Project"), str(i.get("url") or "")) for i in items if i.get("url")]


def capture_project_from_url(*, profile: str, browser_channel: str, url: str, prompt: str | None = None) -> WindowsProjectCandidate:
    session = attach_existing_browser(profile=profile, browser_channel=browser_channel)
    _pwcli([f"-s={session}", "tab-new", url], timeout=120)
    if prompt:
        print(prompt)
        input()
    expression = r"""() => ({href: location.href, title: document.title})"""
    evidence = _eval_json(session, expression)
    href = str(evidence.get("href") or "")
    if not re.match(r"^https://(www\.)?chatgpt\.com/.+/project(?:[/?#].*)?$", href):
        raise WindowsBrowserBridgeError(
            "The current Windows browser tab is not a ChatGPT Project. Finish the invite/navigation and retry."
        )
    normalized = href.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    name = str(evidence.get("title") or "").strip() or normalized.split("/")[-2]
    return WindowsProjectCandidate(name=name, url=normalized)
