from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from . import cli as core
from . import cli_account_binding as account_base
from . import cli_interactive_auth as previous
from . import desktop_browser_bridge as desktop
from .review_onboarding import ProjectCandidate, authorize_chatgpt_account, is_chatgpt_project_url


DESKTOP_ACCOUNT_AUTH_SOURCE = "desktop-browser-context-consent"
DESKTOP_ACCOUNT_BACKEND = "desktop-browser-context"
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
    if backend in {DESKTOP_ACCOUNT_BACKEND, previous.WINDOWS_ACCOUNT_BACKEND, ISOLATED_ACCOUNT_BACKEND}:
        return DESKTOP_ACCOUNT_BACKEND if backend == previous.WINDOWS_ACCOUNT_BACKEND else str(backend)
    if record.get("source") in {DESKTOP_ACCOUNT_AUTH_SOURCE, previous.WINDOWS_ACCOUNT_AUTH_SOURCE}:
        return DESKTOP_ACCOUNT_BACKEND
    if record.get("source") == account_base.ACCOUNT_AUTH_SOURCE:
        return ISOLATED_ACCOUNT_BACKEND
    return str(backend) if backend else None


def _account_authorized(data: dict[str, Any], platform: str, profile: str | None) -> bool:
    record = _account_record(data, platform, profile)
    backend = _account_backend(record)
    if not profile or not record:
        return False
    if backend == DESKTOP_ACCOUNT_BACKEND:
        return bool(
            record.get("source") in {DESKTOP_ACCOUNT_AUTH_SOURCE, previous.WINDOWS_ACCOUNT_AUTH_SOURCE}
            and record.get("remote_debugging_consent") is True
            and (record.get("automation_browser_id") or record.get("browser_channel"))
        )
    if backend == ISOLATED_ACCOUNT_BACKEND:
        return bool(
            record.get("source") == account_base.ACCOUNT_AUTH_SOURCE
            and core.profile_dir(profile, create=False).is_dir()
        )
    return False


