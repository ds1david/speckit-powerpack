#!/usr/bin/env python3
"""Capability resolver for SpecKit PowerPack.

Workflow commands stay OS/language/framework agnostic. This module converts
observable project/environment capabilities into deterministic executable
strategies and fails closed when the architecture is ambiguous.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform as platform_module
import shutil
import subprocess
import sys
import tomllib
from typing import Any, Callable, Iterable

DOC_EXTENSIONS = {".md", ".mdx", ".txt", ".rst", ".adoc", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
DOC_DIRS = {"docs", "doc", "documentation"}


@dataclass(frozen=True)
class PlatformCapabilities:
    key: str
    shell_family: str
    local_script_suffixes: tuple[str, ...]
    prerequisite_runner_order: tuple[str, ...]


@dataclass(frozen=True)
class GateStrategy:
    name: str
    detect: Callable[[Path], bool]
    command: Callable[[Path, PlatformCapabilities], list[str] | None]


def normalize_platform(system: str | None = None) -> str:
    value = (system or platform_module.system()).strip().lower()
    if value.startswith("win"):
        return "windows"
    if value in {"darwin", "mac", "macos"}:
        return "macos"
    if value == "linux":
        return "linux"
    return "other"


def platform_capabilities(system: str | None = None) -> PlatformCapabilities:
    key = normalize_platform(system)
    if key == "windows":
        return PlatformCapabilities(key, "powershell", (".cmd", ".bat", ".exe", ""), ("powershell", "bash"))
    return PlatformCapabilities(key, "posix", ("", ".sh"), ("bash", "powershell"))


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), text=True, capture_output=True)


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".specify").is_dir():
            return candidate
    raise SystemExit("BLOCKED: .specify directory not found.")


def prerequisite_runners(root: Path, caps: PlatformCapabilities) -> list[list[str]]:
    scripts = {
        "bash": root / ".specify" / "scripts" / "bash" / "check-prerequisites.sh",
        "powershell": root / ".specify" / "scripts" / "powershell" / "check-prerequisites.ps1",
    }
    result: list[list[str]] = []
    for family in caps.prerequisite_runner_order:
        if family == "bash":
            exe = shutil.which("bash")
            if exe and scripts[family].is_file():
                result.append([exe, str(scripts[family]), "--json"])
        else:
            exe = shutil.which("pwsh") or shutil.which("powershell")
            if exe and scripts[family].is_file():
                result.append([exe, "-NoProfile", "-File", str(scripts[family]), "-Json"])
    return result


def resolve_feature_dir(root: Path, explicit: str | None = None, *, system: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            return path.resolve()
        raise SystemExit(f"BLOCKED: feature directory does not exist: {path}")
    for argv in prerequisite_runners(root, platform_capabilities(system)):
        proc = run(argv, root)
        if proc.returncode:
            continue
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue
        value = data.get("FEATURE_DIR") or data.get("feature_dir")
        if value:
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            if path.is_dir():
                return path.resolve()
    branch = run(["git", "branch", "--show-current"], root).stdout.strip()
    specs = root / "specs"
    if branch and specs.is_dir():
        direct = specs / branch
        if direct.is_dir():
            return direct.resolve()
        matches = [p for p in specs.glob(f"{branch}*") if p.is_dir()]
        if len(matches) == 1:
            return matches[0].resolve()
    raise SystemExit("BLOCKED: could not resolve current feature directory; pass --feature-dir.")


def feature_key(root: Path, feature: Path) -> str:
    try:
        raw = feature.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raw = feature.name
    return raw.replace("/", "__").replace("\\", "__")


def latest_implement_files(root: Path, feature: Path) -> list[str]:
    path = root / ".specify" / "powerpack" / "state" / f"{feature_key(root, feature)}.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    runs = [item for item in data.get("implement_runs", []) if item.get("status") == "COMPLETED"]
    return list(runs[-1].get("changed_files", [])) if runs else []


def is_documentation_only(paths: Iterable[str]) -> bool:
    items = list(paths)
    if not items:
        return True
    for raw in items:
        path = Path(raw)
        parts = {p.lower() for p in path.parts}
        suffix = path.suffix.lower()
        if suffix in DOC_EXTENSIONS:
            continue
        if parts & DOC_DIRS and suffix not in {".sh", ".ps1", ".py", ".js", ".ts"}:
            continue
        return False
    return True


def quality_config(root: Path) -> dict[str, Any]:
    path = root / ".specify" / "powerpack" / "quality-gates.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def local_tool(root: Path, stem: str, caps: PlatformCapabilities) -> str | None:
    for suffix in caps.local_script_suffixes:
        path = root / f"{stem}{suffix}"
        if path.is_file() and (caps.key == "windows" or os.access(path, os.X_OK)):
            return str(path)
    return None


def tool(root: Path, stem: str, caps: PlatformCapabilities, *, local: bool = False) -> str | None:
    return (local_tool(root, stem, caps) if local else None) or shutil.which(stem)


def node_command(root: Path, caps: PlatformCapabilities) -> list[str] | None:
    try:
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    target = next((name for name in ("verify", "check", "test") if name in scripts), None)
    if not target:
        return None
    choices = [
        ("pnpm-lock.yaml", "pnpm", ["run", target]),
        ("yarn.lock", "yarn", [target]),
        ("bun.lockb", "bun", ["run", target]),
        ("bun.lock", "bun", ["run", target]),
    ]
    for marker, name, tail in choices:
        if (root / marker).is_file():
            exe = tool(root, name, caps)
            return [exe, *tail] if exe else None
    exe = tool(root, "npm", caps)
    return [exe, "run", target] if exe else None


def pytest_configured(root: Path) -> bool:
    if (root / "pytest.ini").is_file():
        return True
    path = root / "pyproject.toml"
    if not path.is_file():
        return False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return isinstance(data.get("tool", {}).get("pytest"), dict)


def strategies() -> tuple[GateStrategy, ...]:
    return (
        GateStrategy("maven", lambda r: (r / "pom.xml").is_file(), lambda r, c: ([exe, "-B", "verify"] if (exe := (tool(r, "mvnw", c, local=True) or tool(r, "mvn", c))) else None)),
        GateStrategy("gradle", lambda r: (r / "build.gradle").is_file() or (r / "build.gradle.kts").is_file(), lambda r, c: ([exe, "check"] if (exe := (tool(r, "gradlew", c, local=True) or tool(r, "gradle", c))) else None)),
        GateStrategy("node", lambda r: (r / "package.json").is_file(), node_command),
        GateStrategy("tox", lambda r: (r / "tox.ini").is_file(), lambda r, c: ([exe] if (exe := tool(r, "tox", c)) else None)),
        GateStrategy("pytest", pytest_configured, lambda r, c: [sys.executable, "-m", "pytest"]),
        GateStrategy("dotnet", lambda r: bool(list(r.glob("*.sln")) or list(r.glob("*.csproj"))), lambda r, c: ([exe, "test"] if (exe := tool(r, "dotnet", c)) else None)),
        GateStrategy("go", lambda r: (r / "go.mod").is_file(), lambda r, c: ([exe, "test", "./..."] if (exe := tool(r, "go", c)) else None)),
        GateStrategy("rust", lambda r: (r / "Cargo.toml").is_file(), lambda r, c: ([exe, "test"] if (exe := tool(r, "cargo", c)) else None)),
    )


def gate_for_project(root: Path, files: list[str], *, system: str | None = None) -> dict[str, Any]:
    if is_documentation_only(files):
        return {"status": "NOT_APPLICABLE", "reason": "documentation-only", "command": None, "changed_files": files}
    custom = quality_config(root).get("custom_command")
    if isinstance(custom, list) and custom and all(isinstance(x, str) for x in custom):
        return {"status": "REQUIRED", "reason": "configured", "strategy": "custom", "command": custom, "changed_files": files}
    caps = platform_capabilities(system)
    detected = [(s.name, s.command(root, caps)) for s in strategies() if s.detect(root)]
    if len(detected) > 1:
        return {"status": "BLOCKED_CONFIGURATION", "reason": "ambiguous-project-architecture", "detected_strategies": [x[0] for x in detected], "command": None, "changed_files": files, "next_action": "Configure an explicit custom_command for this polyglot/multi-build project."}
    if len(detected) == 1:
        name, command = detected[0]
        if command:
            return {"status": "REQUIRED", "reason": name, "strategy": name, "platform": caps.key, "command": command, "changed_files": files}
        return {"status": "BLOCKED_CONFIGURATION", "reason": "required-tool-unavailable", "strategy": name, "platform": caps.key, "command": None, "changed_files": files, "next_action": f"Install/configure the {name} tool or provide custom_command."}
    eclipse = (root / ".project").is_file() or (root / ".classpath").is_file()
    return {"status": "BLOCKED_CONFIGURATION", "reason": "eclipse-project-without-deterministic-build-gate" if eclipse else "unknown-project-architecture", "platform": caps.key, "command": None, "changed_files": files, "next_action": "Configure .specify/powerpack/quality-gates.json custom_command."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="powerpack-capabilities")
    sub = parser.add_subparsers(dest="area", required=True)
    platform = sub.add_parser("platform")
    platform.add_argument("--system")
    gate = sub.add_parser("gate")
    gate_sub = gate.add_subparsers(dest="action", required=True)
    for action in ("detect", "run"):
        p = gate_sub.add_parser(action)
        p.add_argument("--feature-dir")
        p.add_argument("--system")
    args = parser.parse_args(argv)
    if args.area == "platform":
        caps = platform_capabilities(args.system)
        print(json.dumps({"platform": caps.key, "shell_family": caps.shell_family, "local_script_suffixes": caps.local_script_suffixes, "prerequisite_runner_order": caps.prerequisite_runner_order}))
        return 0
    root = find_root()
    feature = resolve_feature_dir(root, args.feature_dir, system=args.system)
    result = gate_for_project(root, latest_implement_files(root, feature), system=args.system)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "BLOCKED_CONFIGURATION":
        return 7
    if args.action == "run" and result["status"] == "REQUIRED":
        return subprocess.run(result["command"], cwd=str(root)).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
