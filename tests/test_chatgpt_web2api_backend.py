from __future__ import annotations

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
