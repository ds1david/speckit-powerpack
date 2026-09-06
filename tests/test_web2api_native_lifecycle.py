from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import chatgpt_web2api_backend as backend
from speckit_powerpack import web2api_native_lifecycle as native


def test_detect_native_browser_prefers_microsoft_edge(monkeypatch):
    paths = {
        "microsoft-edge": "/usr/bin/microsoft-edge",
        "google-chrome": "/usr/bin/google-chrome",
    }
    monkeypatch.setattr(native.shutil, "which", lambda command: paths.get(command))
    monkeypatch.setattr(native.Path, "resolve", lambda self: self)

    browser = native.detect_native_browser()

    assert browser == {
        "name": "Microsoft Edge",
        "command": "microsoft-edge",
        "path": "/usr/bin/microsoft-edge",
    }


def test_wsl_local_first_transport_uses_linux_loopback_before_windows(monkeypatch):
    monkeypatch.setattr(native.winbridge, "is_wsl", lambda: True)
    monkeypatch.delattr(backend, "_powerpack_wsl_local_first", raising=False)
    original = backend.request_json
    calls = []

    def local_request(method, url, *, payload, timeout):
        calls.append(("local", method, url))
        return backend.HttpResult(200, json.dumps({"status": "ready"}))

    def windows_should_not_run(*args, **kwargs):
        raise AssertionError("Windows fallback must not run when WSL-local reviewer answers")

    monkeypatch.setattr(backend, "_urllib_request", local_request)
    monkeypatch.setattr(backend, "request_json", windows_should_not_run)
    native.install_wsl_local_first_transport()

    result = backend.request_json("http://127.0.0.1:8080", "GET", "/health", timeout=2)

    assert result == {"status": "ready"}
    assert calls == [("local", "GET", "http://127.0.0.1:8080/health")]
    monkeypatch.setattr(backend, "request_json", original)
    monkeypatch.delattr(backend, "_powerpack_wsl_local_first", raising=False)


def test_native_service_builds_web2api_with_explicit_edge_path(monkeypatch, tmp_path):
    browser = {"name": "Microsoft Edge", "command": "microsoft-edge", "path": "/usr/bin/microsoft-edge"}
    fake_python = tmp_path / "venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(native, "_ensure_reviewer_environment", lambda root, install: fake_python)
    monkeypatch.setattr(native, "install_wsl_local_first_transport", lambda: None)
    monkeypatch.setattr(native.backend, "health", lambda *args, **kwargs: (_ for _ in ()).throw(backend.Web2APIError("not ready")))
    monkeypatch.setattr(native.winbridge, "is_wsl", lambda: True)
    monkeypatch.setattr(native, "_pid_alive", lambda pid: False)
    seen = {}

    class Proc:
        pid = 4321
        returncode = None

        def poll(self):
            return None

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        return Proc()

    monkeypatch.setattr(native.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(native.time, "sleep", lambda seconds: None)

    info = native.start_native_service(
        config_root=tmp_path / "config",
        profile="ds1david",
        port=8080,
        cdp_port=9222,
        install=False,
        browser=browser,
    )

    assert info["host_scope"] == "wsl-native"
    assert info["pid"] == 4321
    assert "--chrome-path" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--chrome-path") + 1] == "/usr/bin/microsoft-edge"
    assert "--cdp-port" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--cdp-port") + 1] == "9222"
