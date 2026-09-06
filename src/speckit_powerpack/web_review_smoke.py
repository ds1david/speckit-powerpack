from __future__ import annotations

from dataclasses import dataclass
import json
import re

from . import desktop_browser_bridge as desktop


DEFAULT_SMOKE_PROMPT = (
    "me diga qual é o nome do projeto e sua principal missão, produza uma resposta simplificada "
    "de no máximo 100 palavras. e me responda quanto é 1 +1"
)


class WebReviewSmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebReviewSmokeResult:
    project_url_requested: str
    project_url_loaded: str
    conversation_url: str
    response: str
    response_words: int
    arithmetic_check: bool
    max_words_check: bool


def _playwright_script(project_url: str, prompt: str, timeout_ms: int) -> str:
    project_json = json.dumps(project_url, ensure_ascii=False)
    prompt_json = json.dumps(prompt, ensure_ascii=False)
    return f"""async page => {{
  const projectUrl = {project_json};
  const prompt = {prompt_json};
  const timeoutMs = {timeout_ms};

  await page.goto(projectUrl, {{ waitUntil: 'domcontentloaded', timeout: timeoutMs }});

  const requested = new URL(projectUrl);
  const loaded = new URL(page.url());
  const normalizePath = value => value.replace(/\\/$/, '');
  if (requested.origin !== loaded.origin || normalizePath(requested.pathname) !== normalizePath(loaded.pathname)) {{
    throw new Error(`Project navigation mismatch: requested ${{projectUrl}}, loaded ${{page.url()}}`);
  }}

  const loginUrl = page.url().toLowerCase();
  if (loginUrl.includes('/auth') || loginUrl.includes('/login') || loginUrl.includes('auth.openai.com')) {{
    throw new Error('ChatGPT session is not authenticated in the selected reviewer browser.');
  }}

  const composerSelectors = [
    '#prompt-textarea',
    'textarea#prompt-textarea',
    'div#prompt-textarea',
    'main textarea[data-id="root"]',
    'main textarea[placeholder*="Message"]',
    'main textarea[placeholder*="message"]',
    'main textarea[placeholder*="Ask"]',
    'main textarea[placeholder*="ask"]',
    'main div[contenteditable="true"][data-placeholder]'
  ];

  let composer = null;
  for (const selector of composerSelectors) {{
    const candidate = page.locator(selector).first();
    if (await candidate.count()) {{
      try {{
        if (await candidate.isVisible()) {{ composer = candidate; break; }}
      }} catch (_) {{}}
    }}
  }}
  if (!composer) {{
    const main = page.locator('main');
    if (await main.count()) {{
      const textbox = main.getByRole('textbox').last();
      if (await textbox.count()) {{
        try {{ if (await textbox.isVisible()) composer = textbox; }} catch (_) {{}}
      }}
    }}
  }}
  if (!composer) throw new Error('No visible ChatGPT prompt composer matched known selectors.');

  const assistantSelectors = [
    '[data-message-author-role="assistant"]',
    '[data-testid="conversation-turn-assistant"]'
  ];
  let before = 0;
  for (const selector of assistantSelectors) {{
    before = Math.max(before, await page.locator(selector).count());
  }}

  await composer.click({{ timeout: 10000 }});
  await composer.fill('');
  await composer.fill(prompt);
  await page.keyboard.press('Enter');

  await page.waitForFunction(
    (arg) => {{
      let count = 0;
      for (const selector of arg.selectors) count = Math.max(count, document.querySelectorAll(selector).length);
      return count > arg.before;
    }},
    {{ selectors: assistantSelectors, before }},
    {{ timeout: timeoutMs }}
  );

  let assistant = null;
  let assistantCount = 0;
  for (const selector of assistantSelectors) {{
    const current = page.locator(selector);
    const count = await current.count();
    if (count > assistantCount) {{
      assistantCount = count;
      assistant = current.nth(count - 1);
    }}
  }}
  if (!assistant) throw new Error('Assistant response container was not found after submit.');

  let previous = '';
  let stableRounds = 0;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {{
    let text = '';
    try {{ text = (await assistant.innerText()).trim(); }} catch (_) {{}}
    const stop = page.locator(
      'button[data-testid="stop-button"], button[aria-label*="Stop" i], button[aria-label*="Parar" i]'
    );
    let stopVisible = false;
    try {{ stopVisible = (await stop.count()) > 0 && await stop.first().isVisible(); }} catch (_) {{}}

    if (text && text === previous && !stopVisible) stableRounds += 1;
    else stableRounds = 0;
    previous = text;
    if (stableRounds >= 3) break;
    await page.waitForTimeout(750);
  }}

  const response = previous.trim();
  if (!response) throw new Error('ChatGPT returned an empty assistant response.');
  const responseWords = response.split(/\\s+/).filter(Boolean).length;
  const arithmeticCheck = /(^|\\D)2(\\D|$)/.test(response) || /\\bdois\\b/i.test(response) || /\\btwo\\b/i.test(response);
  return {{
    project_url_requested: projectUrl,
    project_url_loaded: loaded.href,
    conversation_url: page.url(),
    response,
    response_words: responseWords,
    arithmetic_check: arithmeticCheck,
    max_words_check: responseWords <= 100
  }};
}}"""