def _require_account(profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, data = core.global_config()
    platform = core.platform_key()
    record = _account_record(data, platform, profile)
    if not _account_authorized(data, platform, profile) or not record:
        raise core.PowerPackError(
            f"Perfil '{profile}' não possui autorização válida para ChatGPT Web. "
            "Execute 'speckit-powerpack review auth configure'."
        )
    return data, record


def _print_environment(env: desktop.DesktopEnvironment, browsers: list[desktop.BrowserCandidate]) -> None:
    print("\nAmbiente de navegador detectado:")
    print(f"  runtime: {env.runtime_os}")
    print(f"  host de navegador: {env.host_scope}")
    print(f"  WSL: {'sim' if env.is_wsl else 'não'}")
    if env.desktop:
        print(f"  desktop: {env.desktop}")
    if env.display_server:
        print(f"  display: {env.display_server}")
    if browsers:
        print("  navegadores detectados:")
        for browser in browsers:
            capability = {
                "channel-cdp": "review automatizável (attach direto)",
                "endpoint-cdp": "review automatizável via endpoint CDP",
                "manual-only": "login/manual apenas; sem attach de sessão existente",
            }.get(browser.automation, browser.automation)
            print(f"    - {browser.label}: {capability}")
    else:
        print("  navegadores detectados: nenhum conhecido; o navegador padrão ainda pode ser aberto pelo sistema")


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


def _choose_mode(default: str, env: desktop.DesktopEnvironment) -> str:
    print("\nComo o PowerPack deve acessar o ChatGPT Web?")
    print(f"  1. Reutilizar um navegador do desktop/host ({env.host_scope}) com consentimento explícito")
    print("  2. Usar Chromium isolado do PowerPack")
    default_number = "1" if default == DESKTOP_ACCOUNT_BACKEND else "2"
    choice = _ask("Modo", default=default_number).casefold()
    if choice in {"1", "desktop", "host", "browser", "navegador"}:
        return DESKTOP_ACCOUNT_BACKEND
    if choice in {"2", "isolated", "isolado", "chromium"}:
        return ISOLATED_ACCOUNT_BACKEND
    raise core.PowerPackError("Modo de autenticação inválido.")


def _choose_browser(
    browsers: list[desktop.BrowserCandidate],
    *,
    title: str,
    allow_default: bool,
    automatable_only: bool = False,
    default_id: str | None = None,
) -> desktop.BrowserCandidate | None:
    options = [b for b in browsers if (b.automatable_existing_context or not automatable_only)]
    if not options and automatable_only:
        raise core.PowerPackError(
            "Nenhum navegador Chromium automatizável foi detectado. "
            "Chrome/Edge usam attach direto; Chromium/Opera/Brave podem usar endpoint CDP."
        )
    print(f"\n{title}")
    offset = 1
    if allow_default:
        print("  0. Navegador padrão do sistema")
    for index, browser in enumerate(options, start=offset):
        suffix = ""
        if browser.automation == "manual-only":
            suffix = " [login/manual; não pode ser o backend final de review]"
        elif browser.automation == "endpoint-cdp":
            suffix = " [requer endpoint CDP]"
        print(f"  {index}. {browser.label}{suffix}")
    default_number = None
    if default_id:
        for index, browser in enumerate(options, start=offset):
            if browser.browser_id == default_id:
                default_number = str(index)
                break
    if allow_default and default_number is None:
        default_number = "0"
    choice = _ask("Navegador", default=default_number).strip()
    if allow_default and choice == "0":
        return None
    if choice.isdigit():
        value = int(choice)
        if offset <= value < offset + len(options):
            return options[value - offset]
    for browser in options:
        if choice.casefold() in {browser.browser_id.casefold(), browser.label.casefold()}:
            return browser
    raise core.PowerPackError("Seleção de navegador inválida.")


def _open_login_with_fallback(
    *,
    env: desktop.DesktopEnvironment,
    browsers: list[desktop.BrowserCandidate],
    default_browser_id: str | None = None,
) -> desktop.BrowserCandidate | None:
    login_browser = _choose_browser(
        browsers,
        title="Onde abrir o ChatGPT primeiro?",
        allow_default=True,
        automatable_only=False,
        default_id=default_browser_id,
    )
    try:
        desktop.open_url("https://chatgpt.com/", browser=login_browser, env=env)
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc

    while True:
        label = login_browser.label if login_browser else "navegador padrão"
        print(f"\nChatGPT aberto em: {label}.")
        print("Conclua login/Google/SSO/MFA nesse navegador. Se ele não funcionar, escolha um navegador alternativo.")
        choice = input("[Enter]=login concluído  [A]=abrir em outro navegador  [C]=cancelar: ").strip().casefold()
        if choice in {"", "ok", "done"}:
            return login_browser
        if choice in {"c", "cancelar", "cancel"}:
            raise core.PowerPackError("Configuração de autenticação cancelada.")
        if choice in {"a", "alternativo", "alternate", "outro"}:
            login_browser = _choose_browser(
                browsers,
                title="Escolha outro navegador para tentar o login",
                allow_default=True,
                automatable_only=False,
            )
            try:
                desktop.open_url("https://chatgpt.com/", browser=login_browser, env=env)
            except desktop.DesktopBrowserBridgeError as exc:
                print(f"Falha ao abrir navegador: {exc}")
            continue
        print("Opção inválida.")


def _browser_for_record(record: dict[str, Any], browsers: list[desktop.BrowserCandidate]) -> desktop.BrowserCandidate:
    browser_id = str(record.get("automation_browser_id") or record.get("browser_channel") or "")
    browser = desktop.browser_by_id(browser_id, browsers)
    if browser:
        return browser
    automation = str(record.get("browser_automation") or "channel-cdp")
    channel = record.get("cdp_channel") or (browser_id if browser_id in {"chrome", "msedge"} else None)
    return desktop.BrowserCandidate(
        browser_id=browser_id or "configured-browser",
        label=str(record.get("automation_browser_label") or browser_id or "Configured browser"),
        executable=None,
        automation=automation,
        cdp_channel=str(channel) if channel else None,
        inspect_url=str(record.get("inspect_url")) if record.get("inspect_url") else None,
        host_scope=str(record.get("host_scope") or desktop.detect_environment().host_scope),
    )


def _persist_desktop_account(
    *,
    profile: str,
    account_label: str,
    env: desktop.DesktopEnvironment,
    login_browser: desktop.BrowserCandidate | None,
    automation_browser: desktop.BrowserCandidate,
    cdp_endpoint: str | None,
) -> list[str]:
    path, data = core.global_config()
    platform = core.platform_key()
    invalidated = account_base._invalidate_profile_bindings(data, platform, profile)
    record = {
        "source": DESKTOP_ACCOUNT_AUTH_SOURCE,
        "backend": DESKTOP_ACCOUNT_BACKEND,
        "account_label": account_label,
        "host_scope": env.host_scope,
        "desktop_environment": env.desktop,
        "display_server": env.display_server,
        "login_browser_id": login_browser.browser_id if login_browser else "system-default",
        "automation_browser_id": automation_browser.browser_id,
        "automation_browser_label": automation_browser.label,
        "browser_automation": automation_browser.automation,
        "cdp_channel": automation_browser.cdp_channel,
        "cdp_endpoint": cdp_endpoint,
        "inspect_url": automation_browser.inspect_url,
        "remote_debugging_consent": True,
        "session_name": f"speckit-powerpack-{profile}",
        "granted_at": utc_now(),
    }
    data["schema_version"] = max(5, int(data.get("schema_version", 0) or 0))
    data.setdefault("active_profiles", {})[platform] = profile
    data.setdefault("accounts", {}).setdefault(platform, {})[profile] = record
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {})[profile] = {
        "confirmed": True,
        "source": DESKTOP_ACCOUNT_AUTH_SOURCE,
        "backend": DESKTOP_ACCOUNT_BACKEND,
        "account_label": account_label,
        "host_scope": env.host_scope,
        "granted_at": record["granted_at"],
    }
    core.save_global(path, data)
    return invalidated


