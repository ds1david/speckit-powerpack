from __future__ import annotations

import argparse
from importlib import resources
import json
import os
from pathlib import Path
import platform as platform_module
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .update_manager import UpdateError, apply_self_update, check_update

SPECKIT_REPO = "https://github.com/github/spec-kit.git"
SPECKIT_TESTED_TAG = "v1.0.4"
DEFAULT_INTEGRATION = "claude"


class PowerPackError(RuntimeError):
    pass


def run(argv: list[str], *, cwd: Path | None = None, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise PowerPackError((proc.stderr or proc.stdout or "command failed").strip())
    return proc


def asset(relative: str):
    return resources.as_file(resources.files("speckit_powerpack").joinpath("assets", relative))


def platform_key(system: str | None = None) -> str:
    value = (system or platform_module.system()).strip().lower()
    if value.startswith("win"):
        return "windows"
    if value in {"darwin", "mac", "macos"}:
        return "macos"
    if value == "linux":
        return "linux"
    return "other"


def default_config_base(*, system: str | None = None, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    values = env if env is not None else os.environ
    user_home = home or Path.home()
    if values.get("XDG_CONFIG_HOME"):
        return Path(values["XDG_CONFIG_HOME"]).expanduser()
    current = platform_key(system)
    if current == "windows":
        return Path(values.get("APPDATA") or values.get("LOCALAPPDATA") or (user_home / "AppData" / "Roaming")).expanduser()
    if current == "macos":
        return user_home / "Library" / "Application Support"
    return user_home / ".config"


def ensure_specify(install: bool) -> str:
    binary = shutil.which("specify")
    if binary:
        return binary
    if not install:
        raise PowerPackError("Official Spec Kit CLI ('specify') is not installed.")
    uv = shutil.which("uv")
    if not uv:
        raise PowerPackError("uv is required to bootstrap official Spec Kit.")
    # uv tool install accepts a Git source directly as PACKAGE.
    run([uv, "tool", "install", f"git+{SPECKIT_REPO}@{SPECKIT_TESTED_TAG}"])
    binary = shutil.which("specify")
    if not binary:
        raise PowerPackError("Spec Kit was installed but 'specify' is not visible on PATH yet.")
    return binary


def write_json(path: Path, data: Any, *, overwrite: bool = False, mode: int | None = None) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if mode is not None and os.name != "nt":
        path.chmod(mode)


def read_asset_json(relative: str) -> dict[str, Any]:
    with asset(relative) as source:
        value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PowerPackError(f"Packaged config {relative} must contain an object.")
    return value


def install_support(project: Path, integration: str, *, overwrite_config: bool = False) -> None:
    base = project / ".specify" / "powerpack"
    bin_dir = base / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    runtime_assets = {
        "runtime/powerpack_runtime.py": "powerpack.py",
        "runtime/powerpack_capabilities.py": "capabilities.py",
        "runtime/powerpack_review_protocol.py": "review_protocol.py",
        "runtime/powerpack_debt.py": "debt.py",
        "runtime/powerpack_full_cycle.py": "full_cycle.py",
    }
    for source_name, dest_name in runtime_assets.items():
        with asset(source_name) as source:
            dest = bin_dir / dest_name
            shutil.copy2(source, dest)
            if os.name != "nt":
                dest.chmod(0o755)
    with asset("review/deep-review-protocol.md") as source:
        shutil.copy2(source, base / "deep-review-protocol.md")
    with asset("policies/technical-debt.md") as source:
        shutil.copy2(source, base / "technical-debt-policy.md")
    with asset("templates/technical-debt-backlog.md") as source:
        shutil.copy2(source, base / "technical-debt-template.md")

    routing = read_asset_json("config/default-model-routing.json")
    routing["active_integration"] = integration
    write_json(base / "model-routing.json", routing, overwrite=overwrite_config)
    write_json(base / "review.json", read_asset_json("config/default-review.json"), overwrite=overwrite_config)
    write_json(base / "technical-debt.json", read_asset_json("config/default-technical-debt.json"), overwrite=overwrite_config)
    write_json(base / "full-cycle.json", read_asset_json("config/default-full-cycle.json"), overwrite=overwrite_config)
    write_json(base / "update.json", read_asset_json("config/default-update.json"), overwrite=overwrite_config)
    write_json(base / "prerequisites.json", {
        "schema_version": 1,
        "mode": "strict",
        "steps": {
            "checklist-converge": [{"step": "checklist", "statuses": ["COMPLETED"]}],
            "implement-review": [{"step": "implement", "statuses": ["COMPLETED"]}],
        },
    }, overwrite=overwrite_config)
    write_json(base / "quality-gates.json", {
        "schema_version": 1,
        "policy": "capability-strategy",
        "custom_command": None,
        "unknown_architecture": "block",
        "ambiguous_architecture": "block",
    }, overwrite=overwrite_config)
    ignore = base / ".gitignore"
    if not ignore.exists():
        ignore.write_text("runtime/\nreviews.local.json\nauth/\n*.local.json\n", encoding="utf-8")


def install_components(project: Path, specify: str) -> None:
    with asset("extensions/powerpack-tools") as ext:
        run([specify, "extension", "add", str(ext), "--dev", "--force", "--priority", "5"], cwd=project)
    run([specify, "preset", "remove", "powerpack-core"], cwd=project, check=False)
    with asset("presets/powerpack-core") as preset:
        run([specify, "preset", "add", "--dev", str(preset), "--priority", "5"], cwd=project)


def install_powerpack(path: str, integration: str, *, initialize: bool, bootstrap: bool, overwrite_config: bool = False) -> None:
    project = Path(path).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    specify = ensure_specify(bootstrap)
    if initialize and not (project / ".specify").is_dir():
        run([specify, "init", "--here", "--integration", integration, "--force"], cwd=project)
    if not (project / ".specify").is_dir():
        raise PowerPackError("Target is not an initialized Spec Kit project.")
    install_support(project, integration, overwrite_config=overwrite_config)
    install_components(project, specify)


def global_root() -> Path:
    root = default_config_base() / "speckit-powerpack"
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    return root


def _migrate_global_config(data: dict[str, Any], *, current_platform: str) -> dict[str, Any]:
    data.setdefault("schema_version", 2)
    active_profiles = data.setdefault("active_profiles", {})
    legacy_active = data.pop("active_profile", None)
    if legacy_active and current_platform not in active_profiles:
        active_profiles[current_platform] = legacy_active

    projects = data.setdefault("projects", {})
    for alias, value in list(projects.items()):
        if not isinstance(value, dict):
            continue
        if "bindings" in value:
            value.setdefault("bindings", {})
            continue
        if value.get("url") and value.get("profile"):
            projects[alias] = {
                "bindings": {
                    current_platform: {
                        "url": value["url"],
                        "profile": value["profile"],
                    }
                }
            }
    return data


def global_config() -> tuple[Path, dict[str, Any]]:
    path = global_root() / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return path, _migrate_global_config(data, current_platform=platform_key())


def save_global(path: Path, data: dict[str, Any]) -> None:
    write_json(path, data, overwrite=True, mode=0o600)


def profile_dir(name: str, *, system: str | None = None, create: bool = True) -> Path:
    if not name or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in name):
        raise PowerPackError("Profile names may contain only letters, digits, '-' and '_'.")
    namespace = platform_key(system)
    path = global_root() / "browser-profiles" / namespace / name
    if create:
        path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)
    return path


