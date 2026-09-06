from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import cli as core
from . import cli_account_binding as account_base
from . import cli_browser_accounts as previous
from . import cli_desktop_auth as desktop_auth
from . import desktop_browser_bridge as desktop
from .web_review_smoke import DEFAULT_SMOKE_PROMPT, WebReviewSmokeError, run_bound_project_prompt


def _bound_web_context(project: Path) -> tuple[dict, str, dict, desktop.BrowserCandidate]:
    readiness = desktop_auth.review_readiness(project)
    if not all(readiness.values()):
        desktop_auth.print_review_setup_status(project)
        missing = ", ".join(key for key, ok in readiness.items() if not ok)
        raise core.PowerPackError(f"Web review binding is not ready: {missing}")

    _, review = account_base._review_config(project)
    web = review.get("chatgpt_web")
    if not isinstance(web, dict):
        raise core.PowerPackError("review.json has no chatgpt_web object.")
    profile = str(web.get("profile") or "")
    project_url = str(web.get("project_url") or "")
    if not profile or not project_url:
        raise core.PowerPackError("The repository has no active ChatGPT reviewer profile/Project URL binding.")

    _, account = desktop_auth._require_account(profile)
    backend = desktop_auth._account_backend(account)
    if backend != desktop_auth.DESKTOP_ACCOUNT_BACKEND:
        raise core.PowerPackError(
            "The functional smoke test currently requires backend=desktop-browser-context so it can validate "
            "the same existing browser/account that will perform the Web review. Reconfigure this reviewer with "
            "'speckit-powerpack review auth configure'."
        )

    env = desktop.detect_environment()
    browser = desktop_auth._browser_for_record(account, previous._detected_browsers(env))
    return web, profile, account, browser


def cmd_review_smoke_test(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    web, profile, account, browser = _bound_web_context(project)
    project_url = str(web["project_url"])
    project_alias = str(web.get("project_alias") or "")
    project_name = str(web.get("project_name") or project_alias or project_url)
    account_label = str(account.get("account_label") or profile)
    env = desktop.detect_environment()

    prompt = args.prompt or DEFAULT_SMOKE_PROMPT
    print("\nCHATGPT WEB REVIEW — FUNCTIONAL SMOKE TEST")
    print(f"  repository: {project}")
    print(f"  reviewer profile: {profile}")
    print(f"  reviewer account: {account_label}")
    print(f"  browser host: {env.host_scope}")
    print(f"  browser: {browser.label}")
    print(f"  project alias: {project_alias or 'n/a'}")
    print(f"  project name: {project_name}")
    print(f"  project URL: {project_url}")
    print("  policy: no automatic reviewer/browser/project fallback")
    print("\nPrompt enviado ao Project:")
    print(prompt)
    print("\nAguardando resposta do ChatGPT Web...")

    try:
        result = run_bound_project_prompt(
            profile=profile,
            browser=browser,
            project_url=project_url,
            prompt=prompt,
            cdp_endpoint=str(account.get("cdp_endpoint")) if account.get("cdp_endpoint") else None,
            timeout_seconds=args.timeout,
            env=env,
        )
    except WebReviewSmokeError as exc:
        raise core.PowerPackError(f"Functional Web review smoke test failed: {exc}") from exc

    payload = {
        "status": "ok",
        "profile": profile,
        "account_label": account_label,
        "browser": browser.browser_id,
        "project_alias": project_alias,
        "project_name": project_name,
        "project_url_requested": result.project_url_requested,
        "project_url_loaded": result.project_url_loaded,
        "conversation_url": result.conversation_url,
        "response": result.response,
        "response_words": result.response_words,
        "arithmetic_check": result.arithmetic_check,
        "max_words_check": result.max_words_check,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n=== RESPOSTA RECEBIDA ===")
        print(result.response)
        print("\n=== VALIDAÇÃO ===")
        print(f"PASS Project URL vinculada foi aberta: {result.project_url_loaded}")
        print(f"{'PASS' if result.max_words_check else 'FAIL'} resposta <= 100 palavras ({result.response_words})")
        print(f"{'PASS' if result.arithmetic_check else 'FAIL'} resposta contém resultado 1 + 1 = 2")
        print(f"Conversation URL: {result.conversation_url}")

    if not result.arithmetic_check or not result.max_words_check:
        raise core.PowerPackError(
            "ChatGPT Web responded through the bound Project, but the smoke prompt content contract was not fully satisfied."
        )
    print("\nSMOKE TEST PASSED: reviewer account → browser → bound Project → prompt → response.")


def build_parser() -> argparse.ArgumentParser:
    parser = previous.build_parser()
    root = account_base._subparsers(parser)
    review = root.choices["review"]
    rsub = account_base._subparsers(review)
    if "smoke-test" not in rsub.choices:
        p = rsub.add_parser(
            "smoke-test",
            help="Send a real prompt through the repository's bound ChatGPT Project and capture the response",
        )
        p.add_argument("--path", default=".")
        p.add_argument("--timeout", type=int, default=120)
        p.add_argument("--prompt", help="Override the built-in functional smoke prompt")
        p.add_argument("--json", action="store_true", help="Print machine-readable result JSON")
        p.set_defaults(func=cmd_review_smoke_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    core.review_readiness = lambda project: desktop_auth.review_readiness(project)
    core.print_review_setup_status = desktop_auth.print_review_setup_status
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
        return 0
    except (core.PowerPackError, core.UpdateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


core.review_readiness = lambda project: desktop_auth.review_readiness(project)
core.print_review_setup_status = desktop_auth.print_review_setup_status
