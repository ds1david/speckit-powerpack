from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import web2api_windows_lifecycle as lifecycle


def test_windows_reviewer_uses_detached_process_and_pid_reuse(monkeypatch):
    monkeypatch.setattr(lifecycle.winbridge, "is_wsl", lambda: True)
    monkeypatch.setattr(
        lifecycle,
        "_decode_windows",
        lambda value: value.decode("utf-8") if isinstance(value, bytes) else str(value or ""),
    )
    captured = {}

    class Proc:
        returncode = 0
        stderr = b""
        stdout = json.dumps(
            {
                "pid": 4321,
                "endpoint": "http://127.0.0.1:8080",
                "profile_dir": "C:/reviewer/chrome-profile",
                "venv": "C:/reviewer/venv",
                "stdout": "C:/reviewer/logs/web2api.out.log",
                "stderr": "C:/reviewer/logs/web2api.err.log",
                "python": "C:/reviewer/venv/Scripts/python.exe",
                "upstream_revision": "test",
                "reused": False,
                "detached": True,
            }
        ).encode("utf-8")

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        encoded = argv[argv.index("-EncodedCommand") + 1]
        captured["script"] = base64.b64decode(encoded).decode("utf-16-le")
        return Proc()

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    result = lifecycle.start_windows_service(profile="ds1david", port=8080, cdp_port=9222)

    script = captured["script"]
    assert "launch-detached.py" in script
    assert "service.pid" in script
    assert "Get-Process -Id $existingPid" in script
    assert "DETACHED_PROCESS" not in script  # lives in the base64 launcher payload
    launcher_b64 = script.split("FromBase64String('", 1)[1].split("')", 1)[0]
    launcher = base64.b64decode(launcher_b64).decode("utf-8")
    assert "DETACHED_PROCESS" in launcher
    assert "CREATE_NEW_PROCESS_GROUP" in launcher
    assert result["detached"] is True
    assert result["pid"] == 4321


def test_wait_for_service_timeout_is_waiting_login_not_failure(monkeypatch):
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(ticks))
    state = lifecycle.wait_for_service("http://127.0.0.1:8080", timeout=1)
    assert state["status"] == "waiting-login"
    assert state["chrome_running"] is None
    assert state["cdp_connected"] is None
