from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from . import cli as core
from . import cli_account_binding as base
from .review_onboarding import ProjectCandidate, authorize_chatgpt_account, is_chatgpt_project_url
from . import windows_browser_bridge as winbridge


WINDOWS_ACCOUNT_AUTH_SOURCE = "windows-browser-cdp-consent"
WINDOWS_ACCOUNT_BACKEND = "windows-browser-context"
ISOLATED_ACCOUNT_BACKEND = "isolated-playwright"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yes(prompt: str, *, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    value = input(prompt + suffix).strip().casefold()
    if not value:
        return default
    return value in {"y", "yes", "s", "sim"}


def _ask(prompt: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def _account_record(data: dict[str, Any], platform: str, profile: str | None) -> dict[str, Any] | None:
    if not profile:
        return None
    value = data.get("accounts", {}).get(platform, {}).get(profile)
    return value if isinstance(value, dict) else None


def _account_backend(record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    backend = record.get("backend")
    if backend:
        return str(backend)
    if record.get("source") == WINDOWS_ACCOUNT_AUTH_SOURCE:
        return WINDOWS_ACCOUNT_BACKEND
    if record.get("source") == base.ACCOUNT_AUTH_SOURCE:
        return ISOLATED_ACCOUNT_BACKEND
    return None


def _account_authorized(data: dict[str, Any], platform: str, profile: str | None) -> bool:
    record = _account_record(data, platform, profile)
    backend = _account_backend(record)
    if not profile or not record:
        return False
    if backend == WINDOWS_ACCOUNT_BACKEND:
        return bool(
            record.get("source") == WINDOWS_ACCOUNT_AUTH_SOURCE
            and record.get("remote_debugging_consent") is True
            and record.get("browser_channel") in {"chrome", "msedge"}
        )
    if backend == ISOLATED_ACCOUNT_BACKEND:
        return bool(
            record.get("source") == base.ACCOUNT_AUTH_SOURCE
            and core.profile_dir(profile, create=False).is_dir()
        )
    return False


def _require_account(profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, data = core.global_config()
    platform = core.platform_key()
    record = _account_record(data, platform, profile)
    if not _account_authorized(data, platform, profile) or not record:
        raise core.PowerPackError(
            f"Profile '{profile}' is not an authorized ChatGPT reviewer account on {platform}. "
            "Run 'speckit-powerpack review auth configure'."
        )
    return data, record


def _persist_windows_account(*, profile: str, account_label: str, browser_channel: str) -> list[str]:
    path, data = core.global_config()
    platform = core.platform_key()
    invalidated = base._invalidate_profile_bindings(data, platform, profile)
    record = {
        "source": WINDOWS_ACCOUNT_AUTH_SOURCE,
        "backend": WINDOWS_ACCOUNT_BACKEND,
        "account_label": account_label,
        "browser_channel": winbridge.normalize_browser_channel(browser_channel),
        "remote_debugging_consent": True,
        "session_name": winbridge.session_name_for(profile),
        "granted_at": utc_now(),
    }
    data["schema_version"] = max(4, int(data.get("schema_version", 0) or 0))
    data.setdefault("active_profiles", {})[platform] = profile
    data.setdefault("accounts", {}).setdefault(platform, {})[profile] = record
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {})[profile] = {
        "confirmed": True,
        "source": WINDOWS_ACCOUNT_AUTH_SOURCE,
        "backend": WINDOWS_ACCOUNT_BACKEND,
        "account_label": account_label,
        "granted_at": record["granted_at"],
    }
    core.save_global(path, data)
    return invalidated


def _persist_isolated_account(result) -> list[str]:
    invalidated = base._persist_account(result)
    path, data = core.global_config()
    platform = result.platform
    record = data.setdefault("accounts", {}).setdefault(platform, {}).setdefault(result.profile, {})
    record["backend"] = ISOLATED_ACCOUNT_BACKEND
    core.save_global(path, data)
    return invalidated


def _choose_existing_profile(data: dict[str, Any], platform: str) -> str | None:
    accounts = data.get("accounts", {}).get(platform, {})
    if not isinstance(accounts, dict) or not accounts:
        return None
    active = data.get("active_profiles", {}).get(platform)
    names = sorted(accounts)
    print("\nPerfis ChatGPT já cadastrados:")
    for index, name in enumerate(names, start=1):
        record = accounts.get(name) if isinstance(accounts.get(name), dict) else {}
        marker = "*" if name == active else " "
        print(
            f"  {index}. {marker} {name} | conta={record.get('account_label') or name} "
            f"| modo={_account_backend(record) or 'legacy'}"
        )
    print("  N. criar novo perfil")
    choice = input("Escolha um perfil para reconfigurar ou N para novo [N]: ").strip()
    if not choice or choice.casefold() in {"n", "novo", "new"}:
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1]
    if choice in names:
        return choice
    raise core.PowerPackError("Seleção de perfil inválida.")


def _choose_mode(default: str = WINDOWS_ACCOUNT_BACKEND) -> str:
    print("\nComo o PowerPack deve acessar o ChatGPT Web?")
    print("  1. Reutilizar o contexto do meu Edge/Chrome do Windows (recomendado para Google/SSO/MFA)")
    print("  2. Usar Chromium isolado do PowerPack")
    default_number = "1" if default == WINDOWS_ACCOUNT_BACKEND else "2"
    choice = _ask("Modo", default=default_number)
    if choice in {"1", "windows", "edge", "chrome"}:
        return WINDOWS_ACCOUNT_BACKEND
    if choice in {"2", "isolated", "isolado", "chromium"}:
        return ISOLATED_ACCOUNT_BACKEND
    raise core.PowerPackError("Modo de autenticação inválido.")


def _choose_browser(default: str = "msedge") -> str:
    print("\nNavegador do Windows:")
    print("  1. Microsoft Edge")
    print("  2. Google Chrome")
    default_number = "1" if default == "msedge" else "2"
    choice = _ask("Navegador", default=default_number)
    if choice in {"1", "edge", "msedge"}:
        return "msedge"
    if choice in {"2", "chrome"}:
        return "chrome"
    raise core.PowerPackError("Navegador inválido.")


def _configure_windows_account(*, profile: str, account_label: str, browser_channel: str) -> None:
    if not winbridge.is_wsl():
        raise core.PowerPackError("O modo de contexto do navegador Windows só está disponível quando o PowerPack roda no WSL.")
    try:
        winbridge.ensure_windows_playwright_cli()
        winbridge.open_remote_debugging_settings(browser_channel)
    except winbridge.WindowsBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc

    inspect_url = winbridge.WINDOWS_INSPECT_URLS[winbridge.normalize_browser_channel(browser_channel)]
    print("\nO PowerPack abriu as configurações de depuração remota no navegador do Windows.")
    print(f"Se necessário, navegue manualmente para: {inspect_url}")
    print("Ative 'Allow remote debugging for this browser instance'.")
    print("Essa autorização permite ao Playwright controlar/inspecionar abas DESSE navegador enquanto o gate estiver em execução.")
    print("O PowerPack não copia cookies, senhas, tokens OAuth ou o perfil do navegador para o WSL.")
    if not _yes("Conceder essa permissão de automação ao PowerPack?", default=False):
        raise core.PowerPackError("Autorização do contexto Windows cancelada.")
    input("Depois de habilitar a depuração remota e manter o navegador aberto, pressione Enter... ")

    try:
        session = winbridge.attach_existing_browser(profile=profile, browser_channel=browser_channel)
        winbridge.open_chatgpt_tab(session)
    except winbridge.WindowsBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc

    print("\nUma nova aba do ChatGPT foi aberta NO SEU navegador do Windows.")
    print("Faça login, troque de conta ou conclua Google/SSO/MFA normalmente nesse navegador.")
    print("Quando a interface normal do ChatGPT e o campo de mensagem estiverem visíveis, volte ao terminal.")
    input("Pressione Enter para o PowerPack validar a sessão... ")

    try:
        evidence = winbridge.validate_existing_windows_chatgpt_session(
            profile=profile,
            browser_channel=browser_channel,
            open_tab=False,
        )
    except winbridge.WindowsBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc

    print(f"Sessão ChatGPT validada: {evidence.get('title') or evidence.get('href')}")
    if not _yes(f"Confirmar que essa sessão representa a conta '{account_label}' que fará o review Web?", default=False):
        raise core.PowerPackError("Identidade da conta não confirmada; nenhuma autorização foi gravada.")

    invalidated = _persist_windows_account(
        profile=profile,
        account_label=account_label,
        browser_channel=browser_channel,
    )
    print(f"Conta '{account_label}' autorizada no perfil lógico '{profile}' usando {browser_channel} do Windows.")
    if invalidated:
        print("Bindings anteriores foram marcados como stale e devem ser revalidados: " + ", ".join(sorted(set(invalidated))))


def _configure_isolated_account(*, profile: str, account_label: str, fresh: bool) -> None:
    profile_path = core.profile_dir(profile)
    if fresh and profile_path.exists():
        shutil.rmtree(profile_path)
        profile_path = core.profile_dir(profile)
    try:
        result = authorize_chatgpt_account(
            config_root=core.global_root(),
            platform=core.platform_key(),
            profile=profile,
            profile_dir=profile_path,
            account_label=account_label,
        )
    except RuntimeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    if not result.granted:
        raise core.PowerPackError("Autorização isolada cancelada; nenhuma conta foi gravada.")
    invalidated = _persist_isolated_account(result)
    print(f"Conta '{account_label}' autorizada no Chromium isolado '{profile}'.")
    if invalidated:
        print("Bindings anteriores foram marcados como stale e devem ser revalidados: " + ", ".join(sorted(set(invalidated))))


def interactive_configure(*, requested_profile: str | None = None, requested_label: str | None = None, fresh: bool = False) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    profile = requested_profile or _choose_existing_profile(data, platform)
    if not profile:
        profile = _ask("Nome lógico do perfil PowerPack", default="chatgpt-review")
    if not profile:
        raise core.PowerPackError("O perfil é obrigatório.")

    existing = _account_record(data, platform, profile)
    if existing and _account_authorized(data, platform, profile):
        print(
            f"\nJá existe uma autorização válida para '{profile}' "
            f"(conta={existing.get('account_label') or profile}, modo={_account_backend(existing)})."
        )
        if not _yes("Deseja substituir essa autorização?", default=False):
            print("Autorização atual preservada; nenhuma alteração realizada.")
            return

    account_label = requested_label or _ask(
        "Identificação local da conta ChatGPT",
        default=str((existing or {}).get("account_label") or profile),
    )
    default_backend = _account_backend(existing) or (WINDOWS_ACCOUNT_BACKEND if winbridge.is_wsl() else ISOLATED_ACCOUNT_BACKEND)
    backend = _choose_mode(default_backend)

    if backend == WINDOWS_ACCOUNT_BACKEND:
        default_browser = str((existing or {}).get("browser_channel") or "msedge")
        browser = _choose_browser(default_browser)
        _configure_windows_account(profile=profile, account_label=account_label, browser_channel=browser)
        return

    if existing and not fresh:
        fresh = _yes("Apagar apenas o Chromium isolado anterior deste perfil e iniciar uma sessão limpa?", default=False)
    _configure_isolated_account(profile=profile, account_label=account_label, fresh=fresh)


def cmd_auth_configure(args: argparse.Namespace) -> None:
    interactive_configure()


def cmd_auth_reconfigure(args: argparse.Namespace) -> None:
    interactive_configure(
        requested_profile=getattr(args, "profile", None),
        requested_label=getattr(args, "account_label", None),
        fresh=bool(getattr(args, "fresh", False)),
    )


def cmd_auth_list(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    active = data.get("active_profiles", {}).get(platform)
    accounts = data.get("accounts", {}).get(platform, {})
    if not isinstance(accounts, dict) or not accounts:
        print("Nenhuma conta ChatGPT autorizada nesta plataforma.")
        return
    for profile, raw in sorted(accounts.items()):
        record = raw if isinstance(raw, dict) else {}
        marker = "*" if profile == active else " "
        extra = ""
        if _account_backend(record) == WINDOWS_ACCOUNT_BACKEND:
            extra = f" browser={record.get('browser_channel')}"
        print(
            f"{marker} {profile}: account={record.get('account_label') or profile} "
            f"backend={_account_backend(record) or 'legacy'}{extra} platform={platform}"
        )


def cmd_auth_use(args: argparse.Namespace) -> None:
    path, data = core.global_config()
    platform = core.platform_key()
    if not _account_authorized(data, platform, args.profile):
        raise core.PowerPackError(f"Perfil '{args.profile}' não possui uma autorização válida em {platform}.")
    data.setdefault("active_profiles", {})[platform] = args.profile
    core.save_global(path, data)
    print(f"Perfil ChatGPT ativo: '{args.profile}'.")
    print("O reviewer Web do repositório só muda depois de project use/select/add com esse perfil.")


def cmd_auth_validate(args: argparse.Namespace) -> None:
    profile = getattr(args, "profile", None) or base._profile_for(args)
    _, record = _require_account(profile)
    backend = _account_backend(record)
    if backend == WINDOWS_ACCOUNT_BACKEND:
        try:
            evidence = winbridge.validate_existing_windows_chatgpt_session(
                profile=profile,
                browser_channel=str(record.get("browser_channel")),
                open_tab=True,
            )
        except winbridge.WindowsBrowserBridgeError as exc:
            raise core.PowerPackError(str(exc)) from exc
        print(
            f"OK profile={profile} account={record.get('account_label') or profile} "
            f"backend={backend} browser={record.get('browser_channel')} url={evidence.get('href')}"
        )
        return
    if backend == ISOLATED_ACCOUNT_BACKEND:
        if not core.profile_dir(profile, create=False).is_dir():
            raise core.PowerPackError("O diretório do perfil Chromium isolado não existe mais.")
        print(f"OK profile={profile} account={record.get('account_label') or profile} backend={backend} configured=true")
        return
    raise core.PowerPackError("Backend de autenticação desconhecido.")


def cmd_auth_logout(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    record = _account_record(data, platform, args.profile)
    if _account_backend(record) != WINDOWS_ACCOUNT_BACKEND:
        base.cmd_auth_logout(args)
        return
    path, data = core.global_config()
    invalidated = base._invalidate_profile_bindings(data, platform, args.profile)
    data.setdefault("accounts", {}).setdefault(platform, {}).pop(args.profile, None)
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {}).pop(args.profile, None)
    if data.setdefault("active_profiles", {}).get(platform) == args.profile:
        data["active_profiles"].pop(platform, None)
    core.save_global(path, data)
    print(f"Autorização PowerPack removida para '{args.profile}'.")
    print("A conta NÃO foi desconectada do Edge/Chrome do Windows; o PowerPack não altera a sessão pessoal do navegador.")
    if invalidated:
        print("Bindings marcados como stale: " + ", ".join(sorted(set(invalidated))))


def _persist_binding(*, alias: str, candidate: ProjectCandidate, profile: str, project_path: Path) -> None:
    cfg_path, data = core.global_config()
    platform = core.platform_key()
    _, account = _require_account(profile)
    registered = data.setdefault("projects", {}).setdefault(alias, {"bindings": {}})
    registered["display_name"] = candidate.name
    platform_bindings = registered.setdefault("bindings", {}).setdefault(platform, {})
    if isinstance(platform_bindings, dict) and "url" in platform_bindings and "profile" in platform_bindings:
        legacy = dict(platform_bindings)
        legacy_profile = str(legacy.get("profile") or "legacy")
        registered["bindings"][platform] = {legacy_profile: legacy}
        platform_bindings = registered["bindings"][platform]
    platform_bindings[profile] = {
        "url": core.validate_project_url(candidate.url),
        "profile": profile,
        "account_label": account.get("account_label") or profile,
        "account_backend": _account_backend(account),
        "browser_channel": account.get("browser_channel"),
        "authorization": base.PROJECT_BINDING_AUTH,
    }
    data.setdefault("active_profiles", {})[platform] = profile
    core.save_global(cfg_path, data)

    review_path, review = base._review_config(project_path)
    web = review.setdefault("chatgpt_web", {})
    web["required"] = True
    web["enabled"] = True
    web["project_alias"] = alias
    web["project_url"] = candidate.url
    web["project_name"] = candidate.name
    web["profile"] = profile
    web["account_label"] = account.get("account_label") or profile
    web["account_backend"] = _account_backend(account)
    web["browser_channel"] = account.get("browser_channel")
    web["profile_scope"] = "platform"
    web["profile_platform"] = platform
    web["authorization"] = base.PROJECT_BINDING_AUTH
    core.write_json(review_path, review, overwrite=True)
    print(
        f"Repository bound to ChatGPT Project '{candidate.name}' as '{alias}' using "
        f"account '{account.get('account_label') or profile}' ({_account_backend(account)})."
    )


def _discover(profile: str) -> list[ProjectCandidate]:
    _, account = _require_account(profile)
    if _account_backend(account) != WINDOWS_ACCOUNT_BACKEND:
        return base._discover(profile)
    try:
        values = winbridge.discover_projects(profile=profile, browser_channel=str(account.get("browser_channel")))
    except winbridge.WindowsBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    return [ProjectCandidate(item.name, item.url) for item in values]


def _manual_project(profile: str) -> ProjectCandidate:
    _, account = _require_account(profile)
    if _account_backend(account) != WINDOWS_ACCOUNT_BACKEND:
        return base._manual_project(profile)
    url = _ask("Cole a URL do Project que você abriu no navegador Windows")
    if not url:
        raise core.PowerPackError("URL do Project é obrigatória no modo manual.")
    try:
        item = winbridge.capture_project_from_url(
            profile=profile,
            browser_channel=str(account.get("browser_channel")),
            url=url,
            prompt="Confirme no navegador que o Project correto abriu; depois pressione Enter aqui.",
        )
    except winbridge.WindowsBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    return ProjectCandidate(item.name, item.url)


def cmd_project_discover(args: argparse.Namespace) -> None:
    profile = base._profile_for(args)
    projects = _discover(profile)
    if not projects:
        print("Nenhum Project foi descoberto. Use project select --manual, project add ou project accept-invite.")
        return
    for index, item in enumerate(projects, start=1):
        print(f"{index:2}. {item.name} | {item.url}")


def cmd_project_select(args: argparse.Namespace) -> None:
    profile = base._profile_for(args)
    if args.manual:
        candidate = _manual_project(profile)
    else:
        projects = _discover(profile)
        candidate = base._choose_project(projects, args.index) if projects else _manual_project(profile)
    alias = args.alias or base._local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def _capture_url(profile: str, url: str, *, prompt: str | None = None) -> ProjectCandidate:
    _, account = _require_account(profile)
    if _account_backend(account) != WINDOWS_ACCOUNT_BACKEND:
        try:
            item = base.open_link_and_capture_project(
                profile_dir=core.profile_dir(profile),
                url=url,
                purpose="ChatGPT Project verification" if not prompt else "ChatGPT Project invite/shared-link acceptance",
            )
        except RuntimeError as exc:
            raise core.PowerPackError(str(exc)) from exc
        return item
    try:
        item = winbridge.capture_project_from_url(
            profile=profile,
            browser_channel=str(account.get("browser_channel")),
            url=url,
            prompt=prompt,
        )
    except winbridge.WindowsBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    return ProjectCandidate(item.name, item.url)


def cmd_project_add(args: argparse.Namespace) -> None:
    profile = base._profile_for(args)
    if not is_chatgpt_project_url(args.url):
        raise core.PowerPackError("Expected a ChatGPT Project URL ending in /project.")
    candidate = _capture_url(profile, args.url)
    alias = args.alias or base._local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def cmd_project_accept_invite(args: argparse.Namespace) -> None:
    profile = base._profile_for(args)
    candidate = _capture_url(
        profile,
        args.url,
        prompt="Aceite o convite/compartilhamento no navegador Windows, navegue até o Project final e pressione Enter aqui.",
    )
    alias = args.alias or base._local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def cmd_project_use(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    _, data = core.global_config()
    platform = core.platform_key()
    registered = data.get("projects", {}).get(args.alias)
    if not isinstance(registered, dict):
        raise core.PowerPackError(f"Unknown project alias: {args.alias}")
    profile, binding = base._select_binding(registered, platform, getattr(args, "profile", None))
    _require_account(profile)
    if binding.get("authorization") != base.PROJECT_BINDING_AUTH:
        raise core.PowerPackError("Project binding is stale/legacy; re-select/add it with the desired account.")
    candidate = ProjectCandidate(name=registered.get("display_name") or args.alias, url=binding["url"])
    _persist_binding(alias=args.alias, candidate=candidate, profile=profile, project_path=project)


def review_readiness(project: Path, *, live: bool = False) -> dict[str, bool]:
    try:
        _, review = base._review_config(project)
    except core.PowerPackError:
        result = {
            "web-review-required": False,
            "playwright-package": core.playwright_package_ready(),
            "playwright-browser": core.playwright_browser_ready(),
            "chatgpt-account-authenticated": False,
            "chatgpt-project-bound": False,
        }
        if live:
            result["chatgpt-browser-session-live"] = False
        return result
    web = review.get("chatgpt_web", {}) if isinstance(review, dict) else {}
    if not isinstance(web, dict):
        web = {}
    platform = core.platform_key()
    profile = web.get("profile")
    alias = web.get("project_alias")
    url = web.get("project_url")
    _, data = core.global_config()
    account_ok = _account_authorized(data, platform, profile)
    registered = data.get("projects", {}).get(alias) if alias else None
    binding = base._binding_for(registered, platform, profile) if isinstance(registered, dict) else None
    project_ok = bool(
        account_ok
        and alias
        and url
        and isinstance(binding, dict)
        and binding.get("profile") == profile
        and binding.get("url") == url
        and binding.get("authorization") == base.PROJECT_BINDING_AUTH
        and web.get("authorization") == base.PROJECT_BINDING_AUTH
    )
    result = {
        "web-review-required": bool(web.get("required") and web.get("enabled")),
        "playwright-package": core.playwright_package_ready(),
        "playwright-browser": core.playwright_browser_ready(),
        "chatgpt-account-authenticated": account_ok,
        "chatgpt-project-bound": project_ok,
    }
    if live:
        live_ok = account_ok
        record = _account_record(data, platform, profile)
        if account_ok and _account_backend(record) == WINDOWS_ACCOUNT_BACKEND:
            try:
                winbridge.validate_existing_windows_chatgpt_session(
                    profile=str(profile),
                    browser_channel=str(record.get("browser_channel")),
                    open_tab=False,
                )
            except winbridge.WindowsBrowserBridgeError:
                live_ok = False
        result["chatgpt-browser-session-live"] = bool(live_ok)
    return result


def print_review_setup_status(project: Path) -> None:
    readiness = review_readiness(project)
    if all(readiness.values()):
        print("Mandatory ChatGPT Web review is configured: account and Project binding are present.")
        return
    print("\nCHATGPT WEB REVIEW SETUP")
    if not readiness["chatgpt-account-authenticated"]:
        print("1. Configure/reconfigure a reviewer account interactively:")
        print("   speckit-powerpack review auth configure")
    if not readiness["chatgpt-project-bound"]:
        print("2. Discover/select a Project and bind it to this repository:")
        print("   speckit-powerpack review project select --path .")
    print("For Windows Google/SSO/MFA accounts, choose the Windows browser-context mode during auth configuration.")
    print("Use 'speckit-powerpack doctor --strict-review' immediately before implement-review.\n")


def cmd_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    runtime = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    specify_binary = shutil.which("specify")
    current_spec_kit = core.specify_version(specify_binary) if specify_binary else None
    integration = core.project_integration(project)
    readiness = review_readiness(project, live=bool(args.strict_review))
    hard_checks = {
        "specify": bool(specify_binary),
        "spec-kit-compatible": core.spec_kit_compatible(current_spec_kit),
        "spec-kit-project": (project / ".specify").is_dir(),
        "powerpack-runtime": runtime.is_file(),
        "capability-resolver": runtime.with_name("capabilities.py").is_file(),
        "review-protocol-validator": runtime.with_name("review_protocol.py").is_file(),
        "technical-debt-runtime": runtime.with_name("debt.py").is_file(),
        "full-cycle-runtime": runtime.with_name("full_cycle.py").is_file(),
        "selected-executor": bool(shutil.which(integration)),
    }
    print(f"Platform:    {core.platform_key()} ({core.platform_module.system()})")
    print(f"Config:      {core.global_root()}")
    print(f"Integration: {integration}")
    print(f"Spec Kit:    {current_spec_kit or 'unknown'} (requires >= {core.SPECKIT_MIN_VERSION_TEXT})")
    for key, ok in hard_checks.items():
        print(f"{'OK' if ok else 'FAIL':5} {key}")
    for key, ok in readiness.items():
        print(f"{'OK' if ok else 'SETUP':5} {key}")
    if not all(hard_checks.values()):
        raise core.PowerPackError("PowerPack installation checks failed.")
    if args.strict_review and not all(readiness.values()):
        print_review_setup_status(project)
        raise core.PowerPackError("Mandatory ChatGPT Web review is not ready.")
    if not all(readiness.values()):
        print_review_setup_status(project)
        print("Installation is healthy; ChatGPT Web review onboarding is incomplete.")


def _find_action(parser: argparse.ArgumentParser, dest: str):
    for action in parser._actions:
        if action.dest == dest:
            return action
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = base.build_parser()
    root = base._subparsers(parser)

    doctor = root.choices["doctor"]
    doctor.set_defaults(func=cmd_doctor)

    review = root.choices["review"]
    rsub = base._subparsers(review)
    auth = rsub.choices["auth"]
    asub = base._subparsers(auth)

    configure = asub.add_parser("configure", help="Interactive ChatGPT reviewer-account configuration")
    configure.set_defaults(func=cmd_auth_configure)

    reconfigure = asub.choices["reconfigure"]
    profile_action = _find_action(reconfigure, "profile")
    if profile_action is not None:
        profile_action.nargs = "?"
        profile_action.default = None
    reconfigure.set_defaults(func=cmd_auth_reconfigure)

    asub.choices["list"].set_defaults(func=cmd_auth_list)
    asub.choices["use"].set_defaults(func=cmd_auth_use)
    asub.choices["logout"].set_defaults(func=cmd_auth_logout)

    validate = asub.add_parser("validate", help="Validate the currently authorized reviewer account/session")
    validate.add_argument("profile", nargs="?")
    validate.set_defaults(func=cmd_auth_validate)

    project = rsub.choices["project"]
    psub = base._subparsers(project)
    psub.choices["discover"].set_defaults(func=cmd_project_discover)
    psub.choices["select"].set_defaults(func=cmd_project_select)
    psub.choices["add"].set_defaults(func=cmd_project_add)
    psub.choices["accept-invite"].set_defaults(func=cmd_project_accept_invite)
    psub.choices["use"].set_defaults(func=cmd_project_use)
    return parser


def main(argv: list[str] | None = None) -> int:
    core.review_readiness = lambda project: review_readiness(project)
    core.print_review_setup_status = print_review_setup_status
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
        return 0
    except (core.PowerPackError, core.UpdateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


core.review_readiness = lambda project: review_readiness(project)
core.print_review_setup_status = print_review_setup_status
