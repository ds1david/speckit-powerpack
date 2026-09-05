from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import cli as core
from .review_onboarding import (
    ReviewAuthorizationResult,
    authorize_chatgpt_project,
    browser_install_ready,
    ensure_chromium,
)


def playwright_browser_ready() -> bool:
    return core.playwright_package_ready() and browser_install_ready(core.global_root(), core.platform_key())


def ensure_playwright_browser() -> None:
    core.ensure_playwright()
    try:
        ensure_chromium(core.global_root(), core.platform_key())
    except RuntimeError as exc:
        raise core.PowerPackError(
            "Playwright is installed but Chromium could not be prepared: " + str(exc)
        ) from exc


def review_readiness(project: Path) -> dict[str, bool]:
    review_path = project / ".specify" / "powerpack" / "review.json"
    if not review_path.is_file():
        return {
            "web-review-required": False,
            "playwright-package": core.playwright_package_ready(),
            "playwright-browser": playwright_browser_ready(),
            "chatgpt-authenticated": False,
            "chatgpt-project-bound": False,
        }
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        review = {}
    web = review.get("chatgpt_web", {}) if isinstance(review, dict) else {}
    current = core.platform_key()
    profile = web.get("profile") if isinstance(web, dict) else None
    alias = web.get("project_alias") if isinstance(web, dict) else None
    url = web.get("project_url") if isinstance(web, dict) else None

    _, global_data = core.global_config()
    authenticated = global_data.get("authenticated_profiles", {}).get(current, {})
    authorization = global_data.get("authorizations", {}).get(current, {}).get(profile) if profile else None
    auth_ok = bool(
        profile
        and authenticated.get(profile, {}).get("source") == "playwright-consent"
        and isinstance(authorization, dict)
        and authorization.get("scope") == "chatgpt-web-review"
        and authorization.get("project_alias") == alias
        and authorization.get("project_url") == url
        and core.profile_dir(profile, create=False).is_dir()
    )

    registered = global_data.get("projects", {}).get(alias) if alias else None
    binding = registered.get("bindings", {}).get(current) if isinstance(registered, dict) else None
    project_ok = bool(
        alias
        and profile
        and url
        and web.get("authorization") == "playwright-consent"
        and isinstance(binding, dict)
        and binding.get("profile") == profile
        and binding.get("url") == url
        and binding.get("authorization") == "playwright-consent"
    )
    return {
        "web-review-required": bool(web.get("required") and web.get("enabled")) if isinstance(web, dict) else False,
        "playwright-package": core.playwright_package_ready(),
        "playwright-browser": playwright_browser_ready(),
        "chatgpt-authenticated": auth_ok,
        "chatgpt-project-bound": project_ok,
    }


def print_review_setup_status(project: Path) -> None:
    readiness = core.review_readiness(project)
    if all(readiness.values()):
        print("Mandatory ChatGPT Project Web review is configured and ready.")
        return
    print("\nMANDATORY REVIEW AUTHORIZATION REQUIRED")
    print("PowerPack is installed. Authorize ChatGPT Web in one isolated Playwright profile:")
    print(
        "  speckit-powerpack review authorize --profile <profile> --project <alias> "
        "--url https://chatgpt.com/g/g-p-.../project --path ."
    )
    print("The authorization screen opens inside PowerPack Chromium, never your Windows Edge/Chrome profile.")
    print("Credentials and MFA are entered only on chatgpt.com.\n")


def cmd_review_setup(args: argparse.Namespace) -> None:
    ensure_playwright_browser()
    print("Playwright and isolated Chromium review dependencies are ready.")


