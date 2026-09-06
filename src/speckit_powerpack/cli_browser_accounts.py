from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from . import cli as core
from . import cli_account_binding as account_base
from . import cli_desktop_auth as base
from . import desktop_browser_bridge as desktop


DESKTOP_ACCOUNT_BACKEND = base.DESKTOP_ACCOUNT_BACKEND
DESKTOP_ACCOUNT_AUTH_SOURCE = base.DESKTOP_ACCOUNT_AUTH_SOURCE


def _windows_app_path(executable: str) -> str | None:
    script = rf"""
$paths = @(
  "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\{executable}",
  "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
)
foreach ($p in $paths) {{
  try {{
    $v = (Get-ItemProperty $p -ErrorAction Stop).'(default)'
    if (-not $v) {{ $v = (Get-Item $p -ErrorAction Stop).GetValue('') }}
    if ($v) {{ Write-Output $v; exit 0 }}
  }} catch {{}}
}}
$c = Get-Command '{executable}' -ErrorAction SilentlyContinue
if ($c) {{ Write-Output $c.Source; exit 0 }}
exit 1
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = (proc.stdout or "").strip().splitlines()
    return value[-1].strip() if proc.returncode == 0 and value else None


def _augment_windows_candidates(
    env: desktop.DesktopEnvironment,
    browsers: list[desktop.BrowserCandidate],
) -> list[desktop.BrowserCandidate]:
    if env.host_scope != "windows":
        return browsers
    by_id = {item.browser_id: item for item in browsers}
    known = [
        ("msedge", "Microsoft Edge", "msedge.exe", "channel-cdp", "msedge", "edge://inspect/#remote-debugging"),
        ("chrome", "Google Chrome", "chrome.exe", "channel-cdp", "chrome", "chrome://inspect/#remote-debugging"),
        ("brave", "Brave", "brave.exe", "endpoint-cdp", None, None),
        ("opera", "Opera", "opera.exe", "endpoint-cdp", None, None),
        ("firefox", "Mozilla Firefox", "firefox.exe", "manual-only", None, None),
    ]
    for browser_id, label, exe, automation, channel, inspect in known:
        if browser_id in by_id:
            continue
        path = _windows_app_path(exe)
        if not path:
            continue
        by_id[browser_id] = desktop.BrowserCandidate(
            browser_id=browser_id,
            label=label,
            executable=path,
            automation=automation,
            cdp_channel=channel,
            inspect_url=inspect,
            host_scope="windows",
        )
    order = {"msedge": 0, "chrome": 1, "brave": 2, "opera": 3, "chromium": 4, "firefox": 5}
    return sorted(by_id.values(), key=lambda item: (order.get(item.browser_id, 99), item.label.casefold()))


def _detected_browsers(env: desktop.DesktopEnvironment) -> list[desktop.BrowserCandidate]:
    return _augment_windows_candidates(env, desktop.detect_browsers(env))


def _default_browser_id(env: desktop.DesktopEnvironment) -> str | None:
    if env.host_scope == "windows":
        script = r"""