def _configure_desktop_account(*, profile: str, account_label: str, existing: dict[str, Any] | None) -> None:
    env = desktop.detect_environment()
    browsers = desktop.detect_browsers(env)
    _print_environment(env, browsers)

    default_login = str((existing or {}).get("login_browser_id") or "") or None
    login_browser = _open_login_with_fallback(env=env, browsers=browsers, default_browser_id=default_login)

    automatable = [b for b in browsers if b.automatable_existing_context]
    if login_browser and login_browser.automation == "manual-only":
        print(
            f"\n{login_browser.label} funcionou como navegador de login/manual, mas Playwright não consegue anexar "
            "a sessão existente dele para o review automático. Escolha abaixo um navegador Chromium compatível "
            "e autentique a mesma conta nele também."
        )
    default_automation = None
    if login_browser and login_browser.automatable_existing_context:
        default_automation = login_browser.browser_id
    elif existing:
        default_automation = str(existing.get("automation_browser_id") or "") or None
    automation_browser = _choose_browser(
        automatable,
        title="Qual navegador será controlado pelo PowerPack durante o code review Web?",
        allow_default=False,
        automatable_only=True,
        default_id=default_automation,
    )
    assert automation_browser is not None

    cdp_endpoint = None
    if automation_browser.automation == "channel-cdp":
        try:
            desktop.open_remote_debugging_settings(automation_browser, env=env)
        except desktop.DesktopBrowserBridgeError as exc:
            raise core.PowerPackError(str(exc)) from exc
        print(f"\nNo {automation_browser.label}, habilite 'Allow remote debugging for this browser instance'.")
        print("O navegador pode pedir uma confirmação adicional quando o PowerPack tentar anexar.")
    else:
        print(
            f"\n{automation_browser.label} é Chromium, mas não possui channel de attach direto reconhecido pelo Playwright."
        )
        print("Inicie/habilite esse navegador com um endpoint CDP e informe-o abaixo.")
        cdp_endpoint = _ask("Endpoint CDP", default=str((existing or {}).get("cdp_endpoint") or "http://127.0.0.1:9222"))

    print("\nPermissão solicitada:")
    print("- Playwright poderá inspecionar/controlar abas do navegador de automação enquanto o review estiver ativo.")
    print("- O PowerPack NÃO copia cookies, senhas, MFA, OAuth tokens ou o perfil do navegador para o repositório/WSL.")
    print("- A conta autenticada nesse navegador será a identidade do reviewer Web.")
    if not _yes("Conceder essa permissão ao PowerPack?", default=False):
        raise core.PowerPackError("Autorização de automação cancelada.")
    input("Depois de preparar o navegador e mantê-lo aberto, pressione Enter para conectar... ")

    try:
        session = desktop.attach_existing_browser(
            profile=profile,
            browser=automation_browser,
            cdp_endpoint=cdp_endpoint,
            env=env,
        )
        desktop.open_chatgpt_tab(session, env=env)
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc

    print(f"\nChatGPT aberto pelo Playwright em {automation_browser.label}.")
    print("Se essa conta ainda não estiver autenticada nesse navegador, conclua login/Google/SSO/MFA agora.")
    input("Quando o campo normal de mensagem do ChatGPT estiver visível, pressione Enter para validar... ")

    try:
        evidence = desktop.validate_existing_chatgpt_session(
            profile=profile,
            browser=automation_browser,
            cdp_endpoint=cdp_endpoint,
            open_tab=False,
            env=env,
        )
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc

    print(f"Sessão ChatGPT validada: {evidence.get('title') or evidence.get('href')}")
    if not _yes(f"Confirmar que essa sessão é a conta '{account_label}' que fará o review Web?", default=False):
        raise core.PowerPackError("Identidade da conta não confirmada; nenhuma autorização foi gravada.")

    invalidated = _persist_desktop_account(
        profile=profile,
        account_label=account_label,
        env=env,
        login_browser=login_browser,
        automation_browser=automation_browser,
        cdp_endpoint=cdp_endpoint,
    )
    print(
        f"Conta '{account_label}' autorizada como '{profile}' usando {automation_browser.label} "
        f"no host {env.host_scope}."
    )
    if invalidated:
        print("Bindings anteriores marcados como stale: " + ", ".join(sorted(set(invalidated))))


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
    invalidated = account_base._persist_account(result)
    path, data = core.global_config()
    record = data.setdefault("accounts", {}).setdefault(result.platform, {}).setdefault(result.profile, {})
    record["backend"] = ISOLATED_ACCOUNT_BACKEND
    core.save_global(path, data)
    print(f"Conta '{account_label}' autorizada no Chromium isolado '{profile}'.")
    if invalidated:
        print("Bindings anteriores marcados como stale: " + ", ".join(sorted(set(invalidated))))


