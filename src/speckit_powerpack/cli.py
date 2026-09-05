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

SPECKIT_REPO = "https://github.com/github/spec-kit.git"
SPECKIT_TESTED_TAG = "v1.0.4"
DEFAULT_INTEGRATION = "claude"


class PowerPackError(RuntimeError):
    pass


def run(argv: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise PowerPackError((proc.stderr or proc.stdout or "command failed").strip())
    return proc


def asset(relative: str):
    return resources.as_file(resources.files("speckit_powerpack").joinpath("assets", relative))


def ensure_specify(install: bool) -> str:
    binary = shutil.which("specify")
    if binary:
        return binary
    if not install:
        raise PowerPackError("Official Spec Kit CLI ('specify') is not installed.")
    uv = shutil.which("uv")
    if not uv:
        raise PowerPackError("uv is required to bootstrap official Spec Kit.")
    run([uv, "tool", "install", "specify-cli", "--from", f"git+{SPECKIT_REPO}@{SPECKIT_TESTED_TAG}"])
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


def install_support(project: Path, integration: str) -> None:
    base = project / ".specify" / "powerpack"
    base.mkdir(parents=True, exist_ok=True)
    with asset("runtime/powerpack_runtime.py") as source:
        dest = base / "bin" / "powerpack.py"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        if os.name != "nt":
            dest.chmod(0o755)
    with asset("config/default-model-routing.json") as source:
        routing = json.loads(source.read_text(encoding="utf-8"))
    routing["active_integration"] = integration
    write_json(base / "model-routing.json", routing)
    with asset("config/default-review.json") as source:
        review = json.loads(source.read_text(encoding="utf-8"))
    write_json(base / "review.json", review)
    write_json(base / "prerequisites.json", {
        "schema_version": 1,
        "mode": "strict",
        "steps": {
            "checklist-converge": [{"step": "checklist", "statuses": ["COMPLETED"]}],
            "implement-review": [{"step": "implement", "statuses": ["COMPLETED"]}]
        }
    })
    write_json(base / "quality-gates.json", {
        "schema_version": 1,
        "policy": "auto-detect",
        "custom_command": None,
        "unknown_architecture": "block"
    })
    ignore = base / ".gitignore"
    if not ignore.exists():
        ignore.write_text("runtime/\nreviews.local.json\nauth/\n*.local.json\n", encoding="utf-8")


def install_components(project: Path, specify: str) -> None:
    with asset("extensions/powerpack-tools") as ext:
        run([specify, "extension", "add", str(ext), "--dev", "--force", "--priority", "5"], cwd=project)
    run([specify, "preset", "remove", "powerpack-core"], cwd=project, check=False)
    with asset("presets/powerpack-core") as preset:
        run([specify, "preset", "add", "--dev", str(preset), "--priority", "5"], cwd=project)


def install_powerpack(path: str, integration: str, *, initialize: bool, bootstrap: bool) -> None:
    project = Path(path).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    specify = ensure_specify(bootstrap)
    if initialize and not (project / ".specify").is_dir():
        run([specify, "init", "--here", "--integration", integration, "--force"], cwd=project)
    if not (project / ".specify").is_dir():
        raise PowerPackError("Target is not an initialized Spec Kit project.")
    install_support(project, integration)
    install_components(project, specify)


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
        if values.get("APPDATA"):
            return Path(values["APPDATA"]).expanduser()
        if values.get("LOCALAPPDATA"):
            return Path(values["LOCALAPPDATA"]).expanduser()
        return user_home / "AppData" / "Roaming"
    if current == "macos":
        return user_home / "Library" / "Application Support"
    return user_home / ".config"


def global_root() -> Path:
    root = default_config_base() / "speckit-powerpack"
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    return root


def global_config() -> tuple[Path, dict[str, Any]]:
    path = global_root() / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("active_profile", None)
    data.setdefault("projects", {})
    return path, data


def save_global(path: Path, data: dict[str, Any]) -> None:
    write_json(path, data, overwrite=True, mode=0o600)


def profile_dir(name: str) -> Path:
    if not name or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in name):
        raise PowerPackError("Profile names may contain only letters, digits, '-' and '_'.")
    path = global_root() / "browser-profiles" / name
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
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile_dir(profile)), headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        print(f"Browser opened for {purpose}. Enter credentials/MFA only in the browser.")
        input("Press Enter after completing the browser action: ")
        context.close()


def validate_project_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "www.chatgpt.com"} or not parsed.path.endswith("/project"):
        raise PowerPackError("Expected a ChatGPT Project URL: https://chatgpt.com/g/g-p-.../project")
    return url


