from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).parents[1] / "src" / "speckit_powerpack" / "assets" / "runtime" / "powerpack_capabilities.py"
spec = importlib.util.spec_from_file_location("powerpack_capabilities", MODULE_PATH)
cap = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = cap
spec.loader.exec_module(cap)


def executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)


def project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".specify" / "powerpack").mkdir(parents=True)
    return root


def test_platform_capability_order():
    assert cap.platform_capabilities("Windows").prerequisite_runner_order[0] == "powershell"
    assert cap.platform_capabilities("Linux").prerequisite_runner_order[0] == "bash"
    assert cap.platform_capabilities("Darwin").key == "macos"


def test_windows_maven_wrapper(tmp_path: Path):
    root = project(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    (root / "mvnw.cmd").write_text("@echo off\r\n")
    result = cap.gate_for_project(root, ["src/App.java"], system="Windows")
    assert result["command"][0].endswith("mvnw.cmd")


def test_posix_maven_wrapper(tmp_path: Path):
    root = project(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    executable(root / "mvnw")
    result = cap.gate_for_project(root, ["src/App.java"], system="Linux")
    assert result["command"][0].endswith("mvnw")


def test_windows_gradle_wrapper(tmp_path: Path):
    root = project(tmp_path)
    (root / "build.gradle").write_text("")
    (root / "gradlew.cmd").write_text("@echo off\r\n")
    assert cap.gate_for_project(root, ["src/App.java"], system="Windows")["command"][0].endswith("gradlew.cmd")


def test_missing_tool_blocks(tmp_path: Path, monkeypatch):
    root = project(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    monkeypatch.setattr(cap.shutil, "which", lambda _: None)
    result = cap.gate_for_project(root, ["src/App.java"], system="Linux")
    assert result["status"] == "BLOCKED_CONFIGURATION"
    assert result["reason"] == "required-tool-unavailable"


def test_pyproject_does_not_imply_pytest(tmp_path: Path):
    root = project(tmp_path)
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
    assert cap.gate_for_project(root, ["src/demo.py"])["reason"] == "unknown-project-architecture"


def test_pytest_requires_explicit_configuration(tmp_path: Path):
    root = project(tmp_path)
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts='-q'\n")
    result = cap.gate_for_project(root, ["src/demo.py"])
    assert result["reason"] == "pytest"
    assert result["command"] == [sys.executable, "-m", "pytest"]


def test_polyglot_is_ambiguous(tmp_path: Path, monkeypatch):
    root = project(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    (root / "go.mod").write_text("module demo\n")
    executable(root / "mvnw")
    monkeypatch.setattr(cap.shutil, "which", lambda x: "/usr/bin/go" if x == "go" else None)
    result = cap.gate_for_project(root, ["src/App.java"], system="Linux")
    assert result["reason"] == "ambiguous-project-architecture"


def test_docs_only_is_os_and_framework_independent(tmp_path: Path):
    root = project(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    for system in ("Windows", "Linux", "Darwin"):
        assert cap.gate_for_project(root, ["README.md", "docs/guide.md"], system=system)["status"] == "NOT_APPLICABLE"


def test_custom_gate_overrides_detection(tmp_path: Path):
    root = project(tmp_path)
    (root / "pom.xml").write_text("<project/>")
    (root / ".specify" / "powerpack" / "quality-gates.json").write_text('{"custom_command":["tool","verify"]}')
    result = cap.gate_for_project(root, ["src/App.java"])
    assert result["strategy"] == "custom"
    assert result["command"] == ["tool", "verify"]