def interactive_configure(*, requested_profile: str | None = None, requested_label: str | None = None, fresh: bool = False) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    env = desktop.detect_environment()
    profile = requested_profile or _choose_existing_profile(data, platform)
    if not profile:
        profile = _ask("Nome lógico do perfil PowerPack", default="chatgpt-review")
    if not profile:
        raise core.PowerPackError("O perfil é obrigatório.")

    existing = _account_record(data, platform, profile)
    if existing and _account_authorized(data, platform, profile):
        print(
            f"\nJá existe autorização válida para '{profile}' "
            f"(conta={existing.get('account_label') or profile}, modo={_account_backend(existing)})."
        )
        if not _yes("Deseja substituir a autorização anterior?", default=False):
            print("Autorização atual preservada.")
            return

    account_label = requested_label or _ask(
        "Identificação local da conta ChatGPT",
        default=str((existing or {}).get("account_label") or profile),
    )
    default_backend = _account_backend(existing) or DESKTOP_ACCOUNT_BACKEND
    backend = _choose_mode(default_backend, env)
    if backend == DESKTOP_ACCOUNT_BACKEND:
        _configure_desktop_account(profile=profile, account_label=account_label, existing=existing)
        return
    if existing and not fresh:
        fresh = _yes("Apagar apenas o Chromium isolado anterior deste perfil e iniciar sessão limpa?", default=False)
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
        if _account_backend(record) == DESKTOP_ACCOUNT_BACKEND:
            extra = f" host={record.get('host_scope')} browser={record.get('automation_browser_id') or record.get('browser_channel')}"
        print(
            f"{marker} {profile}: account={record.get('account_label') or profile} "
            f"backend={_account_backend(record) or 'legacy'}{extra} platform={platform}"
        )


