from __future__ import annotations

import argparse
import importlib.resources as resources
import json
import os
import platform as platform_module
from pathlib import Path
import shutil
import subprocess
import sys
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse

from .review_onboarding import ProjectCandidate, discover_chatgpt_projects, select_chatgpt_project_interactively
from .update_manager import UpdateError, maybe_check_for_updates


SPECKIT_MIN_VERSION = (1, 0, 0)
SPECKIT_MIN_VERSION_TEXT = "1.0.0"


class PowerPackError(RuntimeError):
    pass


def global_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "speckit-powerpack"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "speckit-powerpack"


def platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return sys.platform


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.is_file():
        return dict(default or {})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PowerPackError(f"Cannot read JSON config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PowerPackError(f"JSON config {path} must contain an object.")
    return value


def write_json(path: Path, value: dict, *, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@contextmanager
def asset(name: str) -> Iterator[Path]:
    target = resources.files("speckit_powerpack.assets").joinpath(name)
    with resources.as_file(target) as path:
        yield path


def read_asset_json(name: str) -> dict:
    with asset(name) as path:
        return read_json(path)


def global_config() -> tuple[Path, dict]:
    path = global_root() / "config.json"
    value = read_json(path, {"schema_version": 1})
    return path, value


def save_global(path: Path, value: dict) -> None:
    write_json(path, value, overwrite=True)
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def profile_dir(profile: str, *, create: bool = True) -> Path:
    path = global_root() / "browser-profiles" / platform_key() / profile
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def parse_version(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    import re

    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def specify_version(binary: str | None) -> str | None:
    if not binary:
        return None
    for argv in ([binary, "--version"], [binary, "version"]):
        try:
            proc = subprocess.run(argv, text=True, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            text = (proc.stdout or proc.stderr or "").strip()
            if text:
                return text
    return None


def spec_kit_compatible(version_text: str | None) -> bool:
    value = parse_version(version_text)
    return bool(value and value >= SPECKIT_MIN_VERSION)


def project_integration(project: Path) -> str:
    config = read_json(project / ".specify" / "powerpack" / "model-routing.json", {})
    value = str(config.get("active_integration") or "").strip()
    if value:
        return value
    if (project / ".codex").exists():
        return "codex"
    if (project / ".claude").exists():
        return "claude"
    return "codex"


def playwright_package_ready() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return True


def playwright_browser_ready() -> bool:
    if not playwright_package_ready():
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)
            return executable.is_file()
    except Exception:
        return False


def review_readiness(project: Path) -> dict[str, bool]:
    path = project / ".specify" / "powerpack" / "review.json"
    value = read_json(path, {})
    web = value.get("chatgpt_web", {}) if isinstance(value, dict) else {}
    if not isinstance(web, dict):
        web = {}
    return {
        "web-review-required": bool(web.get("required") and web.get("enabled")),
        "playwright-package": playwright_package_ready(),
        "playwright-browser": playwright_browser_ready(),
        "chatgpt-account-authenticated": False,
        "chatgpt-project-bound": False,
    }


def print_review_setup_status(project: Path) -> None:
    print("\nCHATGPT WEB REVIEW SETUP")
    print("1. Configure a reviewer account with the installed PowerPack review backend.")
    print("2. Bind an accessible ChatGPT Project to this repository.")


def enforce_mandatory_web_review(review_path: Path) -> None:
    """Promote existing installed policy to the current mandatory Web backend.

    Account, endpoint and Project values remain null here because they are
    personal/user-scoped state. The repository file declares only that Web
    review is mandatory and which backend contract is expected.
    """
    if review_path.is_file():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PowerPackError(f"Cannot read PowerPack review config: {exc}") from exc
    else:
        review = read_asset_json("config/default-review.json")
    if not isinstance(review, dict):
        raise PowerPackError("PowerPack review config must contain an object.")
    review["schema_version"] = max(4, int(review.get("schema_version", 0) or 0))
    web = review.setdefault("chatgpt_web", {})
    web["required"] = True
    web["enabled"] = True
    web["backend"] = "chatgpt-web2api"
    web.setdefault("mode", "assisted")
    web["headless"] = False
    web.setdefault("project_alias", None)
    web.setdefault("project_id", None)
    web.setdefault("project_url", None)
    web.setdefault("project_name", None)
    web.setdefault("profile", None)
    web.setdefault("account_label", None)
    web.setdefault("endpoint", None)
    web.setdefault("profile_scope", "platform")
    web.setdefault("profile_platform", None)
    web.setdefault("authorization", None)
    write_json(review_path, review, overwrite=True)


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
    review_path = base / "review.json"
    write_json(review_path, read_asset_json("config/default-review.json"), overwrite=overwrite_config)
    enforce_mandatory_web_review(review_path)
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
        "documentation_only": "not-applicable",
    }, overwrite=overwrite_config)


def validate_project_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "www.chatgpt.com"} or not parsed.path.endswith("/project"):
        raise PowerPackError("Expected a ChatGPT Project URL: https://chatgpt.com/g/g-p-.../project")
    return url.rstrip("/")


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return parser.add_subparsers(dest="command", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="speckit-powerpack")
    parser.add_argument("--version", action="store_true", help=argparse.SUPPRESS)
    root = parser.add_subparsers(dest="command")

    doctor = root.add_parser("doctor", help="Check PowerPack installation")
    doctor.add_argument("--path", default=".")

    install = root.add_parser("install", help="Install/update PowerPack assets in a repository")
    install.add_argument("path", nargs="?", default=".")
    install.add_argument("--integration", default="codex")
    install.add_argument("--bootstrap-speckit", action="store_true")
    install.add_argument("--overwrite-config", action="store_true")

    review = root.add_parser("review", help="ChatGPT Web review configuration")
    rsub = review.add_subparsers(dest="review_cmd", required=True)
    auth = rsub.add_parser("auth")
    asub = auth.add_subparsers(dest="auth_cmd", required=True)
    asub.add_parser("login")
    logout = asub.add_parser("logout")
    logout.add_argument("profile")
    forget = asub.add_parser("forget")
    forget.add_argument("profile")
    asub.add_parser("authorize")

    project = rsub.add_parser("project")
    psub = project.add_subparsers(dest="project_cmd", required=True)
    bind = psub.add_parser("bind")
    bind.add_argument("alias")
    list_parser = psub.add_parser("list")
    list_parser.add_argument("--all-platforms", action="store_true")
    use_parser = psub.add_parser("use")
    use_parser.add_argument("alias")
    use_parser.add_argument("--path", default=".")

    return parser


