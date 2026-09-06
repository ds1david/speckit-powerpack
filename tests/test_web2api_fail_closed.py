from __future__ import annotations

from pathlib import Path

import pytest

from speckit_powerpack import cli as core
from speckit_powerpack import cli_user_state as user_state
from speckit_powerpack import cli_web2api_review as web2api


class Project:
    def __init__(self, project_id: str):
        self.project_id = project_id


def test_verify_endpoint_accepts_cold_start_when_transport_is_fully_connected(monkeypatch):
    monkeypatch.setattr(
        web2api,
        "health",
        lambda endpoint, timeout=10: {
            "status": "starting",
            "chrome_running": True,
            "cdp_connected": True,
            "driver_connected": True,
            "open_breakers": [],
        },
    )
    monkeypatch.setattr(web2api, "list_projects", lambda endpoint, timeout=30: [Project("g-p-1")])

    state, projects = user_state._verify_endpoint_fail_closed("http://127.0.0.1:8080")

    assert state["status"] == "starting"
    assert projects[0].project_id == "g-p-1"


def test_verify_endpoint_rejects_degraded_driver_even_when_projects_are_still_visible(monkeypatch):
    monkeypatch.setattr(
        web2api,
        "health",
        lambda endpoint, timeout=10: {
            "status": "degraded",
            "chrome_running": True,
            "cdp_connected": False,
            "driver_connected": False,
            "open_breakers": [],
        },
    )
    monkeypatch.setattr(web2api, "list_projects", lambda endpoint, timeout=30: [Project("g-p-stale")])

    with pytest.raises(core.PowerPackError, match="reviewer transport is not ready"):
        user_state._verify_endpoint_fail_closed("http://127.0.0.1:8080")


def test_verify_endpoint_rejects_open_breaker_even_with_connected_driver(monkeypatch):
    monkeypatch.setattr(
        web2api,
        "health",
        lambda endpoint, timeout=10: {
            "status": "degraded",
            "chrome_running": True,
            "cdp_connected": True,
            "driver_connected": True,
            "open_breakers": ["auth_required"],
        },
    )
    monkeypatch.setattr(web2api, "list_projects", lambda endpoint, timeout=30: [Project("g-p-1")])

    with pytest.raises(core.PowerPackError, match="open_breakers"):
        user_state._verify_endpoint_fail_closed("http://127.0.0.1:8080")


def test_state_ready_requires_all_live_transport_bits():
    assert user_state._web2api_state_ready(
        {
            "status": "healthy",
            "chrome_running": True,
            "cdp_connected": True,
            "driver_connected": True,
            "open_breakers": [],
        }
    )
    assert not user_state._web2api_state_ready(
        {
            "status": "healthy",
            "chrome_running": True,
            "cdp_connected": False,
            "driver_connected": True,
            "open_breakers": [],
        }
    )
