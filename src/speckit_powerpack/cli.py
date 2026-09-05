from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from . import __version__

SPECKIT_TESTED_TAG = "v1.0.4"
SPECKIT_REPO = "https://github.com/github/spec-kit.git"
DEFAULT_INTEGRATION = "claude"


class PowerPackError(RuntimeError):
    pass


def _run(argv: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise PowerPackError(f"Command failed ({' '.join(argv)}): {detail}")
    return proc


def _project_root(path: str | Path = ".") -> Path:
    return Path(path).expanduser().resolve()


def _asset_path(relative: str):
    return resources.as_file(resources.files("speckit_powerpack").joinpath("assets", relative))


def _ensure_uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise PowerPackError("uv is required to bootstrap the official Spec Kit. Install uv first: https://docs.astral.sh/uv/")
    return uv


def ensure_speckit(*, install_if_missing: bool = True, tag: str = SPECKIT_TESTED_TAG) -> str:
    specify = shutil.which("specify")
    if specify:
        return specify
    if not install_if_missing:
        raise PowerPackError("Official Spec Kit CLI ('specify') is not installed.")
    uv = _ensure_uv()
    _run([uv, "tool", "install", "specify-cli", "--from", f"git+{SPECKIT_REPO}@{tag}"])
    specify = shutil.which("specify")
    if not specify:
        raise PowerPackError("Spec Kit installation completed but 'specify' is not visible on PATH. Open a new shell or add the uv tool bin directory to PATH.")
    return specify


def _write_json(path: Path, data: Any, *, mode: int | None = None, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if mode is not None and os.name != "nt":
        path.chmod(mode)


def _copy_runtime(project: Path) -> None:
    destination = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _asset_path("runtime/powerpack_runtime.py") as source:
        shutil.copy2(source, destination)
    if os.name != "nt":
        destination.chmod(0o755)


def _install_support_files(project: Path, integration: str) -> None:
    root = project / ".specify" / "powerpack"
    root.mkdir(parents=True, exist_ok=True)

    with _asset_path("config/default-model-routing.json") as source:
        default_routing = json.loads(source.read_text(encoding="utf-8"))
    default_routing["active_integration"] = integration
    _write_json(root / "model-routing.json", default_routing, overwrite=False)

    with _asset_path("config/default-review.json") as source:
        review = json.loads(source.read_text(encoding="utf-8"))
    _write_json(root / "review.json", review, overwrite=False)

    prerequisites = {
        "schema_version": 1,
        "mode": "strict",
        "steps": {
            "checklist-converge": [{"step": "checklist", "statuses": ["COMPLETED"], "allow_artifact_evidence": True}],
            "tasks": [{"step": "checklist-converge", "statuses": ["CONVERGED"]}],
            "analyze": [{"step": "tasks", "statuses": ["COMPLETED"]}],
            "implement": [{"step": "analyze", "statuses": ["COMPLETED"]}],
            "converge": [{"step": "implement", "statuses": ["COMPLETED"]}],
            "implement-review": [
                {"step": "implement", "statuses": ["COMPLETED"]},
                {"step": "converge", "statuses": ["CONVERGED"]},
            ],
        },
    }
    _write_json(root / "prerequisites.json", prerequisites, overwrite=False)

    quality = {
        "schema_version": 1,
        "policy": "auto-detect",
        "skip_when": "documentation-only",
        "custom_command": None,
        "notes": "Set custom_command to an argv array when the project architecture cannot be detected safely.",
    }
    _write_json(root / "quality-gates.json", quality, overwrite=False)

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# Local PowerPack state that may contain browser/session references\nreviews.local.json\n*.local.json\nauth/\n", encoding="utf-8")

    (root / "VERSION").write_text(__version__ + "\n", encoding="utf-8")
    _copy_runtime(project)


def _install_components(project: Path, specify: str) -> None:
    with _asset_path("extensions/powerpack-tools") as extension_dir:
        _run([specify, "extension", "add", str(extension_dir), "--dev", "--force", "--priority", "5"], cwd=project)

    _run([specify, "preset", "remove", "powerpack-core"], cwd=project, check=False)
    with _asset_path("presets/powerpack-core") as preset_dir:
        _run([specify, "preset", "add", "--dev", str(preset_dir), "--priority", "5"], cwd=project)


def install_powerpack(project: Path, *, integration: str, bootstrap_speckit: bool, initialize: bool, speckit_tag: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    specify = ensure_speckit(install_if_missing=bootstrap_speckit, tag=speckit_tag)
    if initialize and not (project / ".specify").is_dir():
        _run([specify, "init", "--here", "--integration", integration, "--force"], cwd=project)
    if not (project / ".specify").is_dir():
        raise PowerPackError(f"{project} is not a Spec Kit project. Run 'speckit-powerpack init' or initialize it with the official 'specify init' first.")
    _install_support_files(project, integration)
    _install_components(project, specify)


def _global_config_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    root = base / "speckit-powerpack"
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    return root


def _global_config() -> tuple[Path, dict[str, Any]]:
    path = _global_config_root() / "config.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    data.setdefault("active_profile", None)
    data.setdefault("projects", {})
    return path, data


def _save_global_config(path: Path, data: dict[str, Any]) -> None:
    _write_json(path, data, mode=0o600)


def _profile_dir(profile: str, *, create: bool = True) -> Path:
    if not profile or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in profile):
        raise PowerPackError("Profile names may contain only letters, numbers, '-' and '_'.")
    path = _global_config_root() / "browser-profiles" / profile
    if create:
        path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)
    return path


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PowerPackError("Playwright Python package is unavailable. Reinstall speckit-powerpack with its declared dependencies.") from exc
    return sync_playwright


def _open_browser(profile: str, url: str, *, purpose: str) -> None:
    sync_playwright = _require_playwright()
    profile_dir = _profile_dir(profile)
    print(f"Opening browser profile '{profile}' for {purpose}.")
    print("Credentials, MFA codes and passkeys must be entered directly in the browser.")
    print("PowerPack does not read or store your password.")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        input("Complete the requested browser action, then press Enter here to close the browser: ")
        context.close()


def _validate_chatgpt_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "www.chatgpt.com"}:
        raise PowerPackError("ChatGPT project/conversation URLs must use https://chatgpt.com/.")
    return url