try {
  $p = 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
  $v = (Get-ItemProperty $p -ErrorAction Stop).ProgId
  Write-Output $v
  exit 0
} catch { exit 1 }
"""
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                text=True,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = (proc.stdout or "").strip().casefold()
        if "edge" in value:
            return "msedge"
        if "chrome" in value:
            return "chrome"
        if "firefox" in value:
            return "firefox"
        if "brave" in value:
            return "brave"
        if "opera" in value:
            return "opera"
        return None
    if env.host_scope == "linux":
        xdg = shutil.which("xdg-settings")
        if not xdg:
            return None
        try:
            proc = subprocess.run(
                [xdg, "get", "default-web-browser"],
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = (proc.stdout or "").strip().casefold()
        for browser_id, needles in {
            "msedge": ("edge", "microsoft-edge"),
            "chrome": ("chrome", "google-chrome"),
            "chromium": ("chromium",),
            "brave": ("brave",),
            "opera": ("opera",),
            "firefox": ("firefox",),
        }.items():
            if any(needle in value for needle in needles):
                return browser_id
    return None


def _open_url_nonblocking(
    url: str,
    *,
    browser: desktop.BrowserCandidate,
    env: desktop.DesktopEnvironment,
) -> None:
    if env.host_scope == "linux" and browser.executable:
        try:
            subprocess.Popen(
                [browser.executable, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except OSError as exc:
            raise core.PowerPackError(f"Não foi possível abrir {browser.label}: {exc}") from exc
    try:
        desktop.open_url(url, browser=browser, env=env)
    except desktop.DesktopBrowserBridgeError as exc:
        raise core.PowerPackError(str(exc)) from exc


def _print_browser_matrix(
    browsers: list[desktop.BrowserCandidate],
    *,
    default_id: str | None,
) -> None:
    print("\nNavegadores encontrados:")
    for index, browser in enumerate(browsers, start=1):
        marker = " [padrão]" if browser.browser_id == default_id else ""
        capability = {
            "channel-cdp": "review Web automatizável por attach direto",
            "endpoint-cdp": "review Web automatizável via endpoint CDP",
            "manual-only": "login manual apenas; não pode executar o gate Web automatizado",
        }.get(browser.automation, browser.automation)
        print(f"  {index}. {browser.label}{marker} — {capability}")


def _choose_reviewer_browser(
    browsers: list[desktop.BrowserCandidate],
    *,
    default_id: str | None,
    previous_id: str | None,
) -> desktop.BrowserCandidate:
    automatable = [browser for browser in browsers if browser.automatable_existing_context]
    if not automatable:
        raise core.PowerPackError(
            "Nenhum navegador compatível com attach de sessão existente foi detectado. "
            "Não existe fallback automático: configure Chrome/Edge ou outro Chromium com CDP e rode auth configure novamente."
        )
    preferred = previous_id or default_id
    print("\nEscolha explicitamente qual navegador/conta fará o review Web.")
    print("A troca de navegador é uma troca consciente da identidade do reviewer; nunca ocorre de forma silenciosa.")
    for index, browser in enumerate(automatable, start=1):
        marker = " [sugerido]" if browser.browser_id == preferred else ""
        suffix = " [endpoint CDP]" if browser.automation == "endpoint-cdp" else ""
        print(f"  {index}. {browser.label}{marker}{suffix}")
    default_index = 1
    for index, browser in enumerate(automatable, start=1):
        if browser.browser_id == preferred:
            default_index = index
            break
    value = base._ask("Navegador/conta", default=str(default_index)).strip()
    if not value.isdigit() or not (1 <= int(value) <= len(automatable)):
        raise core.PowerPackError("Seleção de navegador inválida.")
    return automatable[int(value) - 1]


def _prepare_attach(
    browser: desktop.BrowserCandidate,
    *,
    env: desktop.DesktopEnvironment,
    existing: dict[str, Any] | None,
) -> str | None:
    if browser.automation == "channel-cdp":
        if browser.inspect_url:
            _open_url_nonblocking(browser.inspect_url, browser=browser, env=env)
        print(f"\nNo {browser.label}, habilite 'Allow remote debugging for this browser instance'.")
        print("Mantenha a mesma instância e o mesmo perfil do navegador abertos.")
        return None
    if browser.automation == "endpoint-cdp":
        print(f"\n{browser.label} exige um endpoint CDP da MESMA instância onde a conta está autenticada.")
        endpoint = base._ask(
            "Endpoint CDP",
            default=str((existing or {}).get("cdp_endpoint") or "http://127.0.0.1:9222"),
        )
        if not endpoint:
            raise core.PowerPackError("Endpoint CDP é obrigatório para o navegador selecionado.")
        return endpoint
    raise core.PowerPackError(
        f"{browser.label} não suporta attach da sessão existente neste backend. "
        "Escolha outro navegador explicitamente; o PowerPack não executará fallback."
    )


def _configure_desktop_account(
    *,
    profile: str,
    account_label: str,
    existing: dict[str, Any] | None,
) -> None:
    env = desktop.detect_environment()
    browsers = _detected_browsers(env)
    base._print_environment(env, browsers)
    default_id = _default_browser_id(env)
    _print_browser_matrix(browsers, default_id=default_id)

    previous_id = str((existing or {}).get("automation_browser_id") or (existing or {}).get("browser_channel") or "") or None

    while True:
        browser = _choose_reviewer_browser(
            browsers,
            default_id=default_id,
            previous_id=previous_id,
        )
        print("\nIdentidade de review selecionada:")
        print(f"  profile lógico: {profile}")
        print(f"  account label: {account_label}")
        print(f"  host: {env.host_scope}")
        print(f"  browser: {browser.label}")
        print("  política: nenhuma troca automática de browser/backend")

        _open_url_nonblocking("https://chatgpt.com/", browser=browser, env=env)
        print(f"\nChatGPT aberto em {browser.label} SEM controle Playwright.")
        print("Conclua login/Google/SSO/MFA nessa mesma instância. A conta já logada pode ser diferente da conta em outro navegador.")
        choice = input("[Enter]=login concluído  [T]=tentar OUTRO navegador/conta  [C]=cancelar: ").strip().casefold()
        if choice in {"t", "trocar", "tentar", "outro"}:
            print("Nenhuma autorização foi gravada. Escolha conscientemente outra identidade de navegador/conta.")
            previous_id = None
            continue
        if choice in {"c", "cancelar", "cancel"}:
            raise core.PowerPackError("Configuração cancelada; nenhuma autorização foi gravada.")
        if choice not in {"", "ok", "done"}:
            print("Opção inválida; nenhuma mudança de browser foi executada.")
            continue

        cdp_endpoint = _prepare_attach(browser, env=env, existing=existing)
        print("\nPermissão solicitada:")
        print("- Playwright poderá inspecionar/controlar abas desta instância durante o gate Web.")
        print("- O PowerPack não copia cookies, senhas, MFA, OAuth tokens ou o perfil do navegador.")
        print("- Esta autorização vale apenas para o profile lógico/conta que você está configurando.")
        if not base._yes("Conceder essa permissão ao PowerPack?", default=False):
            raise core.PowerPackError("Permissão negada; nenhuma autorização foi gravada.")
        input("Depois de habilitar a depuração remota e manter o browser aberto, pressione Enter para validar... ")

        try:
            session = desktop.attach_existing_browser(
                profile=profile,
                browser=browser,
                cdp_endpoint=cdp_endpoint,
                env=env,
            )
            desktop.open_chatgpt_tab(session, env=env)
            evidence = desktop.validate_existing_chatgpt_session(
                profile=profile,
                browser=browser,
                cdp_endpoint=cdp_endpoint,
                open_tab=False,
                env=env,
            )
        except desktop.DesktopBrowserBridgeError as exc:
            print(f"\nFalha ao validar {browser.label}: {exc}")
            retry = input("[T]=tentar explicitamente outro navegador/conta  [C]=encerrar com erro: ").strip().casefold()
            if retry in {"t", "trocar", "tentar", "outro"}:
                print("Nenhum fallback automático foi executado e nenhuma autorização foi gravada.")
                previous_id = None
                continue
            raise core.PowerPackError(
                f"Falha no browser selecionado ({browser.browser_id}); nenhum fallback foi executado."
            ) from exc

        print(f"\nSessão ChatGPT validada: {evidence.get('title') or evidence.get('href')}")
        if not base._yes(
            f"Confirmar que a conta aberta em {browser.label} corresponde ao reviewer '{account_label}'?",
            default=False,
        ):
            retry = input("[T]=tentar outra conta/browser  [C]=cancelar: ").strip().casefold()
            if retry in {"t", "trocar", "tentar", "outro"}:
                previous_id = None
                continue
            raise core.PowerPackError("Identidade não confirmada; nenhuma autorização foi gravada.")

        invalidated = base._persist_desktop_account(
            profile=profile,
            account_label=account_label,
            env=env,
            login_browser=browser,
            automation_browser=browser,
            cdp_endpoint=cdp_endpoint,
        )
        print(
            f"Conta '{account_label}' autorizada como '{profile}' em {browser.label}. "
            "Login browser e automation browser são a MESMA identidade."
        )
        if invalidated:
            print("Bindings anteriores marcados como stale: " + ", ".join(sorted(set(invalidated))))
        return


def interactive_configure(
    *,
    requested_profile: str | None = None,
    requested_label: str | None = None,
) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    profile = requested_profile or base._choose_existing_profile(data, platform)
    if not profile:
        profile = base._ask("Nome lógico do reviewer/account", default="chatgpt-review")
    if not profile:
        raise core.PowerPackError("Nome lógico do reviewer é obrigatório.")

    existing = base._account_record(data, platform, profile)
    if existing and base._account_authorized(data, platform, profile):
        print(
            f"\nJá existe autorização válida para '{profile}' "
            f"(conta={existing.get('account_label') or profile}, browser={existing.get('automation_browser_id') or existing.get('browser_channel')})."
        )
        if not base._yes("Deseja substituir essa autorização?", default=False):
            print("Autorização existente preservada.")
            return

    account_label = requested_label or base._ask(
        "Identificação local da conta ChatGPT",
        default=str((existing or {}).get("account_label") or profile),
    )
    if not account_label:
        raise core.PowerPackError("Identificação local da conta é obrigatória.")
    _configure_desktop_account(profile=profile, account_label=account_label, existing=existing)


def cmd_auth_configure(args: argparse.Namespace) -> None:
    interactive_configure()


def cmd_auth_reconfigure(args: argparse.Namespace) -> None:
    # Arguments remain accepted for backwards compatibility, but the user-visible
    # workflow is interactive and asks before replacing an existing valid grant.
    interactive_configure(
        requested_profile=getattr(args, "profile", None),
        requested_label=getattr(args, "account_label", None),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = base.build_parser()
    root = account_base._subparsers(parser)
    review = root.choices["review"]
    rsub = account_base._subparsers(review)
    auth = rsub.choices["auth"]
    asub = account_base._subparsers(auth)
    asub.choices["configure"].set_defaults(func=cmd_auth_configure)
    asub.choices["reconfigure"].set_defaults(func=cmd_auth_reconfigure)
    return parser


def main(argv: list[str] | None = None) -> int:
    core.review_readiness = lambda project: base.review_readiness(project)
    core.print_review_setup_status = base.print_review_setup_status
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


core.review_readiness = lambda project: base.review_readiness(project)
core.print_review_setup_status = base.print_review_setup_status
