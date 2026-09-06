from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import cli as core
from . import cli_account_binding as account_base
from . import cli_desktop_auth as desktop_auth
from . import cli_web_review as previous
from . import repository_context as repoctx
from . import browser_extension_transport
from . import windows_argv_transport


# Apply host-browser semantics after all CLI layers are imported. Extension
# mode is preferred for Edge/Chrome existing sessions; then replace the WSL ->
# Windows process bridge with argv-safe PowerShell transport so eval/run-code
# expressions are never re-parsed by cmd.exe.
browser_extension_transport.apply()
windows_argv_transport.apply()

# All command layers share this module object. Replacing the legacy worktree
# reader here moves subsequent reads/writes to the user-scoped repository state
# without duplicating each account/project command implementation.
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
    print(f"  reviewer profile: {web.get('profile') or 'NOT CONFIGURED'}")
    print(f"  reviewer account: {web.get('account_label') or 'NOT CONFIGURED'}")
    print(f"  browser: {web.get('automation_browser_id') or web.get('browser_channel') or 'NOT CONFIGURED'}")
    print(f"  browser host: {web.get('host_scope') or 'NOT CONFIGURED'}")
    print(f"  Project alias: {web.get('project_alias') or 'NOT CONFIGURED'}")
    print(f"  Project name: {web.get('project_name') or 'NOT CONFIGURED'}")
    print(f"  Project URL: {web.get('project_url') or 'NOT CONFIGURED'}")
    print(f"  authorization: {web.get('authorization') or 'NOT CONFIGURED'}")


def cmd_binding_path(args: argparse.Namespace) -> None:
    project = Path(args.path).expanduser().resolve()
    _prepare_repository_state(project)
    print(repoctx.repository_state_dir(project) / "review.json")


def build_parser() -> argparse.ArgumentParser:
    parser = previous.build_parser()
    root = account_base._subparsers(parser)
    review = root.choices["review"]
    rsub = account_base._subparsers(review)
    if "binding" not in rsub.choices:
        binding = rsub.add_parser("binding", help="Inspect the user-scoped repository-to-ChatGPT reviewer binding")
        bsub = binding.add_subparsers(dest="binding_command", required=True)
        show = bsub.add_parser("show", help="Show repository identity, reviewer account/browser and bound ChatGPT Project")
        show.add_argument("--path", default=".")
        show.add_argument("--json", action="store_true")
        show.set_defaults(func=cmd_binding_show)
        path = bsub.add_parser("path", help="Print the user-scoped binding file path")
        path.add_argument("--path", default=".")
        path.set_defaults(func=cmd_binding_path)
    return parser


def main(argv: list[str] | None = None) -> int:
    account_base._review_config = repoctx.review_config
    core.review_readiness = lambda project: desktop_auth.review_readiness(project)
    core.print_review_setup_status = desktop_auth.print_review_setup_status
    args = build_parser().parse_args(argv)
    project = _command_project(args)
    try:
        # Do this before configuration so legacy per-repository account/Project
        # fields are migrated before any new mutation. It is safe on non-Git dirs.
        _prepare_repository_state(project)
        args.func(args)
        # install/init may have created .specify during the command.
        _prepare_repository_state(project)
        return 0
    except (core.PowerPackError, core.UpdateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


account_base._review_config = repoctx.review_config
core.review_readiness = lambda project: desktop_auth.review_readiness(project)
core.print_review_setup_status = desktop_auth.print_review_setup_status