def cmd_auth_use(args: argparse.Namespace) -> None:
    path, data = core.global_config()
    platform = core.platform_key()
    if not _account_authorized(data, platform, args.profile):
        raise core.PowerPackError(f"Perfil '{args.profile}' não possui autorização válida em {platform}.")
    data.setdefault("active_profiles", {})[platform] = args.profile
    core.save_global(path, data)
    print(f"Perfil ChatGPT ativo: '{args.profile}'.")
    print("O reviewer Web do repositório só muda após project use/select/add com esse perfil.")


def _validate_desktop_record(profile: str, record: dict[str, Any], *, open_tab: bool) -> dict:
    env = desktop.detect_environment()
    browsers = desktop.detect_browsers(env)
    browser = _browser_for_record(record, browsers)
    try:
        return desktop.validate_existing_chatgpt_session(
            profile=profile,
            browser=browser,
            cdp_endpoint=str(record.get("cdp_endpoint")) if record.get("cdp_endpoint") else None,
            open_tab=open_tab,
            env=env,
        )
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc


def cmd_auth_validate(args: argparse.Namespace) -> None:
    profile = getattr(args, "profile", None) or account_base._profile_for(args)
    _, record = _require_account(profile)
    backend = _account_backend(record)
    if backend == DESKTOP_ACCOUNT_BACKEND:
        evidence = _validate_desktop_record(profile, record, open_tab=True)
        print(
            f"OK profile={profile} account={record.get('account_label') or profile} "
            f"backend={backend} host={record.get('host_scope')} browser={record.get('automation_browser_id')} "
            f"url={evidence.get('href')}"
        )
        return
    if backend == ISOLATED_ACCOUNT_BACKEND:
        if not core.profile_dir(profile, create=False).is_dir():
            raise core.PowerPackError("O diretório do Chromium isolado não existe mais.")
        print(f"OK profile={profile} account={record.get('account_label') or profile} backend={backend} configured=true")
        return
    raise core.PowerPackError("Backend de autenticação desconhecido.")


