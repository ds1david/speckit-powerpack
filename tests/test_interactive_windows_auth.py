from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import cli as core
from speckit_powerpack import cli_account_binding as base
from speckit_powerpack import cli_interactive_auth as interactive
from speckit_powerpack import windows_browser_bridge as winbridge


def test_parser_adds_parameterless_interactive_configure_and_reconfigure():
    parser = interactive.build_parser()
    configure = parser.parse_args(["review", "auth", "configure"])
    assert configure.func is interactive.cmd_auth_configure

    reconfigure = parser.parse_args(["review", "auth", "reconfigure"])
    assert reconfigure.func is interactive.cmd_auth_reconfigure
    assert reconfigure.profile is None

    validate = parser.parse_args(["review", "auth", "validate"])
    assert validate.func is interactive.cmd_auth_validate
    assert validate.profile is None


def test_windows_account_is_authorized_without_linux_profile_dir():
    data = {
        "accounts": {
            "linux": {
                "ds1david": {
                    "source": interactive.WINDOWS_ACCOUNT_AUTH_SOURCE,
                    "backend": interactive.WINDOWS_ACCOUNT_BACKEND,
                    "browser_channel": "msedge",
                    "remote_debugging_consent": True,
                }
            }
        }
    }
    assert interactive._account_authorized(data, "linux", "ds1david") is True


def test_windows_account_requires_explicit_remote_debugging_consent():
    data = {
        "accounts": {
            "linux": {
                "ds1david": {
                    "source": interactive.WINDOWS_ACCOUNT_AUTH_SOURCE,
                    "backend": interactive.WINDOWS_ACCOUNT_BACKEND,
                    "browser_channel": "msedge",
                    "remote_debugging_consent": False,
                }
            }
        }
    }
    assert interactive._account_authorized(data, "linux", "ds1david") is False


def test_persist_windows_account_records_backend_and_invalidates_old_binding(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.json"
    state = {
        "schema_version": 3,
        "projects": {
            "atsel": {
                "bindings": {
                    "linux": {
                        "ds1david": {
                            "profile": "ds1david",
                            "url": "https://chatgpt.com/g/g-p-demo/project",
                            "authorization": base.PROJECT_BINDING_AUTH,
                        }
                    }
                }
            }
        },
    }

    def global_config():
        return config_path, state

    def save_global(path: Path, data: dict):
        snapshot = json.loads(json.dumps(data))
        state.clear()
        state.update(snapshot)
        path.write_text(json.dumps(snapshot), encoding="utf-8")

    monkeypatch.setattr(core, "global_config", global_config)
    monkeypatch.setattr(core, "save_global", save_global)
    monkeypatch.setattr(core, "platform_key", lambda *args, **kwargs: "linux")

    invalidated = interactive._persist_windows_account(
        profile="ds1david",
        account_label="ds1david-plus",
        browser_channel="msedge",
    )

    assert invalidated == ["atsel"]
    account = state["accounts"]["linux"]["ds1david"]
    assert account["source"] == interactive.WINDOWS_ACCOUNT_AUTH_SOURCE
    assert account["backend"] == interactive.WINDOWS_ACCOUNT_BACKEND
    assert account["browser_channel"] == "msedge"
    assert account["remote_debugging_consent"] is True
    assert state["projects"]["atsel"]["bindings"]["linux"]["ds1david"]["authorization"] == base.STALE_BINDING_AUTH


def test_windows_project_binding_persists_reviewer_backend(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.json"
    project = tmp_path / "repo"
    review_path = project / ".specify" / "powerpack" / "review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps({"chatgpt_web": {"required": True, "enabled": True}}), encoding="utf-8")
    state = {
        "schema_version": 4,
        "accounts": {
            "linux": {
                "ds1david": {
                    "source": interactive.WINDOWS_ACCOUNT_AUTH_SOURCE,
                    "backend": interactive.WINDOWS_ACCOUNT_BACKEND,
                    "account_label": "ds1david-plus",
                    "browser_channel": "msedge",
                    "remote_debugging_consent": True,
                }
            }
        },
        "projects": {},
    }

    def global_config():
        return config_path, state

    def save_global(path: Path, data: dict):
        snapshot = json.loads(json.dumps(data))
        state.clear()
        state.update(snapshot)
        path.write_text(json.dumps(snapshot), encoding="utf-8")

    monkeypatch.setattr(core, "global_config", global_config)
    monkeypatch.setattr(core, "save_global", save_global)
    monkeypatch.setattr(core, "platform_key", lambda *args, **kwargs: "linux")

    candidate = base.ProjectCandidate("ATSEL", "https://chatgpt.com/g/g-p-demo/project")
    interactive._persist_binding(alias="atsel", candidate=candidate, profile="ds1david", project_path=project)

    binding = state["projects"]["atsel"]["bindings"]["linux"]["ds1david"]
    assert binding["account_backend"] == interactive.WINDOWS_ACCOUNT_BACKEND
    assert binding["browser_channel"] == "msedge"

    web = json.loads(review_path.read_text(encoding="utf-8"))["chatgpt_web"]
    assert web["profile"] == "ds1david"
    assert web["account_label"] == "ds1david-plus"
    assert web["account_backend"] == interactive.WINDOWS_ACCOUNT_BACKEND
    assert web["browser_channel"] == "msedge"


def test_strict_readiness_requires_live_windows_session(tmp_path: Path, monkeypatch):
    project = tmp_path / "repo"
    review_path = project / ".specify" / "powerpack" / "review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps({
        "chatgpt_web": {
            "required": True,
            "enabled": True,
            "project_alias": "atsel",
            "project_url": "https://chatgpt.com/g/g-p-demo/project",
            "profile": "ds1david",
            "authorization": base.PROJECT_BINDING_AUTH,
        }
    }), encoding="utf-8")
    state = {
        "accounts": {
            "linux": {
                "ds1david": {
                    "source": interactive.WINDOWS_ACCOUNT_AUTH_SOURCE,
                    "backend": interactive.WINDOWS_ACCOUNT_BACKEND,
                    "browser_channel": "msedge",
                    "remote_debugging_consent": True,
                }
            }
        },
        "projects": {
            "atsel": {
                "bindings": {
                    "linux": {
                        "ds1david": {
                            "profile": "ds1david",
                            "url": "https://chatgpt.com/g/g-p-demo/project",
                            "authorization": base.PROJECT_BINDING_AUTH,
                        }
                    }
                }
            }
        },
    }

    monkeypatch.setattr(core, "global_config", lambda: (tmp_path / "config.json", state))
    monkeypatch.setattr(core, "platform_key", lambda *args, **kwargs: "linux")
    monkeypatch.setattr(core, "playwright_package_ready", lambda: True)
    monkeypatch.setattr(core, "playwright_browser_ready", lambda: True)

    def fail_live(**kwargs):
        raise winbridge.WindowsBrowserBridgeError("offline")

    monkeypatch.setattr(winbridge, "validate_existing_windows_chatgpt_session", fail_live)

    normal = interactive.review_readiness(project, live=False)
    assert normal["chatgpt-account-authenticated"] is True
    assert normal["chatgpt-project-bound"] is True

    strict = interactive.review_readiness(project, live=True)
    assert strict["chatgpt-browser-session-live"] is False


def test_browser_channel_normalization():
    assert winbridge.normalize_browser_channel("edge") == "msedge"
    assert winbridge.normalize_browser_channel("msedge") == "msedge"
    assert winbridge.normalize_browser_channel("chrome") == "chrome"
    assert winbridge.session_name_for("ds1david") == "speckit-powerpack-ds1david"