def ensure_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "playwright>=1.55,<2"])


def browser_action(profile: str, url: str, purpose: str) -> None:
    ensure_playwright()
    from playwright.sync_api import sync_playwright
    current = platform_key()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile_dir(profile)), headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        print(f"Browser opened for {purpose} using {current} profile '{profile}'. Enter credentials/MFA only in the browser.")
        input("Press Enter after completing the browser action: ")
        context.close()


def validate_project_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "www.chatgpt.com"} or not parsed.path.endswith("/project"):
        raise PowerPackError("Expected a ChatGPT Project URL: https://chatgpt.com/g/g-p-.../project")
    return url


def project_update_config(path: str | Path) -> dict[str, Any]:
    project = Path(path).expanduser().resolve()
    candidate = project / ".specify" / "powerpack" / "update.json"
    if candidate.is_file():
        data = json.loads(candidate.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else read_asset_json("config/default-update.json")
    return read_asset_json("config/default-update.json")


def project_integration(path: str | Path, fallback: str = DEFAULT_INTEGRATION) -> str:
    candidate = Path(path).expanduser().resolve() / ".specify" / "powerpack" / "model-routing.json"
    if candidate.is_file():
        try:
            value = json.loads(candidate.read_text(encoding="utf-8")).get("active_integration")
        except (OSError, json.JSONDecodeError):
            value = None
        if value in {"claude", "codex"}:
            return value
    return fallback


def confirm_update(prompt: str, *, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(f"{prompt} [y/N]: ").strip().casefold()
    return answer in {"y", "yes", "s", "sim"}


def check_update_safe(config: dict[str, Any]) -> dict[str, Any]:
    try:
        return check_update(config)
    except UpdateError as exc:
        return {"status": "CHECK_FAILED", "error": str(exc)}


def rerun_after_self_update(command: str, args: argparse.Namespace) -> None:
    binary = shutil.which("speckit-powerpack")
    if not binary:
        raise PowerPackError("PowerPack was updated but the executable is not visible on PATH.")
    argv = [binary, command, args.path, "--integration", args.integration, "--no-update-check"]
    if command == "install" and getattr(args, "bootstrap_speckit", False):
        argv.append("--bootstrap-speckit")
    env = dict(os.environ)
    env["SPECKIT_POWERPACK_SKIP_UPDATE_CHECK"] = "1"
    proc = subprocess.run(argv, text=True, env=env)
    raise SystemExit(proc.returncode)


def maybe_auto_update(command: str, args: argparse.Namespace) -> None:
    if getattr(args, "no_update_check", False) or os.environ.get("SPECKIT_POWERPACK_SKIP_UPDATE_CHECK") == "1":
        return
    cfg = project_update_config(args.path)
    if not cfg.get("enabled", True) or not cfg.get("auto_check_on_install", True):
        return
    result = check_update_safe(cfg)
    if result.get("status") == "CHECK_FAILED":
        print(f"Update check skipped: {result.get('error')}", file=sys.stderr)
        return
    if result.get("status") != "UPDATE_AVAILABLE":
        return
    print(f"PowerPack update available: {str(result.get('installed_commit'))[:12]} -> {str(result.get('remote_commit'))[:12]} ({result.get('ref')})")
    if not confirm_update("Update PowerPack before continuing installation?", assume_yes=getattr(args, "yes_update", False)):
        print("Continuing with the currently installed PowerPack.")
        return
    apply_self_update(str(result["repository"]), str(result["ref"]))
    rerun_after_self_update(command, args)


def cmd_init(args: argparse.Namespace) -> None:
    maybe_auto_update("init", args)
    install_powerpack(args.path, args.integration, initialize=True, bootstrap=True)
    print(f"SpecKit PowerPack draft {__version__} installed.")


def cmd_install(args: argparse.Namespace) -> None:
    maybe_auto_update("install", args)
    install_powerpack(args.path, args.integration, initialize=False, bootstrap=args.bootstrap_speckit)
    print(f"SpecKit PowerPack draft {__version__} installed.")


def cmd_update(args: argparse.Namespace) -> None:
    project = Path(args.path).expanduser().resolve()
    cfg = project_update_config(project)
    if args.repository:
        cfg["repository"] = args.repository
    if args.ref:
        cfg["ref"] = args.ref
    result = check_update_safe(cfg)
    if args.check:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("status") == "CHECK_FAILED" and not args.force:
        raise PowerPackError(f"Update check failed: {result.get('error')}. Use --force only when you intentionally want a blind reinstall.")
    if result.get("status") == "CURRENT" and not args.force and not args.project_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("status") == "UNKNOWN_INSTALLED_SOURCE" and not args.force and not args.project_only:
        raise PowerPackError("Cannot prove the installed Git commit. Use --force for an explicit reinstall or --project-only to rematerialize this installed package.")
    if args.reset_config and not args.force:
        raise PowerPackError("--reset-config requires --force.")
    if args.reset_config and not args.yes:
        raise PowerPackError("--reset-config requires explicit --yes confirmation.")

    repository = str(result.get("repository") or cfg.get("repository") or "https://github.com/ds1david/speckit-powerpack.git")
    ref = str(result.get("ref") or cfg.get("ref") or "main")
    action = "FORCE reinstall" if args.force else "update"
    if not confirm_update(f"Confirm PowerPack {action} from {repository}@{ref} and refresh managed project assets?", assume_yes=args.yes):
        raise PowerPackError("Update cancelled. In non-interactive mode pass --yes explicitly.")

    integration = args.integration or project_integration(project)
    if args.project_only:
        install_powerpack(str(project), integration, initialize=False, bootstrap=args.bootstrap_speckit, overwrite_config=args.reset_config)
        print(json.dumps({"status": "PROJECT_REFRESHED", "path": str(project), "force": args.force, "config_reset": args.reset_config}))
        return

    applied = apply_self_update(repository, ref)
    project_refreshed = False
    if cfg.get("project_refresh", True) and (project / ".specify").is_dir():
        binary = shutil.which("speckit-powerpack")
        if not binary:
            raise PowerPackError("CLI update succeeded but updated executable is not visible on PATH.")
        argv = [
            binary,
            "update",
            str(project),
            "--project-only",
            "--force",
            "--yes",
            "--integration",
            integration,
        ]
        if args.bootstrap_speckit:
            argv.append("--bootstrap-speckit")
        if args.reset_config:
            argv.append("--reset-config")
        env = dict(os.environ)
        env["SPECKIT_POWERPACK_SKIP_UPDATE_CHECK"] = "1"
        proc = subprocess.run(argv, text=True, env=env)
        if proc.returncode != 0:
            raise PowerPackError("CLI updated, but project refresh failed; rerun 'speckit-powerpack update . --project-only --force --yes' manually.")
        project_refreshed = True
    print(json.dumps({**applied, "project_refreshed": project_refreshed}, ensure_ascii=False, indent=2))


def cmd_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    runtime = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    capabilities = runtime.with_name("capabilities.py")
    review_protocol = runtime.with_name("review_protocol.py")
    debt_runtime = runtime.with_name("debt.py")
    cycle_runtime = runtime.with_name("full_cycle.py")
    checks = {
        "specify": bool(shutil.which("specify")),
        "spec-kit-project": (project / ".specify").is_dir(),
        "powerpack-runtime": runtime.is_file(),
        "capability-resolver": capabilities.is_file(),
        "review-protocol-validator": review_protocol.is_file(),
        "technical-debt-runtime": debt_runtime.is_file(),
        "full-cycle-runtime": cycle_runtime.is_file(),
        "claude": bool(shutil.which("claude")),
        "codex": bool(shutil.which("codex")),
    }
    print(f"Platform: {platform_key()} ({platform_module.system()})")
    print(f"Config:   {global_root()}")
    for key, ok in checks.items():
        print(f"{'OK' if ok else 'FAIL':4} {key}")
    required = (
        "specify", "spec-kit-project", "powerpack-runtime", "capability-resolver",
        "review-protocol-validator", "technical-debt-runtime", "full-cycle-runtime",
    )
    if not all(checks[name] for name in required):
        raise PowerPackError("Required installation checks failed.")


def cmd_review_setup(args: argparse.Namespace) -> None:
    ensure_playwright()
    if args.install_browser:
        run([sys.executable, "-m", "playwright", "install", "chromium"])
    print("Playwright review dependencies are ready.")


def cmd_auth_login(args: argparse.Namespace) -> None:
    browser_action(args.profile, "https://chatgpt.com/", "ChatGPT login")
    path, data = global_config()
    data.setdefault("active_profiles", {})[platform_key()] = args.profile
    save_global(path, data)


def cmd_auth_logout(args: argparse.Namespace) -> None:
    browser_action(args.profile, "https://chatgpt.com/", "ChatGPT logout")


def cmd_auth_forget(args: argparse.Namespace) -> None:
    current = platform_key()
    path = profile_dir(args.profile, create=False)
    if path.exists():
        shutil.rmtree(path)
    cfg_path, data = global_config()
    if data.setdefault("active_profiles", {}).get(current) == args.profile:
        data["active_profiles"].pop(current, None)
    save_global(cfg_path, data)


def cmd_project_bind(args: argparse.Namespace) -> None:
    cfg_path, data = global_config()
    current = platform_key()
    profile = args.profile or data.setdefault("active_profiles", {}).get(current)
    if not profile:
        raise PowerPackError(f"Login/select a browser profile for platform '{current}' first.")
    project = data.setdefault("projects", {}).setdefault(args.alias, {"bindings": {}})
    bindings = project.setdefault("bindings", {})
    bindings[current] = {"url": validate_project_url(args.url), "profile": profile}
    save_global(cfg_path, data)
    print(f"Bound project '{args.alias}' on {current} to profile '{profile}'.")


def cmd_project_list(args: argparse.Namespace) -> None:
    _, data = global_config()
    current = platform_key()
    for alias, project in sorted(data.get("projects", {}).items()):
        bindings = project.get("bindings", {}) if isinstance(project, dict) else {}
        if args.all_platforms:
            for platform_name, binding in sorted(bindings.items()):
                print(f"{alias}: platform={platform_name} profile={binding.get('profile')} url={binding.get('url')}")
        elif current in bindings:
            binding = bindings[current]
            print(f"{alias}: platform={current} profile={binding.get('profile')} url={binding.get('url')}")


def cmd_project_use(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    _, global_data = global_config()
    current = platform_key()
    registered = global_data.get("projects", {}).get(args.alias)
    if not isinstance(registered, dict):
        raise PowerPackError(f"Unknown project alias: {args.alias}")
    binding = registered.get("bindings", {}).get(current)
    if not binding:
        raise PowerPackError(f"Project alias '{args.alias}' has no ChatGPT binding for platform '{current}'. Bind it on this platform first.")
    review_path = project / ".specify" / "powerpack" / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    web = review.setdefault("chatgpt_web", {})
    web["enabled"] = True
    web["project_alias"] = args.alias
    web["project_url"] = binding["url"]
    web["profile"] = binding["profile"]
    web["profile_scope"] = "platform"
    web["profile_platform"] = current
    write_json(review_path, review, overwrite=True)


def add_install_update_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-update-check", action="store_true")
    parser.add_argument("--yes-update", action="store_true", help="Confirm an installer-triggered CLI update non-interactively")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="speckit-powerpack")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("path", nargs="?", default="."); p.add_argument("--integration", default=DEFAULT_INTEGRATION); add_install_update_flags(p); p.set_defaults(func=cmd_init)
    p = sub.add_parser("install")
    p.add_argument("path", nargs="?", default="."); p.add_argument("--integration", default=DEFAULT_INTEGRATION); p.add_argument("--bootstrap-speckit", action="store_true"); add_install_update_flags(p); p.set_defaults(func=cmd_install)
    p = sub.add_parser("update")
    p.add_argument("path", nargs="?", default="."); p.add_argument("--check", action="store_true"); p.add_argument("--yes", action="store_true"); p.add_argument("--force", action="store_true"); p.add_argument("--project-only", action="store_true"); p.add_argument("--reset-config", action="store_true"); p.add_argument("--repository"); p.add_argument("--ref"); p.add_argument("--integration", choices=["claude", "codex"]); p.add_argument("--bootstrap-speckit", action="store_true"); p.set_defaults(func=cmd_update)
    p = sub.add_parser("doctor"); p.add_argument("path", nargs="?", default="."); p.set_defaults(func=cmd_doctor)

    review = sub.add_parser("review"); rsub = review.add_subparsers(dest="review_cmd", required=True)
    p = rsub.add_parser("setup"); p.add_argument("--install-browser", action="store_true"); p.set_defaults(func=cmd_review_setup)
    auth = rsub.add_parser("auth"); asub = auth.add_subparsers(dest="auth_cmd", required=True)
    p = asub.add_parser("login"); p.add_argument("profile"); p.set_defaults(func=cmd_auth_login)
    p = asub.add_parser("logout"); p.add_argument("profile"); p.set_defaults(func=cmd_auth_logout)
    p = asub.add_parser("forget"); p.add_argument("profile"); p.set_defaults(func=cmd_auth_forget)
    project = rsub.add_parser("project"); psub = project.add_subparsers(dest="project_cmd", required=True)
    p = psub.add_parser("bind"); p.add_argument("alias"); p.add_argument("url"); p.add_argument("--profile"); p.set_defaults(func=cmd_project_bind)
    p = psub.add_parser("list"); p.add_argument("--all-platforms", action="store_true"); p.set_defaults(func=cmd_project_list)
    p = psub.add_parser("use"); p.add_argument("alias"); p.add_argument("--path", default="."); p.set_defaults(func=cmd_project_use)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
        return 0
    except (PowerPackError, UpdateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