def cmd_auth_logout(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    record = _account_record(data, platform, args.profile)
    if _account_backend(record) != DESKTOP_ACCOUNT_BACKEND:
        account_base.cmd_auth_logout(args)
        return
    path, data = core.global_config()
    invalidated = account_base._invalidate_profile_bindings(data, platform, args.profile)
    data.setdefault("accounts", {}).setdefault(platform, {}).pop(args.profile, None)
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {}).pop(args.profile, None)
    if data.setdefault("active_profiles", {}).get(platform) == args.profile:
        data["active_profiles"].pop(platform, None)
    core.save_global(path, data)
    print(f"Autorização PowerPack removida para '{args.profile}'.")
    print("O PowerPack não fez logout no navegador pessoal; apenas removeu sua própria autorização/binding.")
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
        "host_scope": account.get("host_scope"),
        "automation_browser_id": account.get("automation_browser_id") or account.get("browser_channel"),
        "browser_automation": account.get("browser_automation"),
        "cdp_endpoint": account.get("cdp_endpoint"),
        "authorization": account_base.PROJECT_BINDING_AUTH,
    }
    data.setdefault("active_profiles", {})[platform] = profile
    core.save_global(cfg_path, data)

    review_path, review = account_base._review_config(project_path)
    web = review.setdefault("chatgpt_web", {})
    web["required"] = True
    web["enabled"] = True
    web["project_alias"] = alias
    web["project_url"] = candidate.url
    web["project_name"] = candidate.name
    web["profile"] = profile
    web["account_label"] = account.get("account_label") or profile
    web["account_backend"] = _account_backend(account)
    web["host_scope"] = account.get("host_scope")
    web["automation_browser_id"] = account.get("automation_browser_id") or account.get("browser_channel")
    web["browser_automation"] = account.get("browser_automation")
    web["cdp_endpoint"] = account.get("cdp_endpoint")
    web["profile_scope"] = "platform"
    web["profile_platform"] = platform
    web["authorization"] = account_base.PROJECT_BINDING_AUTH
    core.write_json(review_path, review, overwrite=True)
    print(
        f"Repositório vinculado ao Project '{candidate.name}' como '{alias}' usando reviewer "
        f"'{account.get('account_label') or profile}' ({_account_backend(account)})."
    )


def _discover(profile: str) -> list[ProjectCandidate]:
    _, account = _require_account(profile)
    if _account_backend(account) != DESKTOP_ACCOUNT_BACKEND:
        return account_base._discover(profile)
    env = desktop.detect_environment()
    browser = _browser_for_record(account, desktop.detect_browsers(env))
    try:
        values = desktop.discover_projects(
            profile=profile,
            browser=browser,
            cdp_endpoint=str(account.get("cdp_endpoint")) if account.get("cdp_endpoint") else None,
            env=env,
        )
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    return [ProjectCandidate(str(item.get("name") or "Project"), str(item.get("url") or "")) for item in values if item.get("url")]


def _manual_project(profile: str) -> ProjectCandidate:
    _, account = _require_account(profile)
    if _account_backend(account) != DESKTOP_ACCOUNT_BACKEND:
        return account_base._manual_project(profile)
    url = _ask("Cole a URL do Project que deseja vincular")
    if not url:
        raise core.PowerPackError("URL do Project é obrigatória.")
    return _capture_url(profile, url, prompt="Confirme no navegador que o Project correto abriu e pressione Enter aqui.")


def cmd_project_discover(args: argparse.Namespace) -> None:
    profile = account_base._profile_for(args)
    projects = _discover(profile)
    if not projects:
        print("Nenhum Project descoberto. Use project select --manual, project add ou project accept-invite.")
        return
    for index, item in enumerate(projects, start=1):
        print(f"{index:2}. {item.name} | {item.url}")


def cmd_project_select(args: argparse.Namespace) -> None:
    profile = account_base._profile_for(args)
    if args.manual:
        candidate = _manual_project(profile)
    else:
        projects = _discover(profile)
        candidate = account_base._choose_project(projects, args.index) if projects else _manual_project(profile)
    alias = args.alias or account_base._local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def _capture_url(profile: str, url: str, *, prompt: str | None = None) -> ProjectCandidate:
    _, account = _require_account(profile)
    if _account_backend(account) != DESKTOP_ACCOUNT_BACKEND:
        try:
            return account_base.open_link_and_capture_project(
                profile_dir=core.profile_dir(profile),
                url=url,
                purpose="ChatGPT Project verification" if not prompt else "ChatGPT Project invite/shared-link acceptance",
            )
        except RuntimeError as exc:
            raise core.PowerPackError(str(exc)) from exc
    env = desktop.detect_environment()
    browser = _browser_for_record(account, desktop.detect_browsers(env))
    try:
        item = desktop.capture_project_from_url(
            profile=profile,
            browser=browser,
            url=url,
            cdp_endpoint=str(account.get("cdp_endpoint")) if account.get("cdp_endpoint") else None,
            prompt=prompt,
            env=env,
        )
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc
    return ProjectCandidate(str(item.get("name") or "Project"), str(item.get("url") or url))