def _parse_result(stdout: str, stderr: str) -> WebReviewSmokeResult:
    # playwright-cli run-code JSON.stringify()s the function return value. With
    # --raw, stdout should therefore be the returned JSON object and nothing else.
    payload = (stdout or "").strip()
    if not payload:
        detail = (stderr or "").strip()
        raise WebReviewSmokeError(
            "Playwright CLI returned no machine-readable Web review result"
            + (f": {detail}" if detail else ".")
        )

    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(payload)
    except json.JSONDecodeError as exc:
        # Be tolerant of a future CLI version adding one short status line around
        # raw output, but never scrape arbitrary browser text as a result.
        match = re.search(r"(\{.*\})", payload, flags=re.DOTALL)
        if not match:
            raise WebReviewSmokeError("Could not parse the Web review result returned by Playwright CLI.") from exc
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as nested:
            raise WebReviewSmokeError("Could not parse the Web review JSON payload.") from nested

    if not isinstance(value, dict) or not str(value.get("response") or "").strip():
        raise WebReviewSmokeError("Web review result is missing the assistant response.")
    return WebReviewSmokeResult(
        project_url_requested=str(value.get("project_url_requested") or ""),
        project_url_loaded=str(value.get("project_url_loaded") or ""),
        conversation_url=str(value.get("conversation_url") or ""),
        response=str(value.get("response") or "").strip(),
        response_words=int(value.get("response_words") or 0),
        arithmetic_check=bool(value.get("arithmetic_check")),
        max_words_check=bool(value.get("max_words_check")),
    )


def run_bound_project_prompt(
    *,
    profile: str,
    browser: desktop.BrowserCandidate,
    project_url: str,
    prompt: str = DEFAULT_SMOKE_PROMPT,
    cdp_endpoint: str | None = None,
    timeout_seconds: int = 120,
    env: desktop.DesktopEnvironment | None = None,
) -> WebReviewSmokeResult:
    if not prompt.strip():
        raise WebReviewSmokeError("Smoke-test prompt is empty.")
    if timeout_seconds < 10:
        raise WebReviewSmokeError("Smoke-test timeout must be at least 10 seconds.")

    env = env or desktop.detect_environment()
    try:
        session = desktop.attach_existing_browser(
            profile=profile,
            browser=browser,
            cdp_endpoint=cdp_endpoint,
            env=env,
        )
        script = _playwright_script(project_url, prompt, timeout_seconds * 1000)
        proc = desktop._host_pwcli(
            [f"-s={session}", "--raw", "run-code", script],
            env=env,
            timeout=timeout_seconds + 60,
        )
    except desktop.DesktopBrowserBridgeError as exc:
        raise WebReviewSmokeError(str(exc)) from exc
    return _parse_result(proc.stdout or "", proc.stderr or "")
