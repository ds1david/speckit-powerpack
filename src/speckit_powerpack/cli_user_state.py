from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import cli as core
from . import cli_account_binding as account_base
from . import cli_web_review as previous
from . import cli_web2api_review as web2api
from . import repository_context as repoctx


# Personal reviewer/account/Project state is resolved outside the repository.
# Browser automation is delegated to ChatGPT-Web2API; the PowerPack talks only
# to its localhost REST contract and therefore does not own Playwright/CDP/UI
# selectors in the functional review path.
account_base._review_config = repoctx.review_config


def _command_project(args: argparse.Namespace) -> Path:
    raw = getattr(args, "path", None)
    return Path(raw or ".").expanduser().resolve()


def _prepare_repository_state(project: Path) -> None:
    repoctx.ensure_local_git_excludes(project)
    repoctx.migrate_versioned_local_binding(project)


def cmd_binding_show(args: argparse.Namespace) -> None:
    project = Path(args.path).expanduser().resolve()
    _prepare_repository_state(project)
    data = repoctx.describe_binding(project)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    repository = data["repository"]
    web = data.get("chatgpt_web") or {}
    print("\nPOWERPACK WEB REVIEW BINDING")
    print(f"  repository provider: {repository.get('provider')}")
    print(f"  repository identity: {repository.get('canonical')}")
    print(f"  remote: {repository.get('remote_name') or 'none'} -> {repository.get('remote_url') or 'local-only'}")
    print(f"  portable identity: {'yes' if repository.get('portable') else 'no (local path fallback)'}")
    print(f"  user-scoped config: {data.get('user_config')}")
    print("  worktree binding file: none")
    print(f"  reviewer backend: {web.get('backend') or web.get('account_backend') or 'NOT CONFIGURED'}")
    print(f"  reviewer profile: {web.get('profile') or 'NOT CONFIGURED'}")
    print(f"  reviewer account: {web.get('account_label') or 'NOT CONFIGURED'}")
    print(f"  reviewer endpoint: {web.get('endpoint') or 'NOT CONFIGURED'}")
    print(f"  Project alias: {web.get('project_alias') or 'NOT CONFIGURED'}")
    print(f"  Project name: {web.get('project_name') or 'NOT CONFIGURED'}")
    print(f"  Project id: {web.get('project_id') or 'NOT CONFIGURED'}")
    print(f"  Project URL: {web.get('project_url') or 'NOT CONFIGURED'}")
    print(f"  authorization: {web.get('authorization') or 'NOT CONFIGURED'}")


def cmd_binding_path(args: argparse.Namespace) -> None:
    project = Path(args.path).expanduser().resolve()
    _prepare_repository_state(project)
    print(repoctx.repository_state_dir(project) / "review.json")


def _wire_web2api_commands(parser: argparse.ArgumentParser) -> None:
    root = account_base._subparsers(parser)

    doctor = root.choices["doctor"]
    doctor.set_defaults(func=web2api.cmd_doctor)

    review = root.choices["review"]
    rsub = account_base._subparsers(review)

    auth = rsub.choices["auth"]
    asub = account_base._subparsers(auth)
    for name, func in {
        "configure": web2api.cmd_auth_configure,
        "reconfigure": web2api.cmd_auth_configure,
        "list": web2api.cmd_auth_list,
        "validate": web2api.cmd_auth_validate,
        "use": web2api.cmd_auth_use,
        "logout": web2api.cmd_auth_logout,
    }.items():
        if name in asub.choices:
            asub.choices[name].set_defaults(func=func)

    project = rsub.choices["project"]
    psub = account_base._subparsers(project)
    for name, func in {
        "discover": web2api.cmd_project_discover,
        "select": web2api.cmd_project_select,
        "add": web2api.cmd_project_add,
        "accept-invite": web2api.cmd_project_add,
        "use": web2api.cmd_project_use,
        "list": web2api.cmd_project_list,
    }.items():
        if name in psub.choices:
            psub.choices[name].set_defaults(func=func)

    if "smoke-test" in rsub.choices:
        rsub.choices["smoke-test"].set_defaults(func=web2api.cmd_review_smoke_test)

    if "service" not in rsub.choices:
        service = rsub.add_parser("service", help="Manage the dedicated ChatGPT-Web2API reviewer service")
        ssub = service.add_subparsers(dest="service_command", required=True)
        start = ssub.add_parser("start", help="Install/start one headed reviewer service and dedicated Chrome profile")
        start.add_argument("--profile", default=None)
        start.add_argument("--port", type=int, default=8080)
        start.add_argument("--cdp-port", type=int, default=9222)
        start.add_argument("--timeout", type=int, default=45)
        start.add_argument("--no-install", action="store_true", help="Require an existing ChatGPT-Web2API installation")
        start.set_defaults(func=web2api.cmd_service_start)
        status = ssub.add_parser("status", help="Show live reviewer service health")
        status.add_argument("--endpoint", default=None)
        status.add_argument("--timeout", type=int, default=10)
        status.set_defaults(func=web2api.cmd_service_status)

    if "run" not in rsub.choices:
        run = rsub.add_parser("run", help="Send one prompt to the repository's bound ChatGPT Project reviewer")
        run.add_argument("--path", default=".")
        source = run.add_mutually_exclusive_group(required=True)
        source.add_argument("--prompt")
        source.add_argument("--prompt-file")
        run.add_argument("--model", default=None)
        run.add_argument("--timeout", type=int, default=180)
        run.add_argument("--output", help="Write only the assistant response to this file")
        run.add_argument("--json", action="store_true")
        run.set_defaults(func=web2api.cmd_review_run)


def build_parser() -> argparse.ArgumentParser:
    parser = previous.build_parser()
    root = account_base._subparsers(parser)
    review = root.choices["review"]
    rsub = account_base._subparsers(review)
    if "binding" not in rsub.choices:
        binding = rsub.add_parser("binding", help="Inspect the user-scoped repository-to-ChatGPT reviewer binding")
        bsub = binding.add_subparsers(dest="binding_command", required=True)
        show = bsub.add_parser("show", help="Show repository identity, reviewer endpoint/account and bound ChatGPT Project")
        show.add_argument("--path", default=".")
        show.add_argument("--json", action="store_true")
        show.set_defaults(func=cmd_binding_show)
        path = bsub.add_parser("path", help="Print the user-scoped binding file path")
        path.add_argument("--path", default=".")
        path.set_defaults(func=cmd_binding_path)
    _wire_web2api_commands(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    account_base._review_config = repoctx.review_config
    core.review_readiness = lambda project: web2api.review_readiness(project)
    core.print_review_setup_status = web2api.print_review_setup_status
    args = build_parser().parse_args(argv)
    project = _command_project(args)
    try:
        _prepare_repository_state(project)
        args.func(args)
        _prepare_repository_state(project)
        return 0
    except (core.PowerPackError, core.UpdateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


account_base._review_config = repoctx.review_config
core.review_readiness = lambda project: web2api.review_readiness(project)
core.print_review_setup_status = web2api.print_review_setup_status
