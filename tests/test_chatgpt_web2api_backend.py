from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import chatgpt_web2api_backend as backend


def test_project_id_is_extracted_from_chatgpt_project_url():
    value = "https://chatgpt.com/g/g-p-6a7c9c009cf08191bca56001c8bd1a9f-autonomous-trading-strategy-evolution-lab/project"
    assert backend.project_id_from_value(value) == "g-p-6a7c9c009cf08191bca56001c8bd1a9f"


def test_list_projects_normalizes_multiple_payload_shapes(monkeypatch):
    monkeypatch.setattr(
        backend,
        "request_json",
        lambda *args, **kwargs: {
            "object": "list",
            "data": [
                {"id": "g-p-1", "name": "One"},
                {"project_id": "g-p-2", "title": "Two"},
                {"bad": True},
            ],
        },
    )
    values = backend.list_projects("http://127.0.0.1:8080")
    assert [(v.project_id, v.name) for v in values] == [("g-p-1", "One"), ("g-p-2", "Two")]


def test_chat_sends_project_id_and_parses_openai_compatible_response(monkeypatch):
    captured = {}

    def fake_request(endpoint, method, path, *, payload=None, timeout=30):
        captured.update(endpoint=endpoint, method=method, path=path, payload=payload, timeout=timeout)
        return {
            "id": "conv-123",
            "model": "auto",
            "choices": [{"message": {"role": "assistant", "content": "Project answer"}}],
        }

    monkeypatch.setattr(backend, "request_json", fake_request)
    result = backend.chat(
        "http://127.0.0.1:8080",
        project_id="g-p-abc123",
        prompt="review this",
        timeout=90,
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["payload"]["project_id"] == "g-p-abc123"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "review this"}]
    assert result.response == "Project answer"
    assert result.conversation_id == "conv-123"


def test_wsl_loopback_requests_are_executed_on_windows_host(monkeypatch):
    monkeypatch.setattr(backend.winbridge, "is_wsl", lambda: True)
    calls = []

    def fake_windows(method, url, *, payload, timeout):
        calls.append((method, url, payload, timeout))
        return backend.HttpResult(200, '{"status":"healthy"}')

    monkeypatch.setattr(backend, "_powershell_json_request", fake_windows)
    value = backend.request_json("http://127.0.0.1:8080", "GET", "/health", timeout=7)
    assert value == {"status": "healthy"}
    assert calls == [("GET", "http://127.0.0.1:8080/health", None, 7)]


def test_non_loopback_request_uses_normal_http_transport(monkeypatch):
    monkeypatch.setattr(backend.winbridge, "is_wsl", lambda: True)
    calls = []

    def fake_urllib(method, url, *, payload, timeout):
        calls.append((method, url, payload, timeout))
        return backend.HttpResult(200, '{"ok":true}')

    monkeypatch.setattr(backend, "_urllib_request", fake_urllib)
    value = backend.request_json("http://10.0.0.5:8080", "GET", "/health")
    assert value == {"ok": True}
    assert calls[0][1] == "http://10.0.0.5:8080/health"


def test_windows_service_installs_pinned_github_archive_in_dedicated_venv(monkeypatch):
    monkeypatch.setattr(backend.winbridge, "is_wsl", lambda: True)
    monkeypatch.setattr(
        backend,
        "_decode_windows",
        lambda value: value.decode("utf-8") if isinstance(value, bytes) else str(value or ""),
    )
    captured = {}

    class Proc:
        returncode = 0
        stderr = b""
        stdout = json.dumps(
            {
                "pid": 1234,
                "endpoint": "http://127.0.0.1:8080",
                "profile_dir": "C:/reviewer/chrome-profile",
                "venv": "C:/reviewer/venv",
                "stdout": "C:/reviewer/out.log",
                "stderr": "C:/reviewer/err.log",
                "python": "C:/reviewer/venv/Scripts/python.exe",
                "upstream_revision": backend.WEB2API_REVISION,
            }
        ).encode("utf-8")

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        encoded = argv[argv.index("-EncodedCommand") + 1]
        captured["script"] = base64.b64decode(encoded).decode("utf-16-le")
        return Proc()

    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    result = backend.start_windows_service(profile="ds1david", port=8080, cdp_port=9222)

    script = captured["script"]
    assert backend.WEB2API_INSTALL_URL in script
    assert backend.WEB2API_REVISION in script
    assert "-m venv $venv" in script
    assert "Join-Path $venv 'Scripts\\python.exe'" in script
    assert "pip install --disable-pip-version-check --no-warn-script-location --upgrade $source" in script
    assert "--user --upgrade" not in script
    assert "$ErrorActionPreference = 'Continue'" in script
    assert "pip install --user --upgrade chatgpt-web2api" not in script
    assert result["venv"] == "C:/reviewer/venv"
    assert result["upstream_revision"] == backend.WEB2API_REVISION
