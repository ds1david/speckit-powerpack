from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from . import cli as core
from .review_onboarding import (
    AccountAuthorizationResult,
    ProjectCandidate,
    authorize_chatgpt_account,
    discover_chatgpt_projects,
    is_chatgpt_project_url,
    open_link_and_capture_project,
    select_chatgpt_project_interactively,
)


ACCOUNT_AUTH_SOURCE = "playwright-account-consent"
PROJECT_BINDING_AUTH = "playwright-account-consent"
STALE_BINDING_AUTH = "stale-account-reauth"


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise core.PowerPackError("Internal CLI error: subparser registry not found")


def _review_config(project: Path) -> tuple[Path, dict[str, Any]]:
    path = project / ".specify" / "powerpack" / "review.json"
    if not path.is_file():
        raise core.PowerPackError("PowerPack review config is missing; install/refresh PowerPack first.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise core.PowerPackError(f"Cannot read PowerPack review config: {exc}") from exc
    if not isinstance(data, dict):
        raise core.PowerPackError("PowerPack review config must contain an object.")
    return path, data


def _account_record(global_data: dict[str, Any], platform: str, profile: str | None) -> dict[str, Any] | None:
    if not profile:
        return None
    record = global_data.get("accounts", {}).get(platform, {}).get(profile)
    return record if isinstance(record, dict) else None


def _account_authorized(global_data: dict[str, Any], platform: str, profile: str | None) -> bool:
    record = _account_record(global_data, platform, profile)
    return bool(
        profile
        and record
        and record.get("source") == ACCOUNT_AUTH_SOURCE
        and core.profile_dir(profile, create=False).is_dir()
    )


def _platform_bindings(registered: dict[str, Any], platform: str) -> dict[str, dict[str, Any]]:
    raw = registered.get("bindings", {}).get(platform)
    if not isinstance(raw, dict):
        return {}
    if "url" in raw and "profile" in raw:
        profile = str(raw.get("profile") or "legacy")
        return {profile: raw}
    return {str(profile): binding for profile, binding in raw.items() if isinstance(binding, dict)}


def _binding_for(registered: dict[str, Any], platform: str, profile: str | None) -> dict[str, Any] | None:
    bindings = _platform_bindings(registered, platform)
    if profile and profile in bindings:
        return bindings[profile]
    return None


def _invalidate_profile_bindings(data: dict[str, Any], platform: str, profile: str) -> list[str]:
    invalidated: list[str] = []
    for alias, registered in data.setdefault("projects", {}).items():
        if not isinstance(registered, dict):
            continue
        raw = registered.setdefault("bindings", {}).get(platform)
        if not isinstance(raw, dict):
            continue
        if "url" in raw and raw.get("profile") == profile:
            raw["authorization"] = STALE_BINDING_AUTH
            invalidated.append(str(alias))
            continue
        binding = raw.get(profile)
        if isinstance(binding, dict):
            binding["authorization"] = STALE_BINDING_AUTH
            invalidated.append(str(alias))
    return invalidated


def _remove_profile_bindings(data: dict[str, Any], platform: str, profile: str) -> list[str]:
    removed: list[str] = []
    for alias, registered in data.setdefault("projects", {}).items():
        if not isinstance(registered, dict):
            continue
        raw = registered.setdefault("bindings", {}).get(platform)
        if not isinstance(raw, dict):
            continue
        if "url" in raw and raw.get("profile") == profile:
            registered["bindings"].pop(platform, None)
            removed.append(str(alias))
            continue
        if profile in raw:
            raw.pop(profile, None)
            removed.append(str(alias))
        if not raw:
            registered["bindings"].pop(platform, None)
    return removed


def review_readiness(project: Path) -> dict[str, bool]:
    try:
        _, review = _review_config(project)
    except core.PowerPackError:
        return {
            "web-review-required": False,
            "playwright-package": core.playwright_package_ready(),
            "playwright-browser": core.playwright_browser_ready(),
            "chatgpt-account-authenticated": False,
            "chatgpt-project-bound": False,
        }
    web = review.get("chatgpt_web", {}) if isinstance(review, dict) else {}
    if not isinstance(web, dict):
        web = {}
    platform = core.platform_key()
    profile = web.get("profile")
    alias = web.get("project_alias")
    url = web.get("project_url")
    _, global_data = core.global_config()
    account_ok = _account_authorized(global_data, platform, profile)
    registered = global_data.get("projects", {}).get(alias) if alias else None
    binding = _binding_for(registered, platform, profile) if isinstance(registered, dict) else None
    project_ok = bool(
        account_ok
        and alias
        and url
        and isinstance(binding, dict)
        and binding.get("profile") == profile
        and binding.get("url") == url
        and binding.get("authorization") == PROJECT_BINDING_AUTH
        and web.get("authorization") == PROJECT_BINDING_AUTH
    )
    return {
        "web-review-required": bool(web.get("required") and web.get("enabled")),
        "playwright-package": core.playwright_package_ready(),
        "playwright-browser": core.playwright_browser_ready(),
        "chatgpt-account-authenticated": account_ok,
        "chatgpt-project-bound": project_ok,
    }


def print_review_setup_status(project: Path) -> None:
    readiness = review_readiness(project)
    if all(readiness.values()):
        print("Mandatory ChatGPT Web review is ready: account profile and Project binding are configured.")
        return
    print("\nCHATGPT WEB REVIEW SETUP")
    if not readiness["chatgpt-account-authenticated"]:
        print("1. Authorize a dedicated PowerPack browser profile for the ChatGPT account that will perform Web review:")
        print("   speckit-powerpack review auth authorize <profile> --account-label <label>")
    if not readiness["chatgpt-project-bound"]:
        print("2. Discover/select a Project accessible to that account and bind it to this repository:")
        print("   speckit-powerpack review project select --profile <profile> --path .")
        print("   # or accept/open a shared/invite link:")
        print("   speckit-powerpack review project accept-invite '<chatgpt-link>' --profile <profile> --path .")
    print("Profiles are stored under the PowerPack config root and never reuse Windows Edge/Chrome profiles.")
    print("Use 'speckit-powerpack doctor --strict-review' when you need a failing readiness gate.\n")


def _persist_account(result: AccountAuthorizationResult) -> list[str]:
    path, data = core.global_config()
    platform = result.platform
    invalidated = _invalidate_profile_bindings(data, platform, result.profile)
    data["schema_version"] = max(3, int(data.get("schema_version", 0) or 0))
    data.setdefault("active_profiles", {})[platform] = result.profile
    data.setdefault("accounts", {}).setdefault(platform, {})[result.profile] = {
        "source": ACCOUNT_AUTH_SOURCE,
        "account_label": result.account_label or result.profile,
        "profile_dir": result.profile_dir,
        "granted_at": result.granted_at,
    }
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {})[result.profile] = {
        "confirmed": True,
        "source": ACCOUNT_AUTH_SOURCE,
        "account_label": result.account_label or result.profile,
        "granted_at": result.granted_at,
    }
    core.save_global(path, data)
    return invalidated