def cmd_install(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    maybe_check_for_updates(global_root(), interactive=True)
    if args.bootstrap_speckit and not (project / ".specify").exists():
        specify = shutil.which("specify")
        if not specify:
            raise PowerPackError("Spec Kit CLI 'specify' is required for --bootstrap-speckit.")
        proc = subprocess.run([specify, "init", str(project), "--ai", args.integration, "--force", "--no-git"], text=True)
        if proc.returncode != 0:
            raise PowerPackError("Spec Kit bootstrap failed.")
    install_support(project, args.integration, overwrite_config=bool(args.overwrite_config))
    print("SpecKit PowerPack draft 0.1.0.dev0 installed.")
    print_review_setup_status(project)


def cmd_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    runtime = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    specify_binary = shutil.which("specify")
    current_spec_kit = specify_version(specify_binary) if specify_binary else None
    integration = project_integration(project)
    readiness = review_readiness(project)
    hard_checks = {
        "specify": bool(specify_binary),
        "spec-kit-compatible": spec_kit_compatible(current_spec_kit),
        "spec-kit-project": (project / ".specify").is_dir(),
        "powerpack-runtime": runtime.is_file(),
        "selected-executor": bool(shutil.which(integration)),
    }
    print(f"Platform:    {platform_key()} ({platform_module.system()})")
    print(f"Config:      {global_root()}")
    print(f"Integration: {integration}")
    print(f"Spec Kit:    {current_spec_kit or 'unknown'} (requires >= {SPECKIT_MIN_VERSION_TEXT})")
    for key, ok in hard_checks.items():
        print(f"{'OK' if ok else 'FAIL':5} {key}")
    for key, ok in readiness.items():
        print(f"{'OK' if ok else 'SETUP':5} {key}")
    if not all(hard_checks.values()):
        raise PowerPackError("PowerPack installation checks failed.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None and "--version" in sys.argv:
        print("0.1.0.dev0")
        return 0
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            cmd_install(args)
        elif args.command == "doctor":
            cmd_doctor(args)
        elif not hasattr(args, "func"):
            raise PowerPackError("Command is provided by an extended PowerPack CLI layer; refresh the installed package.")
        else:
            args.func(args)
        return 0
    except (PowerPackError, UpdateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "PowerPackError",
    "SPECKIT_MIN_VERSION_TEXT",
    "asset",
    "build_parser",
    "enforce_mandatory_web_review",
    "global_config",
    "global_root",
    "install_support",
    "platform_key",
    "platform_module",
    "playwright_browser_ready",
    "playwright_package_ready",
    "print_review_setup_status",
    "profile_dir",
    "project_integration",
    "read_asset_json",
    "read_json",
    "review_readiness",
    "save_global",
    "spec_kit_compatible",
    "specify_version",
    "validate_project_url",
    "write_json",
]
