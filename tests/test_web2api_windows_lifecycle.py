from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import web2api_windows_lifecycle as lifecycle


def test_windows_reviewer_separates_browser_and_service_lifecycles(monkeypatch):
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
                "phase": "waiting-remote-debugging",
                "pid": 0,
                "browser_pid": 4321,
                "endpoint": "http://127.0.0.1:8080",
                "chrome_cdp_ipv4": "http://127.0.0.1:9222/json/version",
                "chrome_cdp_ipv6": "http://[::1]:9222/json/version",
                "profile_dir": "C:/reviewer/chrome-profile",
                "stdout": "C:/reviewer/logs/web2api.out.log",
                "stderr": "C:/reviewer/logs/web2api.err.log",
                "browser_stderr": "C:/reviewer/logs/chrome.err.log",
                "cdp_transport": "not-ready",
                "upstream_revision": "test",
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
    assert "browser.pid" in script
    assert "service.pid" in script
    assert "chrome://inspect/#remote-debugging" in script
    assert "waiting-remote-debugging" in script
    assert "http://127.0.0.1:$requestedCdpPort/json/version" in script
    assert "http://[::1]:$requestedCdpPort/json/version" in script
    assert "ipv6-via-user-bridge" in script
    assert "cdp-bridge.pid" in script
    assert "cdp-bridge.port" in script
    assert "Get-FreeIpv4LoopbackPort" in script
    assert "$web2apiCdpPort" in script
    assert script.index("waiting-remote-debugging") < script.index("$serviceArgv =")

    launcher_b64 = base64.b64encode(lifecycle._DETACHED_LAUNCHER_SOURCE.encode("utf-8")).decode("ascii")
    assert launcher_b64 in script
    assert "DETACHED_PROCESS" in lifecycle._DETACHED_LAUNCHER_SOURCE
    assert "CREATE_NEW_PROCESS_GROUP" in lifecycle._DETACHED_LAUNCHER_SOURCE
    assert "socket.AF_INET6" in lifecycle._TCP_BRIDGE_SOURCE
    assert 'BridgeServer(("127.0.0.1", listen_port)' in lifecycle._TCP_BRIDGE_SOURCE

    assert result["phase"] == "waiting-remote-debugging"
    assert result["browser_pid"] == 4321
    assert result["cdp_transport"] == "not-ready"


def test_ipv6_bridge_is_standard_library_and_forwards_to_ipv6_loopback():
    bridge = lifecycle._TCP_BRIDGE_SOURCE
    assert "socketserver.ThreadingTCPServer" in bridge
    assert "socket.AF_INET" in bridge
    assert "socket.AF_INET6" in bridge
    assert '("::1", target_port, 0, 0)' in bridge
    assert "select.select" in bridge
    assert "serve_forever" in bridge


def test_wait_for_service_timeout_keeps_independent_browser_alive(monkeypatch):
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(ticks))
    state = lifecycle.wait_for_service("http://127.0.0.1:8080", timeout=1)
    assert state["status"] == "waiting-login"
    assert state["chrome_running"] is True
    assert state["cdp_connected"] is True