def cmd_auth_authorize(args: argparse.Namespace) -> None:
    profile_path = core.profile_dir(args.profile)
    try:
        result = authorize_chatgpt_account(
            config_root=core.global_root(),
            platform=core.platform_key(),
            profile=args.profile,
            profile_dir=profile_path,
            account_label=args.account_label,
        )
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    if not result.granted:
        raise core.PowerPackError("ChatGPT account authorization was cancelled; no account grant was recorded.")
    invalidated = _persist_account(result)
    print(f"Authorized ChatGPT account profile '{args.profile}' ({result.account_label or args.profile}).")
    print(f"Isolated profile storage: {result.profile_dir}")
    if invalidated:
        print("Existing Project bindings for this profile were marked stale and must be re-verified: " + ", ".join(sorted(set(invalidated))))
    print("This profile may now discover/bind any ChatGPT Project accessible to this authenticated account.")


def cmd_auth_list(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    current = core.platform_key()
    active = data.get("active_profiles", {}).get(current)
    accounts = data.get("accounts", {}).get(current, {})
    if not accounts:
        print("No authorized ChatGPT account profiles for this platform.")
        return
    for profile, record in sorted(accounts.items()):
        marker = "*" if profile == active else " "
        label = record.get("account_label") if isinstance(record, dict) else None
        print(f"{marker} {profile}: account={label or profile} platform={current}")


def cmd_auth_use(args: argparse.Namespace) -> None:
    path, data = core.global_config()
    current = core.platform_key()
    if not _account_authorized(data, current, args.profile):
        raise core.PowerPackError(f"Profile '{args.profile}' is not an authorized ChatGPT account on {current}.")
    data.setdefault("active_profiles", {})[current] = args.profile
    core.save_global(path, data)
    print(f"Active ChatGPT account profile is now '{args.profile}' on {current}.")
    print("The repository's Web reviewer identity changes only after project use/select/add with that profile.")


def cmd_auth_reconfigure(args: argparse.Namespace) -> None:
    if args.fresh:
        profile_path = core.profile_dir(args.profile, create=False)
        if profile_path.exists():
            shutil.rmtree(profile_path)
    cmd_auth_authorize(args)


def cmd_auth_logout(args: argparse.Namespace) -> None:
    core.browser_action(args.profile, "https://chatgpt.com/", "ChatGPT account logout")
    path, data = core.global_config()
    current = core.platform_key()
    invalidated = _invalidate_profile_bindings(data, current, args.profile)
    data.setdefault("accounts", {}).setdefault(current, {}).pop(args.profile, None)
    data.setdefault("authenticated_profiles", {}).setdefault(current, {}).pop(args.profile, None)
    if data.setdefault("active_profiles", {}).get(current) == args.profile:
        data["active_profiles"].pop(current, None)
    core.save_global(path, data)
    print(f"Logged out/inactivated PowerPack ChatGPT profile '{args.profile}'.")
    if invalidated:
        print("Project bindings marked stale: " + ", ".join(sorted(set(invalidated))))


def cmd_auth_forget(args: argparse.Namespace) -> None:
    current = core.platform_key()
    profile_path = core.profile_dir(args.profile, create=False)
    if profile_path.exists():
        shutil.rmtree(profile_path)
    cfg_path, data = core.global_config()
    removed = _remove_profile_bindings(data, current, args.profile)
    data.setdefault("accounts", {}).setdefault(current, {}).pop(args.profile, None)
    data.setdefault("authenticated_profiles", {}).setdefault(current, {}).pop(args.profile, None)
    data.setdefault("authorizations", {}).setdefault(current, {}).pop(args.profile, None)
    if data.setdefault("active_profiles", {}).get(current) == args.profile:
        data["active_profiles"].pop(current, None)
    core.save_global(cfg_path, data)
    if getattr(args, "path", None):
        project = Path(args.path).resolve()
        try:
            review_path, review = _review_config(project)
        except core.PowerPackError:
            review_path = None
            review = {}
        web = review.get("chatgpt_web", {}) if isinstance(review, dict) else {}
        if isinstance(web, dict) and web.get("profile") == args.profile:
            for key in ("project_alias", "project_url", "project_name", "profile", "account_label", "profile_platform", "authorization"):
                web[key] = None
            if review_path:
                core.write_json(review_path, review, overwrite=True)
    print(f"Forgot isolated PowerPack ChatGPT profile '{args.profile}'.")
    if removed:
        print("Removed Project bindings: " + ", ".join(sorted(set(removed))))


def _profile_for(args: argparse.Namespace) -> str:
    if getattr(args, "profile", None):
        return args.profile
    _, data = core.global_config()
    profile = data.get("active_profiles", {}).get(core.platform_key())
    if not profile:
        raise core.PowerPackError("No active ChatGPT account profile. Use 'review auth authorize' or pass --profile.")
    return str(profile)


def _require_authorized_profile(profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, data = core.global_config()
    current = core.platform_key()
    record = _account_record(data, current, profile)
    if not _account_authorized(data, current, profile) or not record:
        raise core.PowerPackError(
            f"Profile '{profile}' is not authorized for ChatGPT Web review. "
            f"Run 'speckit-powerpack review auth authorize {profile}'."
        )
    return data, record


def _local_alias(name: str, url: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if base:
        return base[:60]
    return url.rstrip("/").split("/")[-2][:60]


def _persist_binding(*, alias: str, candidate: ProjectCandidate, profile: str, project_path: Path) -> None:
    cfg_path, data = core.global_config()
    current = core.platform_key()
    _, account = _require_authorized_profile(profile)
    registered = data.setdefault("projects", {}).setdefault(alias, {"bindings": {}})
    registered["display_name"] = candidate.name
    platform_bindings = registered.setdefault("bindings", {}).setdefault(current, {})
    if isinstance(platform_bindings, dict) and "url" in platform_bindings and "profile" in platform_bindings:
        legacy = dict(platform_bindings)
        legacy_profile = str(legacy.get("profile") or "legacy")
        registered["bindings"][current] = {legacy_profile: legacy}
        platform_bindings = registered["bindings"][current]
    platform_bindings[profile] = {
        "url": core.validate_project_url(candidate.url),
        "profile": profile,
        "account_label": account.get("account_label") or profile,
        "authorization": PROJECT_BINDING_AUTH,
    }
    data.setdefault("active_profiles", {})[current] = profile
    core.save_global(cfg_path, data)

    review_path, review = _review_config(project_path)
    web = review.setdefault("chatgpt_web", {})
    web["required"] = True
    web["enabled"] = True
    web["project_alias"] = alias
    web["project_url"] = candidate.url
    web["project_name"] = candidate.name
    web["profile"] = profile
    web["account_label"] = account.get("account_label") or profile
    web["profile_scope"] = "platform"
    web["profile_platform"] = current
    web["authorization"] = PROJECT_BINDING_AUTH
    core.write_json(review_path, review, overwrite=True)
    print(
        f"Bound repository to ChatGPT Project '{candidate.name}' as alias '{alias}' using reviewer account "
        f"'{account.get('account_label') or profile}' (profile '{profile}')."
    )


def _discover(profile: str) -> list[ProjectCandidate]:
    _require_authorized_profile(profile)
    try:
        return discover_chatgpt_projects(profile_dir=core.profile_dir(profile))
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc


def _manual_project(profile: str) -> ProjectCandidate:
    _require_authorized_profile(profile)
    try:
        return select_chatgpt_project_interactively(profile_dir=core.profile_dir(profile))
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc


def cmd_project_discover(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    projects = _discover(profile)
    if not projects:
        print("No Project links were discovered in the currently loaded ChatGPT sidebar for this account.")
        print("Use 'project select --manual', 'project add', or 'project accept-invite'.")
        return
    for index, item in enumerate(projects, start=1):
        print(f"{index:2}. {item.name} | {item.url}")


def _choose_project(projects: list[ProjectCandidate], index: int | None) -> ProjectCandidate:
    if not projects:
        raise core.PowerPackError("No ChatGPT Projects were discovered for the selected account profile.")
    if index is None:
        for number, item in enumerate(projects, start=1):
            print(f"{number:2}. {item.name} | {item.url}")
        value = input("Select Project number: ").strip()
        if not value.isdigit():
            raise core.PowerPackError("Project selection must be a number from the discovered list.")
        index = int(value)
    if index < 1 or index > len(projects):
        raise core.PowerPackError("Project selection index is out of range.")
    return projects[index - 1]


def cmd_project_select(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    if args.manual:
        candidate = _manual_project(profile)
    else:
        projects = _discover(profile)
        candidate = _choose_project(projects, args.index) if projects else _manual_project(profile)
    alias = args.alias or _local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def cmd_project_add(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    _require_authorized_profile(profile)
    if not is_chatgpt_project_url(args.url):
        raise core.PowerPackError("Expected a ChatGPT Project URL ending in /project.")
    try:
        candidate = open_link_and_capture_project(
            profile_dir=core.profile_dir(profile),
            url=args.url,
            purpose="ChatGPT Project verification",
        )
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    alias = args.alias or _local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def cmd_project_accept_invite(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    _require_authorized_profile(profile)
    try:
        candidate = open_link_and_capture_project(
            profile_dir=core.profile_dir(profile),
            url=args.url,
            purpose="ChatGPT Project invite/shared-link acceptance",
        )
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    alias = args.alias or _local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def _select_binding(registered: dict[str, Any], platform: str, requested_profile: str | None) -> tuple[str, dict[str, Any]]:
    bindings = _platform_bindings(registered, platform)
    if not bindings:
        raise core.PowerPackError("Project has no binding for the current platform.")
    if requested_profile:
        binding = bindings.get(requested_profile)
        if not binding:
            raise core.PowerPackError(
                f"Project is not registered for profile '{requested_profile}'. Available profiles: {', '.join(sorted(bindings))}"
            )
        return requested_profile, binding
    _, data = core.global_config()
    active = data.get("active_profiles", {}).get(platform)
    if active in bindings:
        return str(active), bindings[str(active)]
    if len(bindings) == 1:
        profile, binding = next(iter(bindings.items()))
        return profile, binding
    raise core.PowerPackError(
        "Project has multiple reviewer-account bindings. Pass --profile explicitly. Available: " + ", ".join(sorted(bindings))
    )


def cmd_project_use(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    _, data = core.global_config()
    current = core.platform_key()
    registered = data.get("projects", {}).get(args.alias)
    if not isinstance(registered, dict):
        raise core.PowerPackError(f"Unknown project alias: {args.alias}")
    profile, binding = _select_binding(registered, current, getattr(args, "profile", None))
    _require_authorized_profile(profile)
    if binding.get("authorization") != PROJECT_BINDING_AUTH:
        raise core.PowerPackError("This Project binding is stale/legacy; re-select/add it with the desired authorized account profile.")
    candidate = ProjectCandidate(name=registered.get("display_name") or args.alias, url=binding["url"])
    _persist_binding(alias=args.alias, candidate=candidate, profile=profile, project_path=project)


def cmd_project_list(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    current = core.platform_key()
    for alias, project in sorted(data.get("projects", {}).items()):
        if not isinstance(project, dict):
            continue
        platforms = project.get("bindings", {})
        platform_names = sorted(platforms) if args.all_platforms else [current]
        for platform_name in platform_names:
            for profile, binding in sorted(_platform_bindings(project, platform_name).items()):
                print(
                    f"{alias}: name={project.get('display_name') or alias} platform={platform_name} "
                    f"profile={profile} account={binding.get('account_label')} "
                    f"authorization={binding.get('authorization')} url={binding.get('url')}"
                )


def cmd_legacy_authorize_deprecated(args: argparse.Namespace) -> None:
    raise core.PowerPackError(
        "Project-scoped 'review authorize' is deprecated. Authorize the ChatGPT account first with "
        "'review auth authorize <profile>', then use 'review project select/add/accept-invite'."
    )


def cmd_legacy_project_bind_deprecated(args: argparse.Namespace) -> None:
    raise core.PowerPackError(
        "Legacy 'review project bind' is deprecated. Use 'review project select', 'project add', or 'project accept-invite' "
        "with an authorized account profile."
    )


def cmd_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    runtime = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    specify_binary = shutil.which("specify")
    current_spec_kit = core.specify_version(specify_binary) if specify_binary else None
    integration = core.project_integration(project)
    readiness = review_readiness(project)
    hard_checks = {
        "specify": bool(specify_binary),
        "spec-kit-compatible": core.spec_kit_compatible(current_spec_kit),
        "spec-kit-project": (project / ".specify").is_dir(),
        "powerpack-runtime": runtime.is_file(),
        "capability-resolver": runtime.with_name("capabilities.py").is_file(),
        "review-protocol-validator": runtime.with_name("review_protocol.py").is_file(),
        "technical-debt-runtime": runtime.with_name("debt.py").is_file(),
        "full-cycle-runtime": runtime.with_name("full_cycle.py").is_file(),
        "selected-executor": bool(shutil.which(integration)),
    }
    print(f"Platform:    {core.platform_key()} ({core.platform_module.system()})")
    print(f"Config:      {core.global_root()}")
    print(f"Integration: {integration}")
    print(f"Spec Kit:    {current_spec_kit or 'unknown'} (requires >= {core.SPECKIT_MIN_VERSION_TEXT})")
    for key, ok in hard_checks.items():
        print(f"{'OK' if ok else 'FAIL':5} {key}")
    for key, ok in readiness.items():
        print(f"{'OK' if ok else 'SETUP':5} {key}")
    if not all(hard_checks.values()):
        raise core.PowerPackError("PowerPack installation checks failed.")
    if args.strict_review and not all(readiness.values()):
        print_review_setup_status(project)
        raise core.PowerPackError("Mandatory ChatGPT Web review is not ready.")
    if not all(readiness.values()):
        print_review_setup_status(project)
        print("Installation is healthy; ChatGPT Web review onboarding is incomplete.")


def build_parser() -> argparse.ArgumentParser:
    parser = core.build_parser()
    root = _subparsers(parser)

    doctor = root.choices["doctor"]
    doctor.add_argument("--strict-review", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    review = root.choices["review"]
    rsub = _subparsers(review)
    rsub.choices["authorize"].set_defaults(func=cmd_legacy_authorize_deprecated)

    auth = rsub.choices["auth"]
    asub = _subparsers(auth)
    p = asub.add_parser("authorize", help="Authorize one isolated ChatGPT account profile")
    p.add_argument("profile")
    p.add_argument("--account-label")
    p.set_defaults(func=cmd_auth_authorize)
    p = asub.add_parser("list")
    p.set_defaults(func=cmd_auth_list)
    p = asub.add_parser("use")
    p.add_argument("profile")
    p.set_defaults(func=cmd_auth_use)
    p = asub.add_parser("reconfigure")
    p.add_argument("profile")
    p.add_argument("--account-label")
    p.add_argument("--fresh", action="store_true", help="Delete only this isolated PowerPack session before authorizing again")
    p.set_defaults(func=cmd_auth_reconfigure)
    asub.choices["logout"].set_defaults(func=cmd_auth_logout)
    forget_parser = asub.choices["forget"]
    forget_parser.add_argument("--path", default=".")
    forget_parser.set_defaults(func=cmd_auth_forget)

    project = rsub.choices["project"]
    psub = _subparsers(project)
    p = psub.add_parser("discover", help="Open ChatGPT and list Projects visible to the selected account")
    p.add_argument("--profile")
    p.set_defaults(func=cmd_project_discover)
    p = psub.add_parser("select", help="Discover and bind one accessible ChatGPT Project")
    p.add_argument("--profile")
    p.add_argument("--index", type=int)
    p.add_argument("--manual", action="store_true", help="Choose by navigating to a Project in the Playwright browser")
    p.add_argument("--alias")
    p.add_argument("--path", default=".")
    p.set_defaults(func=cmd_project_select)
    p = psub.add_parser("add", help="Verify and bind a known ChatGPT Project URL")
    p.add_argument("url")
    p.add_argument("--profile")
    p.add_argument("--alias")
    p.add_argument("--path", default=".")
    p.set_defaults(func=cmd_project_add)
    p = psub.add_parser("accept-invite", help="Open a ChatGPT invite/shared link and bind the resulting Project")
    p.add_argument("url")
    p.add_argument("--profile")
    p.add_argument("--alias")
    p.add_argument("--path", default=".")
    p.set_defaults(func=cmd_project_accept_invite)

    psub.choices["bind"].set_defaults(func=cmd_legacy_project_bind_deprecated)
    psub.choices["list"].set_defaults(func=cmd_project_list)
    use_parser = psub.choices["use"]
    use_parser.add_argument("--profile")
    use_parser.set_defaults(func=cmd_project_use)
    return parser


def main(argv: list[str] | None = None) -> int:
    core.review_readiness = review_readiness
    core.print_review_setup_status = print_review_setup_status
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


core.review_readiness = review_readiness
core.print_review_setup_status = print_review_setup_status
