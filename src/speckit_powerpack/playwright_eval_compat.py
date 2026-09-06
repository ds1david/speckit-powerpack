from __future__ import annotations

import json
import re
from typing import Any

from . import desktop_browser_bridge as desktop


_APPLIED = False


def _parse_raw_json(stdout: str, stderr: str, *, expected: type) -> Any:
    payload = (stdout or "").strip()
    if not payload:
        detail = (stderr or "").strip()
        raise desktop.DesktopBrowserBridgeError(
            "Playwright CLI returned no machine-readable browser evidence"
            + (f": {detail}" if detail else ".")
        )

    value: Any
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        # --raw should be only the return value. Keep one narrow compatibility
        # path for CLI versions that emit a short status line around the value.
        pattern = r"(\{.*\})" if expected is dict else r"(\[.*\])"
        match = re.search(pattern, payload, flags=re.DOTALL)
        if not match:
            raise desktop.DesktopBrowserBridgeError(
                "Could not parse machine-readable browser evidence returned by Playwright CLI."
            ) from exc
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as nested:
            raise desktop.DesktopBrowserBridgeError(
                "Could not parse browser evidence JSON payload."
            ) from nested

    # Some CLI versions stringify a string return value once more. Decode a
    # second time only when the result itself visibly contains JSON.
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass

    if not isinstance(value, expected):
        raise desktop.DesktopBrowserBridgeError(
            f"Expected {expected.__name__} browser evidence from Playwright CLI, got {type(value).__name__}."
        )
    return value


def _raw_eval_json(
    session: str,
    expression: str,
    *,
    expected: type,
    env: desktop.DesktopEnvironment | None = None,
) -> Any:
    proc = desktop._host_pwcli(
        [f"-s={session}", "--raw", "eval", expression],
        env=env,
        timeout=120,
    )
    return _parse_raw_json(proc.stdout or "", proc.stderr or "", expected=expected)


def chatgpt_login_evidence(
    session: str,
    *,
    env: desktop.DesktopEnvironment | None = None,
) -> dict:
    # Keep this as one direct eval function. Do not wrap/invoke another arrow
    # function: extension sessions already execute the supplied function.
    expression = """() => {
      const path = (location.pathname || '').toLowerCase();
      const loginRoute = path.includes('/auth') || path.includes('/login') || path.includes('/signin');
      const composer = !!document.querySelector('textarea,[contenteditable=true]');
      return JSON.stringify({
        href: location.href,
        title: document.title,
        loginRoute,
        composer,
        authenticated: location.hostname.endsWith('chatgpt.com') && !loginRoute && composer
      });
    }"""
    return _raw_eval_json(session, expression, expected=dict, env=env)


def discover_projects(
    *,
    profile: str,
    browser: desktop.BrowserCandidate,
    cdp_endpoint: str | None = None,
    env: desktop.DesktopEnvironment | None = None,
) -> list[dict]:
    env = env or desktop.detect_environment()
    session = desktop.attach_existing_browser(
        profile=profile,
        browser=browser,
        cdp_endpoint=cdp_endpoint,
        env=env,
    )
    desktop.open_chatgpt_tab(session, env=env)
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
      return JSON.stringify(Array.from(values.values()));
    }"""
    return _raw_eval_json(session, expression, expected=list, env=env)


def capture_project_from_url(
    *,
    profile: str,
    browser: desktop.BrowserCandidate,
    url: str,
    cdp_endpoint: str | None = None,
    prompt: str | None = None,
    env: desktop.DesktopEnvironment | None = None,
) -> dict:
    env = env or desktop.detect_environment()
    session = desktop.attach_existing_browser(
        profile=profile,
        browser=browser,
        cdp_endpoint=cdp_endpoint,
        env=env,
    )
    desktop._host_pwcli([f"-s={session}", "tab-new", url], env=env, timeout=120)
    if prompt:
        print(prompt)
        input()

    evidence = _raw_eval_json(
        session,
        "() => JSON.stringify({href:location.href,title:document.title})",
        expected=dict,
        env=env,
    )
    href = str(evidence.get("href") or "")
    if not re.match(r"^https://(www\.)?chatgpt\.com/.+/project(?:[/?#].*)?$", href):
        raise desktop.DesktopBrowserBridgeError("The current browser tab is not a ChatGPT Project.")
    normalized = href.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    name = str(evidence.get("title") or "").strip() or normalized.split("/")[-2]
    return {"name": name, "url": normalized}


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    desktop.chatgpt_login_evidence = chatgpt_login_evidence
    desktop.discover_projects = discover_projects
    desktop.capture_project_from_url = capture_project_from_url