def _write_authorized_project(
    *,
    result: ReviewAuthorizationResult,
    project_path: Path,
) -> None:
    cfg_path, data = core.global_config()
    current = result.platform
    profile = result.profile
    alias = result.project_alias
    data.setdefault("active_profiles", {})[current] = profile
    data.setdefault("authenticated_profiles", {}).setdefault(current, {})[profile] = {
        "confirmed": True,
        "source": "playwright-consent",
        "granted_at": result.granted_at,
    }
    data.setdefault("authorizations", {}).setdefault(current, {})[profile] = {
        "scope": "chatgpt-web-review",
        "project_alias": alias,
        "project_url": result.project_url,
        "profile_dir": result.profile_dir,
        "granted_at": result.granted_at,
    }
    registered = data.setdefault("projects", {}).setdefault(alias, {"bindings": {}})
    registered.setdefault("bindings", {})[current] = {
        "url": result.project_url,
        "profile": profile,
        "authorization": "playwright-consent",
    }
    core.save_global(cfg_path, data)

    review_path = project_path / ".specify" / "powerpack" / "review.json"
    if not review_path.is_file():
        raise core.PowerPackError(
            "PowerPack review config is missing; install/refresh PowerPack in this project before authorizing Web review."
        )
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise core.PowerPackError(f"Cannot read PowerPack review config: {exc}") from exc
    web = review.setdefault("chatgpt_web", {})
    web["required"] = True
    web["enabled"] = True
    web["project_alias"] = alias
    web["project_url"] = result.project_url
    web["profile"] = profile
    web["profile_scope"] = "platform"
    web["profile_platform"] = current
    web["authorization"] = "playwright-consent"
    core.write_json(review_path, review, overwrite=True)


def cmd_review_authorize(args: argparse.Namespace) -> None:
    project_path = Path(args.path).expanduser().resolve()
    if not (project_path / ".specify" / "powerpack" / "review.json").is_file():
        raise core.PowerPackError(
            "Target project is not PowerPack-ready. Run 'speckit-powerpack install . --integration <executor>' first."
        )
    url = core.validate_project_url(args.url)
    current = core.platform_key()
    profile_path = core.profile_dir(args.profile)
    try:
        result = authorize_chatgpt_project(
            config_root=core.global_root(),
            platform=current,
            profile=args.profile,
            profile_dir=profile_path,
            project_alias=args.project,
            project_url=url,
        )
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    if not result.granted:
        raise core.PowerPackError("ChatGPT Web authorization was cancelled; no Project binding was recorded.")
    _write_authorized_project(result=result, project_path=project_path)
    print(
        f"Authorized ChatGPT Project '{result.project_alias}' using isolated Playwright profile "
        f"'{result.profile}' on {result.platform}."
    )
    print(f"Profile storage: {result.profile_dir}")
    print("Run 'speckit-powerpack doctor' to validate review readiness.")


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise core.PowerPackError("Internal CLI error: subparser registry not found")


def build_parser() -> argparse.ArgumentParser:
    parser = core.build_parser()
    root = _subparsers(parser)
    review_parser = root.choices["review"]
    review_sub = _subparsers(review_parser)
    if "authorize" not in review_sub.choices:
        p = review_sub.add_parser(
            "authorize",
            help="Authorize mandatory ChatGPT Web review in an isolated Playwright profile",
        )
        p.add_argument("--profile", required=True)
        p.add_argument("--project", required=True)
        p.add_argument("--url", required=True)
        p.add_argument("--path", default=".")
        p.set_defaults(func=cmd_review_authorize)
    return parser


def _patch_core_runtime() -> None:
    # Keep existing command implementations while replacing browser readiness/setup
    # and authorization-aware readiness. This removes the old sync_playwright()
    # readiness probe that could leave pending connection tasks under Python 3.13.
    core.playwright_browser_ready = playwright_browser_ready
    core.ensure_playwright_browser = ensure_playwright_browser
    core.review_readiness = review_readiness
    core.print_review_setup_status = print_review_setup_status
    core.cmd_review_setup = cmd_review_setup


def main(argv: list[str] | None = None) -> int:
    _patch_core_runtime()
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


_patch_core_runtime()
