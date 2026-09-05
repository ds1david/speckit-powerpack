from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import cli as core
from speckit_powerpack import cli_entry
from speckit_powerpack import review_onboarding as onboarding


def test_consent_page_discloses_isolated_profile_and_exact_project(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "linux" / "atsel"
    html = onboarding.consent_html(
        profile="atsel",
        project_alias="atsel-project",
        project_url="https://chatgpt.com/g/g-p-demo/project",
        profile_dir=profile_dir,
    )
    assert "Autorizar acesso do PowerPack ao ChatGPT Web?" in html
    assert "Não reutiliza cookies, histórico ou sessão do Edge/Chrome" in html
    assert str(profile_dir) in html
    assert "atsel-project" in html
    assert "https://chatgpt.com/g/g-p-demo/project" in html
    assert "Conceder acesso ao projeto" in html


def test_chromium_install_uses_cli_and_writes_versioned_receipt(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_runner(argv, **kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(onboarding, "playwright_version", lambda: "1.55.0")
    onboarding.ensure_chromium(tmp_path, "linux", runner=fake_runner)

    assert calls == [[sys.executable, "-m", "playwright", "install", "chromium"]]
    receipt = onboarding.browser_install_receipt(tmp_path, "linux")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["browser"] == "chromium"
    assert data["platform"] == "linux"
    assert data["playwright_version"] == "1.55.0"
    assert onboarding.browser_install_ready(tmp_path, "linux") is True


def test_browser_receipt_becomes_stale_when_playwright_version_changes(tmp_path: Path, monkeypatch):
    receipt = onboarding.browser_install_receipt(tmp_path, "linux")
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({
            "schema_version": 1,
            "browser": "chromium",
            "platform": "linux",
            "playwright_version": "1.55.0",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(onboarding, "playwright_version", lambda: "1.56.0")
    assert onboarding.browser_install_ready(tmp_path, "linux") is False


def test_cli_registers_single_command_authorization_flow():
    args = cli_entry.build_parser().parse_args([
        "review",
        "authorize",
        "--profile", "atsel",
        "--project", "atsel",
        "--url", "https://chatgpt.com/g/g-p-demo/project",
        "--path", ".",
    ])
    assert args.func is cli_entry.cmd_review_authorize
    assert args.profile == "atsel"
    assert args.project == "atsel"


def test_browser_readiness_does_not_start_playwright_connection(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(core, "playwright_package_ready", lambda: True)
    monkeypatch.setattr(core, "global_root", lambda: tmp_path)
    monkeypatch.setattr(core, "platform_key", lambda: "linux")
    monkeypatch.setattr(cli_entry, "browser_install_ready", lambda root, platform: (root, platform) == (tmp_path, "linux"))
    assert cli_entry.playwright_browser_ready() is True


def test_authorization_persists_platform_profile_and_project_binding(tmp_path: Path, monkeypatch):
    global_path = tmp_path / "global.json"
    project = tmp_path / "project"
    review_path = project / ".specify" / "powerpack" / "review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps({"chatgpt_web": {"required": True, "enabled": True}}), encoding="utf-8")

    monkeypatch.setattr(core, "global_config", lambda: (global_path, {}))

    def save_global(path: Path, data: dict):
        path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(core, "save_global", save_global)

    result = onboarding.ReviewAuthorizationResult(
        granted=True,
        profile="atsel",
        project_alias="atsel-project",
        project_url="https://chatgpt.com/g/g-p-demo/project",
        platform="linux",
        profile_dir="/tmp/powerpack-profile",
        granted_at="2026-09-05T22:00:00+00:00",
    )
    cli_entry._write_authorized_project(result=result, project_path=project)

    global_data = json.loads(global_path.read_text(encoding="utf-8"))
    assert global_data["active_profiles"]["linux"] == "atsel"
    assert global_data["authenticated_profiles"]["linux"]["atsel"]["source"] == "playwright-consent"
    assert global_data["authorizations"]["linux"]["atsel"]["scope"] == "chatgpt-web-review"
    assert global_data["projects"]["atsel-project"]["bindings"]["linux"]["profile"] == "atsel"

    review = json.loads(review_path.read_text(encoding="utf-8"))
    web = review["chatgpt_web"]
    assert web["required"] is True
    assert web["enabled"] is True
    assert web["project_alias"] == "atsel-project"
    assert web["profile"] == "atsel"
    assert web["profile_platform"] == "linux"
    assert web["authorization"] == "playwright-consent"