def _project_review_config(project: Path) -> tuple[Path, dict[str, Any]]:
    path = project / ".specify" / "powerpack" / "review.json"
    if not path.exists():
        raise PowerPackError("PowerPack is not installed in this project.")
    return path, json.loads(path.read_text(encoding="utf-8"))


def _local_review_registry(project: Path) -> tuple[Path, dict[str, Any]]:
    path = project / ".specify" / "powerpack" / "reviews.local.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    data.setdefault("pull_requests", {})
    return path, data


def cmd_init(args: argparse.Namespace) -> None:
    install_powerpack(_project_root(args.path), integration=args.integration, bootstrap_speckit=True, initialize=True, speckit_tag=args.speckit_tag)
    print(f"SpecKit PowerPack draft {__version__} installed.")


def cmd_install(args: argparse.Namespace) -> None:
    install_powerpack(_project_root(args.path), integration=args.integration, bootstrap_speckit=args.bootstrap_speckit, initialize=False, speckit_tag=args.speckit_tag)
    print(f"SpecKit PowerPack draft {__version__} installed.")


def cmd_update(args: argparse.Namespace) -> None:
    project = _project_root(args.path)
    specify = ensure_speckit(install_if_missing=False)
    if args.speckit:
        _run([specify, "self", "upgrade"], cwd=project)
    _install_support_files(project, args.integration)
    _install_components(project, specify)
    print(f"SpecKit PowerPack refreshed to {__version__}.")


def cmd_doctor(args: argparse.Namespace) -> None:
    project = _project_root(args.path)
    checks: list[tuple[str, bool, str]] = []
    specify = shutil.which("specify")
    checks.append(("Official Spec Kit", bool(specify), specify or "not found"))
    checks.append(("Spec Kit project", (project / ".specify").is_dir(), str(project / ".specify")))
    checks.append(("PowerPack runtime", (project / ".specify" / "powerpack" / "bin" / "powerpack.py").is_file(), ".specify/powerpack/bin/powerpack.py"))
    checks.append(("Model routing config", (project / ".specify" / "powerpack" / "model-routing.json").is_file(), ".specify/powerpack/model-routing.json"))
    if specify and (project / ".specify").is_dir():
        preset = _run([specify, "preset", "list"], cwd=project, check=False)
        extension = _run([specify, "extension", "list"], cwd=project, check=False)
        checks.append(("powerpack-core preset", "powerpack-core" in preset.stdout, "specify preset list"))
        checks.append(("powerpack-tools extension", "powerpack-tools" in extension.stdout, "specify extension list"))
    failed = False
    for name, ok, detail in checks:
        print(f"{'OK' if ok else 'FAIL':4}  {name:26} {detail}")
        failed |= not ok
    if failed:
        raise PowerPackError("Doctor found one or more failed checks.")


