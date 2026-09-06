from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from . import cli as core
from . import cli_account_binding as binding


DEFAULT_PROMPT = Path(".specify/powerpack/runtime/web-review-prompt.txt")
DEFAULT_OUTPUT = Path(".specify/powerpack/runtime/web-review.json")
DEFAULT_RAW = Path(".specify/powerpack/runtime/web-review.raw.txt")
ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]'
LOGIN_PATH_MARKERS = ("/auth/login", "/auth/signup", "/login", "/signup")


@dataclass(frozen=True)
class WebReviewConfig:
    project: Path
    project_url: str
    profile: str
    account_label: str
    prompt_path: Path
    output_path: Path
    raw_path: Path
    headless: bool
    timeout_seconds: int


def _review_config(project: Path) -> dict[str, Any]:
    path = project / ".specify" / "powerpack" / "review.json"
    if not path.is_file():
        raise core.PowerPackError("PowerPack review config is missing.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise core.PowerPackError(f"Cannot read PowerPack review config: {exc}") from exc
    if not isinstance(data, dict):
        raise core.PowerPackError("PowerPack review config must contain an object.")
    return data


def _path(project: Path, value: str | None, default: Path) -> Path:
    candidate = Path(value) if value else default
    return candidate if candidate.is_absolute() else project / candidate


def resolve_config(args: argparse.Namespace) -> WebReviewConfig:
    project = Path(args.path).expanduser().resolve()
    review = _review_config(project)
    web = review.get("chatgpt_web")
    if not isinstance(web, dict):
        raise core.PowerPackError("chatgpt_web review config is missing.")
    readiness = binding.review_readiness(project)
    if not all(readiness.values()):
        missing = ", ".join(key for key, ok in readiness.items() if not ok)
        raise core.PowerPackError(
            "Mandatory ChatGPT Web review is not ready: "
            + missing
            + ". Run 'speckit-powerpack doctor --strict-review'."
        )
    project_url = str(web.get("project_url") or "")
    profile = str(web.get("profile") or "")
    if not project_url or not profile:
        raise core.PowerPackError("ChatGPT Project URL/profile binding is incomplete.")
    headless = bool(web.get("headless", False))
    if args.headless:
        headless = True
    if args.headed:
        headless = False
    timeout_seconds = int(args.timeout)
    if timeout_seconds < 30:
        raise core.PowerPackError("--timeout must be at least 30 seconds.")
    return WebReviewConfig(
        project=project,
        project_url=core.validate_project_url(project_url),
        profile=profile,
        account_label=str(web.get("account_label") or profile),
        prompt_path=_path(project, args.prompt or web.get("prompt_path"), DEFAULT_PROMPT),
        output_path=_path(project, args.output, DEFAULT_OUTPUT),
        raw_path=_path(project, args.raw_output, DEFAULT_RAW),
        headless=headless,
        timeout_seconds=timeout_seconds,
    )


def _run_protocol(config: WebReviewConfig, *argv: str) -> subprocess.CompletedProcess[str]:
    protocol = config.project / ".specify" / "powerpack" / "bin" / "review_protocol.py"
    if not protocol.is_file():
        raise core.PowerPackError("PowerPack review protocol runtime is missing; reinstall/update PowerPack.")
    return subprocess.run(
        [sys.executable, str(protocol), *argv],
        cwd=str(config.project),
        text=True,
        capture_output=True,
    )


def prepare_prompt(config: WebReviewConfig) -> str:
    config.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    proc = _run_protocol(config, "web-prompt", "--output", str(config.prompt_path))
    if proc.returncode != 0:
        detail = (proc.stdout + "\n" + proc.stderr).strip()
        raise core.PowerPackError("Web review prompt could not be generated from a fresh manifest. " + detail)
    prompt = config.prompt_path.read_text(encoding="utf-8")
    if not prompt.strip():
        raise core.PowerPackError("Generated Web review prompt is empty.")
    return prompt


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise core.PowerPackError("ChatGPT Web response did not contain a JSON review object.")


def _composer(page: Any) -> Any:
    selectors = (
        "#prompt-textarea",
        'textarea[data-testid="prompt-textarea"]',
        '[contenteditable="true"][data-testid="prompt-textarea"]',
        'textarea[placeholder*="Message"]',
        'textarea[placeholder*="mensagem" i]',
        '[contenteditable="true"]',
    )
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(count - 1, -1, -1):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
    raise core.PowerPackError(
        "ChatGPT Project opened, but no visible prompt composer was found. "
        "The Web UI may have changed or the Project may not be accessible."
    )


def _send(page: Any, composer: Any, prompt: str) -> None:
    try:
        composer.fill(prompt)
    except Exception:
        composer.click()
        composer.press("ControlOrMeta+A")
        page.keyboard.insert_text(prompt)
    send_selectors = (
        'button[data-testid="send-button"]',
        'button[aria-label*="Send" i]',
        'button[aria-label*="Enviar" i]',
        'button[aria-label*="Submit" i]',
    )
    for selector in send_selectors:
        locator = page.locator(selector)
        try:
            for index in range(locator.count() - 1, -1, -1):
                button = locator.nth(index)
                if button.is_visible() and button.is_enabled():
                    button.click()
                    return
        except Exception:
            continue
    composer.press("Enter")


def _login_or_access_failure(page: Any, expected_url: str) -> str | None:
    current = str(page.url or "")
    lowered = current.casefold()
    if any(marker in lowered for marker in LOGIN_PATH_MARKERS):
        return f"ChatGPT session is not authenticated (redirected to {current})."
    if "chatgpt.com" not in lowered:
        return f"Unexpected navigation outside ChatGPT: {current}"
    try:
        body = page.locator("body").inner_text(timeout=3000).casefold()
    except Exception:
        body = ""
    denied_markers = (
        "project not found",
        "you don't have access",
        "you do not have access",
        "projeto não encontrado",
        "você não tem acesso",
    )
    if any(marker in body for marker in denied_markers):
        return "The authenticated account cannot access the configured ChatGPT Project."
    if expected_url.rstrip("/") not in current.rstrip("/") and not current.rstrip("/").endswith("/project"):
        if "/c/" in lowered:
            return f"Configured Project did not open; browser landed on another conversation: {current}"
    return None


def _wait_for_response(page: Any, baseline_count: int, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    assistant = page.locator(ASSISTANT_SELECTOR)
    last_text = ""
    stable = 0
    response_seen = False
    while time.monotonic() < deadline:
        try:
            count = assistant.count()
        except Exception:
            count = 0
        if count > baseline_count:
            response_seen = True
            try:
                text = assistant.nth(count - 1).inner_text().strip()
            except Exception:
                text = ""
            if text and text == last_text:
                stable += 1
            else:
                last_text = text
                stable = 0
            stop_visible = False
            for selector in (
                'button[data-testid="stop-button"]',
                'button[aria-label*="Stop" i]',
                'button[aria-label*="Parar" i]',
            ):
                try:
                    locator = page.locator(selector)
                    stop_visible = any(locator.nth(i).is_visible() for i in range(locator.count()))
                except Exception:
                    stop_visible = False
                if stop_visible:
                    break
            if text and stable >= 3 and not stop_visible:
                return text
        time.sleep(1)
    if response_seen and last_text:
        raise core.PowerPackError(
            "ChatGPT Web produced a response but it did not reach a stable completed state before the timeout."
        )
    raise core.PowerPackError("ChatGPT Web did not produce an assistant response before the timeout.")


def run_web_review(config: WebReviewConfig) -> dict[str, Any]:
    prompt = prepare_prompt(config)
    core.ensure_playwright_browser()
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.raw_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(core.profile_dir(config.profile)),
                headless=config.headless,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(config.project_url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                failure = _login_or_access_failure(page, config.project_url)
                if failure:
                    raise core.PowerPackError(failure)
                baseline = page.locator(ASSISTANT_SELECTOR).count()
                composer = _composer(page)
                _send(page, composer, prompt)
                raw = _wait_for_response(page, baseline, config.timeout_seconds)
            finally:
                context.close()
    except PlaywrightError as exc:
        raise core.PowerPackError(f"Playwright failed during ChatGPT Web review: {exc}") from exc

    config.raw_path.write_text(raw + "\n", encoding="utf-8")
    payload = _extract_json(raw)
    config.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation = _run_protocol(config, "validate", "--input", str(config.output_path))
    if validation.returncode != 0:
        detail = (validation.stdout + "\n" + validation.stderr).strip()
        raise core.PowerPackError(
            "ChatGPT Web returned a review, but it failed the manifest-bound review contract. " + detail
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="speckit-powerpack-web-review",
        description="Run the mandatory ChatGPT Project Web review using the configured isolated Playwright profile.",
    )
    parser.add_argument("--path", default=".", help="Spec Kit project root")
    parser.add_argument("--prompt", help="Override generated Web review prompt path")
    parser.add_argument("--output", help="Review JSON output path")
    parser.add_argument("--raw-output", help="Raw assistant response output path")
    parser.add_argument("--timeout", type=int, default=600, help="Maximum response wait in seconds")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true")
    mode.add_argument("--headed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = resolve_config(args)
        payload = run_web_review(config)
        print(json.dumps({
            "status": "VALID",
            "provider": "chatgpt-web",
            "project_url": config.project_url,
            "profile": config.profile,
            "account_label": config.account_label,
            "output": str(config.output_path),
            "verdict": payload.get("verdict"),
        }, ensure_ascii=False))
        return 0
    except (core.PowerPackError, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "provider": "chatgpt-web",
            "reason": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
