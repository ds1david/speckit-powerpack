from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import cli
from speckit_powerpack import cli_account_binding as account_cli
from speckit_powerpack import review_onboarding as onboarding


def test_account_consent_page_discloses_isolated_profile_and_account_scope(tmp_path: Path):
    profile_dir = tmp_path / "browser-profiles" / "linux" / "ds1david"
    html = onboarding.account_consent_html(
        profile="ds1david",
        account_label="ds1david-plus",
        profile_dir=profile_dir,
    )
    assert "Autorizar esta conta ChatGPT para reviews Web?" in html
    assert "Não reutiliza cookies, histórico ou sessão do Edge/Chrome" in html
    assert "não de um Project específico" in html
    assert "duas assinaturas/contas" in html
    assert str(profile_dir) in html
    assert "ds1david-plus" in html
    assert "Já concluí o login — validar conta" in html
    assert "este botão não concede acesso" in html
    assert "2. Conta validada" in html
    assert "Conceder acesso à conta" in html


def test_chatgpt_login_verification_rejects_auth_routes_and_login_prompts():
    assert onboarding.chatgpt_login_verified("https://chatgpt.com/auth/login", "") is False
    assert onboarding.chatgpt_login_verified("https://chatgpt.com/", "Log in Continue with Google") is False
    assert onboarding.chatgpt_login_verified("https://chatgpt.com/", "Entrar Continuar com Google") is False
    assert onboarding.chatgpt_login_verified("https://example.com/", "ChatGPT") is False
    assert onboarding.chatgpt_login_verified("https://chatgpt.com/", "New chat Projects") is True
    assert onboarding.chatgpt_login_verified("https://chatgpt.com/g/g-p-demo/project", "ATSEL") is True


def test_project_url_helpers_accept_project_and_reject_non_chatgpt():
    requested = "https://chatgpt.com/g/g-p-demo/project"
    assert onboarding.is_chatgpt_project_url(requested) is True
    assert onboarding.same_chatgpt_project(requested, requested) is True
    assert onboarding.same_chatgpt_project(requested + "?foo=bar", requested) is True
    assert onboarding.is_chatgpt_project_url("https://chatgpt.com/auth/login") is False
    assert onboarding.same_chatgpt_project("https://chatgpt.com/g/g-p-other/project", requested) is False
    assert onboarding.is_chatgpt_project_url("https://example.com/g/g-p-demo/project") is False


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


def test_entrypoint_registers_account_auth_project_discovery_and_strict_doctor():
    parser = account_cli.build_parser()
    auth = parser.parse_args([
        "review", "auth", "authorize", "ds1david", "--account-label", "owner-plus",
    ])
    assert auth.func is account_cli.cmd_auth_authorize
    assert auth.profile == "ds1david"
    assert auth.account_label == "owner-plus"

    project = parser.parse_args([
        "review", "project", "select", "--profile", "webflow", "--index", "2", "--path", ".",
    ])
    assert project.func is account_cli.cmd_project_select
    assert project.profile == "webflow"
    assert project.index == 2

    manual = parser.parse_args([
        "review", "project", "select", "--profile", "webflow", "--manual", "--path", ".",
    ])
    assert manual.manual is True

    use = parser.parse_args([
        "review", "project", "use", "atsel", "--profile", "webflow", "--path", ".",
    ])
    assert use.func is account_cli.cmd_project_use
    assert use.profile == "webflow"

    doctor = parser.parse_args(["doctor", ".", "--strict-review"])
    assert doctor.func is account_cli.cmd_doctor
    assert doctor.strict_review is True


def test_legacy_project_scoped_commands_are_deprecated():
    parser = account_cli.build_parser()
    args = parser.parse_args([
        "review", "authorize",
        "--profile", "atsel", "--project", "atsel",
        "--url", "https://chatgpt.com/g/g-p-demo/project",
    ])
    assert args.func is account_cli.cmd_legacy_authorize_deprecated

    bind = parser.parse_args([
        "review", "project", "bind", "atsel", "https://chatgpt.com/g/g-p-demo/project",
    ])
    assert bind.func is account_cli.cmd_legacy_project_bind_deprecated