def cmd_review_setup(args: argparse.Namespace) -> None:
    if args.install_browser:
        _run([sys.executable, "-m", "playwright", "install", args.browser])
        print(f"Playwright browser '{args.browser}' installed.")
    else:
        print("Playwright package is installed with PowerPack.")
        print("Run with --install-browser to install the managed Chromium binary.")


def cmd_review_auth_login(args: argparse.Namespace) -> None:
    path, config = _global_config()
    _open_browser(args.profile, "https://chatgpt.com/", purpose="interactive ChatGPT login")
    config["active_profile"] = args.profile
    _save_global_config(path, config)
    print(f"Profile '{args.profile}' selected as active.")


def cmd_review_auth_logout(args: argparse.Namespace) -> None:
    _open_browser(args.profile, "https://chatgpt.com/", purpose="manual ChatGPT logout")
    print("Logout flow closed. Use 'auth forget' if you also want to delete the local browser profile.")


def cmd_review_auth_forget(args: argparse.Namespace) -> None:
    profile = _profile_dir(args.profile, create=False)
    if not profile.exists():
        raise PowerPackError(f"Profile '{args.profile}' does not exist.")
    if not args.yes:
        answer = input(f"Delete local browser profile '{args.profile}'? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return
    shutil.rmtree(profile, ignore_errors=True)
    path, config = _global_config()
    if config.get("active_profile") == args.profile:
        config["active_profile"] = None
    _save_global_config(path, config)
    print(f"Local profile '{args.profile}' removed.")


def cmd_review_auth_use(args: argparse.Namespace) -> None:
    profile = _profile_dir(args.profile, create=False)
    if not profile.exists():
        raise PowerPackError(f"Profile '{args.profile}' does not exist.")
    path, config = _global_config()
    config["active_profile"] = args.profile
    _save_global_config(path, config)
    print(f"Active browser profile: {args.profile}")


def cmd_review_auth_list(args: argparse.Namespace) -> None:
    _, config = _global_config()
    root = _global_config_root() / "browser-profiles"
    profiles = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
    for profile in profiles:
        marker = "*" if config.get("active_profile") == profile else " "
        print(f"{marker} {profile}")
    if not profiles:
        print("No browser profiles configured.")


def cmd_review_project_bind(args: argparse.Namespace) -> None:
    url = _validate_chatgpt_url(args.url)
    path, config = _global_config()
    profile = args.profile or config.get("active_profile")
    if not profile:
        raise PowerPackError("Choose a profile with 'review auth login/use' or pass --profile.")
    config["projects"][args.alias] = {"url": url, "profile": profile}
    _save_global_config(path, config)
    print(f"Bound project '{args.alias}' to profile '{profile}'.")


def cmd_review_project_list(args: argparse.Namespace) -> None:
    _, config = _global_config()
    for alias, item in sorted(config.get("projects", {}).items()):
        print(f"{alias}: profile={item.get('profile')} url={item.get('url')}")
    if not config.get("projects"):
        print("No ChatGPT projects bound.")


def cmd_review_project_unbind(args: argparse.Namespace) -> None:
    path, config = _global_config()
    config.get("projects", {}).pop(args.alias, None)
    _save_global_config(path, config)
    print(f"Project '{args.alias}' unbound.")


def cmd_review_project_use(args: argparse.Namespace) -> None:
    project = _project_root(args.path)
    _, global_config = _global_config()
    if args.alias not in global_config.get("projects", {}):
        raise PowerPackError(f"Unknown ChatGPT project alias '{args.alias}'.")
    path, review = _project_review_config(project)
    review["chatgpt_web"]["project_alias"] = args.alias
    review["chatgpt_web"]["enabled"] = True
    _write_json(path, review)
    print(f"Repository now references ChatGPT project '{args.alias}'.")


def _resolve_review_target(project: Path, pr: str | None = None) -> tuple[str, str]:
    _, global_config = _global_config()
    _, review = _project_review_config(project)
    alias = review.get("chatgpt_web", {}).get("project_alias")
    if not alias:
        raise PowerPackError("No ChatGPT project selected. Use 'review project use <alias>'.")
    item = global_config.get("projects", {}).get(alias)
    if not item:
        raise PowerPackError(f"Project alias '{alias}' is not present in the global configuration.")
    if pr is not None:
        _, registry = _local_review_registry(project)
        session = registry["pull_requests"].get(str(pr))
        if session and session.get("conversation_url"):
            return item["profile"], _validate_chatgpt_url(session["conversation_url"])
    return item["profile"], _validate_chatgpt_url(item["url"])


def cmd_review_session_bind(args: argparse.Namespace) -> None:
    project = _project_root(args.path)
    url = _validate_chatgpt_url(args.url)
    path, registry = _local_review_registry(project)
    registry["pull_requests"][str(args.pr)] = {"conversation_url": url}
    _write_json(path, registry, mode=0o600)
    print(f"PR #{args.pr} bound to its ChatGPT conversation locally.")


def cmd_review_session_open(args: argparse.Namespace) -> None:
    project = _project_root(args.path)
    profile, url = _resolve_review_target(project, str(args.pr))
    _open_browser(profile, url, purpose=f"assisted review session for PR #{args.pr}")


def cmd_review_doctor(args: argparse.Namespace) -> None:
    project = _project_root(args.path)
    checks = []
    try:
        sync_playwright = _require_playwright()
        with sync_playwright() as p:
            exe = Path(p.chromium.executable_path)
            checks.append(("Playwright Chromium", exe.exists(), str(exe)))
    except Exception as exc:
        checks.append(("Playwright Chromium", False, str(exc)))
    try:
        profile, url = _resolve_review_target(project)
        checks.append(("Active review profile", _profile_dir(profile, create=False).exists(), profile))
        checks.append(("ChatGPT project binding", True, url))
    except PowerPackError as exc:
        checks.append(("ChatGPT project binding", False, str(exc)))
    for name, ok, detail in checks:
        print(f"{'OK' if ok else 'FAIL':4}  {name:26} {detail}")
    if any(not ok for _, ok, _ in checks):
        raise PowerPackError("Review doctor found one or more failed checks.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="speckit-powerpack", description="Draft enhanced distribution layer for the official GitHub Spec Kit.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Install official Spec Kit, initialize a project, and apply PowerPack.")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--integration", default=DEFAULT_INTEGRATION)
    p.add_argument("--speckit-tag", default=SPECKIT_TESTED_TAG)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("install", help="Apply PowerPack to an existing Spec Kit project.")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--integration", default=DEFAULT_INTEGRATION)
    p.add_argument("--bootstrap-speckit", action="store_true")
    p.add_argument("--speckit-tag", default=SPECKIT_TESTED_TAG)
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("update", help="Refresh PowerPack components; optionally upgrade official Spec Kit.")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--integration", default=DEFAULT_INTEGRATION)
    p.add_argument("--speckit", action="store_true", help="Also run 'specify self upgrade'.")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("doctor", help="Validate a PowerPack installation.")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_doctor)

    review = sub.add_parser("review", help="Configure assisted code-review providers and sessions.")
    rsub = review.add_subparsers(dest="review_command", required=True)

    p = rsub.add_parser("setup")
    p.add_argument("--install-browser", action="store_true")
    p.add_argument("--browser", default="chromium", choices=["chromium"])
    p.set_defaults(func=cmd_review_setup)

    auth = rsub.add_parser("auth")
    asub = auth.add_subparsers(dest="auth_command", required=True)
    p = asub.add_parser("login"); p.add_argument("profile"); p.set_defaults(func=cmd_review_auth_login)
    p = asub.add_parser("logout"); p.add_argument("profile"); p.set_defaults(func=cmd_review_auth_logout)
    p = asub.add_parser("forget"); p.add_argument("profile"); p.add_argument("--yes", action="store_true"); p.set_defaults(func=cmd_review_auth_forget)
    p = asub.add_parser("use"); p.add_argument("profile"); p.set_defaults(func=cmd_review_auth_use)
    p = asub.add_parser("list"); p.set_defaults(func=cmd_review_auth_list)

    project = rsub.add_parser("project")
    psub = project.add_subparsers(dest="project_command", required=True)
    p = psub.add_parser("bind"); p.add_argument("alias"); p.add_argument("url"); p.add_argument("--profile"); p.set_defaults(func=cmd_review_project_bind)
    p = psub.add_parser("list"); p.set_defaults(func=cmd_review_project_list)
    p = psub.add_parser("unbind"); p.add_argument("alias"); p.set_defaults(func=cmd_review_project_unbind)
    p = psub.add_parser("use"); p.add_argument("alias"); p.add_argument("--path", default="."); p.set_defaults(func=cmd_review_project_use)

    session = rsub.add_parser("session")
    ssub = session.add_subparsers(dest="session_command", required=True)
    p = ssub.add_parser("bind"); p.add_argument("pr", type=int); p.add_argument("url"); p.add_argument("--path", default="."); p.set_defaults(func=cmd_review_session_bind)
    p = ssub.add_parser("open"); p.add_argument("pr", type=int); p.add_argument("--path", default="."); p.set_defaults(func=cmd_review_session_open)

    p = rsub.add_parser("doctor"); p.add_argument("--path", default="."); p.set_defaults(func=cmd_review_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except PowerPackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