def cmd_project_add(args: argparse.Namespace) -> None:
    profile = account_base._profile_for(args)
    if not is_chatgpt_project_url(args.url):
        raise core.PowerPackError("Expected a ChatGPT Project URL ending in /project.")
    candidate = _capture_url(profile, args.url)
    alias = args.alias or account_base._local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def cmd_project_accept_invite(args: argparse.Namespace) -> None:
    profile = account_base._profile_for(args)
    candidate = _capture_url(
        profile,
        args.url,
        prompt="Aceite o convite/compartilhamento, navegue até o Project final e pressione Enter aqui.",
    )
    alias = args.alias or account_base._local_alias(candidate.name, candidate.url)
    _persist_binding(alias=alias, candidate=candidate, profile=profile, project_path=Path(args.path).resolve())


def cmd_project_use(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    _, data = core.global_config()
    platform = core.platform_key()
    registered = data.get("projects", {}).get(args.alias)
    if not isinstance(registered, dict):
        raise core.PowerPackError(f"Unknown project alias: {args.alias}")
    profile, binding = account_base._select_binding(registered, platform, getattr(args, "profile", None))
    _require_account(profile)
    if binding.get("authorization") != account_base.PROJECT_BINDING_AUTH:
        raise core.PowerPackError("Project binding stale/legacy; re-select/add it with the desired account.")
    candidate = ProjectCandidate(name=registered.get("display_name") or args.alias, url=binding["url"])
    _persist_binding(alias=args.alias, candidate=candidate, profile=profile, project_path=project)


def review_readiness(project: Path, *, live: bool = False) -> dict[str, bool]:
    try:
        _, review = account_base._review_config(project)
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
    binding = account_base._binding_for(registered, platform, profile) if isinstance(registered, dict) else None
    project_ok = bool(
        account_ok
        and alias
        and url
        and isinstance(binding, dict)
        and binding.get("profile") == profile
        and binding.get("url") == url
        and binding.get("authorization") == account_base.PROJECT_BINDING_AUTH
        and web.get("authorization") == account_base.PROJECT_BINDING_AUTH
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
        if account_ok and _account_backend(record) == DESKTOP_ACCOUNT_BACKEND:
            try:
                _validate_desktop_record(str(profile), record or {}, open_tab=False)
            except core.PowerPackError:
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
    print("The PowerPack detects WSL→Windows or the native Linux/macOS desktop and offers compatible browsers.")
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
    env = desktop.detect_environment()
    print(f"Platform:    {core.platform_key()} ({core.platform_module.system()})")
    print(f"Browser host:{env.host_scope} | desktop={env.desktop or 'n/a'} | display={env.display_server or 'n/a'}")
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
    parser = previous.build_parser()
    root = account_base._subparsers(parser)
    root.choices["doctor"].set_defaults(func=cmd_doctor)

    review = root.choices["review"]
    rsub = account_base._subparsers(review)
    auth = rsub.choices["auth"]
    asub = account_base._subparsers(auth)
    asub.choices["configure"].set_defaults(func=cmd_auth_configure)
    reconfigure = asub.choices["reconfigure"]
    profile_action = _find_action(reconfigure, "profile")
    if profile_action is not None:
        profile_action.nargs = "?"
        profile_action.default = None
    reconfigure.set_defaults(func=cmd_auth_reconfigure)
    asub.choices["list"].set_defaults(func=cmd_auth_list)
    asub.choices["use"].set_defaults(func=cmd_auth_use)
    asub.choices["logout"].set_defaults(func=cmd_auth_logout)
    asub.choices["validate"].set_defaults(func=cmd_auth_validate)

    project = rsub.choices["project"]
    psub = account_base._subparsers(project)
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