def _prepare_account_state(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.json"
    state: dict = {
        "schema_version": 3,
        "active_profiles": {"linux": "ds1david"},
        "accounts": {
            "linux": {
                "ds1david": {
                    "source": account_cli.ACCOUNT_AUTH_SOURCE,
                    "account_label": "owner-plus",
                    "profile_dir": str(tmp_path / "profiles" / "ds1david"),
                },
                "webflow": {
                    "source": account_cli.ACCOUNT_AUTH_SOURCE,
                    "account_label": "shared-plus",
                    "profile_dir": str(tmp_path / "profiles" / "webflow"),
                },
            }
        },
        "projects": {},
    }
    for profile in ("ds1david", "webflow"):
        (tmp_path / "profiles" / profile).mkdir(parents=True, exist_ok=True)

    def global_config():
        return config_path, state

    def save_global(path: Path, data: dict):
        snapshot = json.loads(json.dumps(data))
        state.clear()
        state.update(snapshot)
        path.write_text(json.dumps(snapshot), encoding="utf-8")

    monkeypatch.setattr(cli, "global_config", global_config)
    monkeypatch.setattr(cli, "save_global", save_global)
    monkeypatch.setattr(account_cli.core, "global_config", global_config)
    monkeypatch.setattr(account_cli.core, "save_global", save_global)
    monkeypatch.setattr(account_cli.core, "platform_key", lambda *args, **kwargs: "linux")
    monkeypatch.setattr(account_cli.core, "profile_dir", lambda name, **kwargs: tmp_path / "profiles" / name)
    return state


def test_same_project_can_bind_owner_and_shared_account(tmp_path: Path, monkeypatch):
    state = _prepare_account_state(tmp_path, monkeypatch)
    project = tmp_path / "repo"
    review_path = project / ".specify" / "powerpack" / "review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps({"chatgpt_web": {"required": True, "enabled": True}}), encoding="utf-8")
    candidate = onboarding.ProjectCandidate("ATSEL", "https://chatgpt.com/g/g-p-demo/project")

    account_cli._persist_binding(alias="atsel", candidate=candidate, profile="ds1david", project_path=project)
    account_cli._persist_binding(alias="atsel", candidate=candidate, profile="webflow", project_path=project)

    bindings = state["projects"]["atsel"]["bindings"]["linux"]
    assert set(bindings) == {"ds1david", "webflow"}
    assert bindings["ds1david"]["account_label"] == "owner-plus"
    assert bindings["webflow"]["account_label"] == "shared-plus"

    review = json.loads(review_path.read_text(encoding="utf-8"))["chatgpt_web"]
    assert review["profile"] == "webflow"
    assert review["account_label"] == "shared-plus"
    assert review["authorization"] == account_cli.PROJECT_BINDING_AUTH


def test_review_readiness_is_bound_to_selected_account_identity(tmp_path: Path, monkeypatch):
    _prepare_account_state(tmp_path, monkeypatch)
    project = tmp_path / "repo"
    review_path = project / ".specify" / "powerpack" / "review.json"
    review_path.parent.mkdir(parents=True)
    candidate = onboarding.ProjectCandidate("ATSEL", "https://chatgpt.com/g/g-p-demo/project")
    review_path.write_text(json.dumps({"chatgpt_web": {"required": True, "enabled": True}}), encoding="utf-8")

    account_cli._persist_binding(alias="atsel", candidate=candidate, profile="ds1david", project_path=project)
    monkeypatch.setattr(account_cli.core, "playwright_package_ready", lambda: True)
    monkeypatch.setattr(account_cli.core, "playwright_browser_ready", lambda: True)

    readiness = account_cli.review_readiness(project)
    assert readiness["chatgpt-account-authenticated"] is True
    assert readiness["chatgpt-project-bound"] is True

    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["chatgpt_web"]["profile"] = "webflow"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    readiness = account_cli.review_readiness(project)
    assert readiness["chatgpt-account-authenticated"] is True
    assert readiness["chatgpt-project-bound"] is False


def test_project_use_requires_explicit_profile_when_same_project_has_two_accounts(tmp_path: Path, monkeypatch):
    state = _prepare_account_state(tmp_path, monkeypatch)
    state["active_profiles"]["linux"] = "other"
    registered = {
        "bindings": {
            "linux": {
                "ds1david": {"profile": "ds1david", "url": "https://chatgpt.com/g/g-p-demo/project"},
                "webflow": {"profile": "webflow", "url": "https://chatgpt.com/g/g-p-demo/project"},
            }
        }
    }
    try:
        account_cli._select_binding(registered, "linux", None)
    except cli.PowerPackError as exc:
        assert "--profile" in str(exc)
        assert "ds1david" in str(exc)
        assert "webflow" in str(exc)
    else:
        raise AssertionError("multiple account bindings should require an explicit profile when no active match exists")


def test_reauthorizing_profile_invalidates_old_project_binding(tmp_path: Path, monkeypatch):
    state = _prepare_account_state(tmp_path, monkeypatch)
    state["projects"] = {
        "atsel": {
            "bindings": {
                "linux": {
                    "ds1david": {
                        "profile": "ds1david",
                        "url": "https://chatgpt.com/g/g-p-demo/project",
                        "authorization": account_cli.PROJECT_BINDING_AUTH,
                    }
                }
            }
        }
    }
    result = onboarding.AccountAuthorizationResult(
        granted=True,
        profile="ds1david",
        platform="linux",
        profile_dir=str(tmp_path / "profiles" / "ds1david"),
        account_label="owner-plus-reconfigured",
        granted_at="2026-09-05T23:00:00+00:00",
    )
    invalidated = account_cli._persist_account(result)
    assert invalidated == ["atsel"]
    assert state["projects"]["atsel"]["bindings"]["linux"]["ds1david"]["authorization"] == account_cli.STALE_BINDING_AUTH