def cmd_init(args: argparse.Namespace) -> None:
    install_powerpack(args.path, args.integration, initialize=True, bootstrap=True)
    print(f"SpecKit PowerPack draft {__version__} installed.")


def cmd_install(args: argparse.Namespace) -> None:
    install_powerpack(args.path, args.integration, initialize=False, bootstrap=args.bootstrap_speckit)
    print(f"SpecKit PowerPack draft {__version__} installed.")


def cmd_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    runtime = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    checks = {
        "specify": bool(shutil.which("specify")),
        "spec-kit-project": (project / ".specify").is_dir(),
        "powerpack-runtime": runtime.is_file(),
        "claude": bool(shutil.which("claude")),
        "codex": bool(shutil.which("codex")),
    }
    print(f"Platform: {platform_key()} ({platform_module.system()})")
    print(f"Config:   {global_root()}")
    for key, ok in checks.items():
        print(f"{'OK' if ok else 'FAIL':4} {key}")
    if not all(checks[name] for name in ("specify", "spec-kit-project", "powerpack-runtime")):
        raise PowerPackError("Required installation checks failed.")


def cmd_review_setup(args: argparse.Namespace) -> None:
    ensure_playwright()
    if args.install_browser:
        run([sys.executable, "-m", "playwright", "install", "chromium"])
    print("Playwright review dependencies are ready.")


def cmd_auth_login(args: argparse.Namespace) -> None:
    browser_action(args.profile, "https://chatgpt.com/", "ChatGPT login")
    path, data = global_config(); data["active_profile"] = args.profile; save_global(path, data)


def cmd_auth_logout(args: argparse.Namespace) -> None:
    browser_action(args.profile, "https://chatgpt.com/", "ChatGPT logout")


def cmd_auth_forget(args: argparse.Namespace) -> None:
    path = profile_dir(args.profile)
    if path.exists():
        shutil.rmtree(path)
    cfg_path, data = global_config()
    if data.get("active_profile") == args.profile:
        data["active_profile"] = None
    save_global(cfg_path, data)


def cmd_project_bind(args: argparse.Namespace) -> None:
    cfg_path, data = global_config()
    profile = args.profile or data.get("active_profile")
    if not profile:
        raise PowerPackError("Login/select a browser profile first.")
    data["projects"][args.alias] = {"url": validate_project_url(args.url), "profile": profile}
    save_global(cfg_path, data)


def cmd_project_use(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    _, global_data = global_config()
    if args.alias not in global_data.get("projects", {}):
        raise PowerPackError(f"Unknown project alias: {args.alias}")
    review_path = project / ".specify" / "powerpack" / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["chatgpt_web"]["enabled"] = True
    review["chatgpt_web"]["project_alias"] = args.alias
    write_json(review_path, review, overwrite=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="speckit-powerpack")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init"); p.add_argument("path", nargs="?", default="."); p.add_argument("--integration", default=DEFAULT_INTEGRATION); p.set_defaults(func=cmd_init)
    p = sub.add_parser("install"); p.add_argument("path", nargs="?", default="."); p.add_argument("--integration", default=DEFAULT_INTEGRATION); p.add_argument("--bootstrap-speckit", action="store_true"); p.set_defaults(func=cmd_install)
    p = sub.add_parser("doctor"); p.add_argument("path", nargs="?", default="."); p.set_defaults(func=cmd_doctor)
    review = sub.add_parser("review"); rsub = review.add_subparsers(dest="review_cmd", required=True)
    p = rsub.add_parser("setup"); p.add_argument("--install-browser", action="store_true"); p.set_defaults(func=cmd_review_setup)
    auth = rsub.add_parser("auth"); asub = auth.add_subparsers(dest="auth_cmd", required=True)
    p = asub.add_parser("login"); p.add_argument("profile"); p.set_defaults(func=cmd_auth_login)
    p = asub.add_parser("logout"); p.add_argument("profile"); p.set_defaults(func=cmd_auth_logout)
    p = asub.add_parser("forget"); p.add_argument("profile"); p.set_defaults(func=cmd_auth_forget)
    project = rsub.add_parser("project"); psub = project.add_subparsers(dest="project_cmd", required=True)
    p = psub.add_parser("bind"); p.add_argument("alias"); p.add_argument("url"); p.add_argument("--profile"); p.set_defaults(func=cmd_project_bind)
    p = psub.add_parser("use"); p.add_argument("alias"); p.add_argument("--path", default="."); p.set_defaults(func=cmd_project_use)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
        return 0
    except PowerPackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
