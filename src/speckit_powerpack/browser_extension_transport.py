from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
from typing import Any, Iterable

from . import cli as core
from . import cli_browser_accounts as accounts
from . import cli_desktop_auth as desktop_auth
from . import desktop_browser_bridge as desktop
from . import windows_browser_bridge as winbridge


PLAYWRIGHT_EXTENSION_URL = (
    "https://chromewebstore.google.com/detail/playwright-extension/"
    "mmlmfjhmonkocbjadbfplnigmagldckm"
)
EXTENSION_BROWSER_IDS = {"chrome", "msedge"}

_ORIGINAL_DETECT_BROWSERS = desktop.detect_browsers
_ORIGINAL_WINDOWS_CMD = winbridge._windows_cmd
_ORIGINAL_PREPARE_ATTACH = accounts._prepare_attach
_APPLIED = False


def _decode_completed_process(proc: subprocess.CompletedProcess[bytes]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        stdout=winbridge._decode_windows_output(proc.stdout),
        stderr=winbridge._decode_windows_output(proc.stderr),
    )


def _windows_cmd_local_cwd(
    args: Iterable[str],
    *,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run Windows CLI tooling from a Windows-local cwd when called from WSL.

    Starting cmd.exe while Python's cwd is \\wsl.localhost\\... produces UNC cwd
    diagnostics and can destabilize npm/node child processes. The PowerPack does
    not need the repository cwd for browser automation, so execute Playwright CLI
    under %TEMP% and start cmd.exe from C:\\Windows instead.
    """
    if not winbridge.is_wsl():
        raise winbridge.WindowsBrowserBridgeError(
            "Windows browser-context mode is supported from WSL only."
        )

    payload = subprocess.list2cmdline(list(args))
    command = (
        'chcp 65001 >NUL && '
        'cd /d "%TEMP%" && '
        'if not exist "speckit-powerpack-playwright" mkdir "speckit-powerpack-playwright" && '
        'cd /d "speckit-powerpack-playwright" && '
        f"{payload}"
    )

    local_cwd = next(
        (
            path
            for path in (Path("/mnt/c/Windows/System32"), Path("/mnt/c/Windows"), Path("/mnt/c"))
            if path.is_dir()
        ),
        None,
    )
    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", command],
            cwd=str(local_cwd) if local_cwd else None,
            text=False,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise winbridge.WindowsBrowserBridgeError("cmd.exe is unavailable from WSL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise winbridge.WindowsBrowserBridgeError("Windows browser command timed out.") from exc
    return _decode_completed_process(proc)


def _detect_browsers_extension_first(
    env: desktop.DesktopEnvironment | None = None,
) -> list[desktop.BrowserCandidate]:
    values = _ORIGINAL_DETECT_BROWSERS(env)
    result: list[desktop.BrowserCandidate] = []
    for browser in values:
        if browser.browser_id in EXTENSION_BROWSER_IDS:
            result.append(
                replace(
                    browser,
                    automation="extension-attach",
                    inspect_url=PLAYWRIGHT_EXTENSION_URL,
                )
            )
        else:
            result.append(browser)
    return result


def _capability_text(browser: desktop.BrowserCandidate) -> str:
    return {
        "extension-attach": "review Web automatizável via Playwright Extension (sessão existente)",
        "channel-cdp": "review Web automatizável por attach CDP",
        "endpoint-cdp": "review Web automatizável via endpoint CDP",
        "manual-only": "login manual apenas; não pode executar o gate Web automatizado",
    }.get(browser.automation, browser.automation)


def _print_environment(
    env: desktop.DesktopEnvironment,
    browsers: list[desktop.BrowserCandidate],
) -> None:
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
            print(f"    - {browser.label}: {_capability_text(browser)}")
    else:
        print("  navegadores detectados: nenhum compatível encontrado")


def _print_browser_matrix(
    browsers: list[desktop.BrowserCandidate],
    *,
    default_id: str | None,
) -> None:
    print("\nNavegadores encontrados:")
    for index, browser in enumerate(browsers, start=1):
        marker = " [padrão]" if browser.browser_id == default_id else ""
        print(f"  {index}. {browser.label}{marker} — {_capability_text(browser)}")


def _prepare_extension(
    browser: desktop.BrowserCandidate,
    *,
    env: desktop.DesktopEnvironment,
) -> None:
    print(f"\n{browser.label} usará a Playwright Extension oficial para reutilizar esta sessão autenticada.")
    print("Isso evita copiar cookies/tokens e não exige DevToolsActivePort/remote debugging.")
    print("A extensão deve estar instalada e habilitada NESTE MESMO perfil do navegador.")
    choice = input(
        "[Enter]=extensão já instalada  [I]=abrir página de instalação  "
        "[T]=escolher outro navegador/conta  [C]=cancelar: "
    ).strip().casefold()
    if choice in {"t", "trocar", "outro"}:
        raise _ChooseAnotherBrowser()
    if choice in {"c", "cancelar", "cancel"}:
        raise core.PowerPackError("Configuração cancelada; nenhuma autorização foi gravada.")
    if choice in {"i", "instalar", "install"}:
        accounts._open_url_nonblocking(PLAYWRIGHT_EXTENSION_URL, browser=browser, env=env)
        print("Instale/ative 'Playwright Extension' publicada pelo Playwright Team.")
        if browser.browser_id == "msedge":
            print("No Edge, permita extensões da Chrome Web Store se o navegador solicitar.")
        input("Quando a extensão estiver instalada e habilitada neste perfil, pressione Enter... ")
    elif choice not in {"", "ok", "done"}:
        raise core.PowerPackError("Opção de extensão inválida; nenhuma autorização foi gravada.")


class _ChooseAnotherBrowser(RuntimeError):
    pass


def _prepare_attach(
    browser: desktop.BrowserCandidate,
    *,
    env: desktop.DesktopEnvironment,
    existing: dict[str, Any] | None,
) -> str | None:
    if browser.automation == "extension-attach":
        _prepare_extension(browser, env=env)
        return None
    return _ORIGINAL_PREPARE_ATTACH(browser, env=env, existing=existing)


def _attach_existing_browser(
    *,
    profile: str,
    browser: desktop.BrowserCandidate,
    cdp_endpoint: str | None = None,
    env: desktop.DesktopEnvironment | None = None,
) -> str:
    env = env or desktop.detect_environment()
    desktop.ensure_host_playwright_cli(env)
    session = winbridge.session_name_for(profile)

    if browser.automation == "extension-attach":
        channel = browser.cdp_channel or browser.browser_id
        extension_arg = "--extension" if channel == "chrome" else f"--extension={channel}"
        try:
            desktop._host_pwcli(
                [f"-s={session}", "attach", extension_arg],
                env=env,
                timeout=180,
            )
        except desktop.DesktopBrowserBridgeError as exc:
            raise desktop.DesktopBrowserBridgeError(
                f"Could not attach to {browser.label} through Playwright Extension. "
                "Confirm that the official Playwright Extension is installed/enabled in the SAME browser profile, "
                "keep the browser open, and approve the extension connection page when it asks to Allow & select "
                f"the ChatGPT tab. Underlying error: {exc}"
            ) from exc
        return session

    if browser.automation == "endpoint-cdp":
        if not cdp_endpoint:
            raise desktop.DesktopBrowserBridgeError(
                f"{browser.label} requires a Chromium CDP endpoint, for example http://127.0.0.1:9222."
            )
        try:
            desktop._host_pwcli(
                [f"-s={session}", "attach", f"--cdp={cdp_endpoint}"],
                env=env,
                timeout=120,
            )
        except desktop.DesktopBrowserBridgeError as exc:
            raise desktop.DesktopBrowserBridgeError(
                f"Could not attach to {browser.label} endpoint {cdp_endpoint}. Underlying error: {exc}"
            ) from exc
        return session

    if browser.automation == "channel-cdp":
        target = browser.cdp_channel
        if not target:
            raise desktop.DesktopBrowserBridgeError(f"{browser.label} has no CDP channel configured.")
        desktop._host_pwcli(
            [f"-s={session}", "attach", f"--cdp={target}"],
            env=env,
            timeout=120,
        )
        return session

    raise desktop.DesktopBrowserBridgeError(
        f"{browser.label} cannot automate its existing session with backend={browser.automation}."
    )


def _configure_desktop_account(
    *,
    profile: str,
    account_label: str,
    existing: dict[str, Any] | None,
) -> None:
    env = desktop.detect_environment()
    browsers = accounts._detected_browsers(env)
    _print_environment(env, browsers)
    default_id = accounts._default_browser_id(env)
    _print_browser_matrix(browsers, default_id=default_id)

    previous_id = str(
        (existing or {}).get("automation_browser_id")
        or (existing or {}).get("browser_channel")
        or ""
    ) or None

    while True:
        browser = accounts._choose_reviewer_browser(
            browsers,
            default_id=default_id,
            previous_id=previous_id,
        )
        print("\nIdentidade de review selecionada:")
        print(f"  profile lógico: {profile}")
        print(f"  account label: {account_label}")
        print(f"  host: {env.host_scope}")
        print(f"  browser: {browser.label}")
        print(f"  transporte: {browser.automation}")
        print("  política: nenhuma troca automática de browser/backend")

        accounts._open_url_nonblocking("https://chatgpt.com/", browser=browser, env=env)
        print(f"\nChatGPT aberto em {browser.label} SEM controle Playwright.")
        print(
            "Confirme que ESTE navegador/perfil está autenticado na conta que fará o review. "
            "Conclua Google/SSO/MFA normalmente se necessário."
        )
        choice = input(
            "[Enter]=conta correta e login concluído  [T]=outro navegador/conta  [C]=cancelar: "
        ).strip().casefold()
        if choice in {"t", "trocar", "tentar", "outro"}:
            previous_id = None
            continue
        if choice in {"c", "cancelar", "cancel"}:
            raise core.PowerPackError("Configuração cancelada; nenhuma autorização foi gravada.")
        if choice not in {"", "ok", "done"}:
            print("Opção inválida; nenhuma autorização foi gravada.")
            continue

        try:
            cdp_endpoint = _prepare_attach(browser, env=env, existing=existing)
        except _ChooseAnotherBrowser:
            previous_id = None
            continue

        print("\nPermissão solicitada:")
        print("- Playwright poderá controlar somente a sessão/abas liberadas pelo transporte selecionado.")
        print("- O PowerPack não copia senhas, MFA, cookies nem tokens para o WSL/repositório.")
        print("- A conta autenticada neste browser será a identidade do reviewer Web.")
        if not desktop_auth._yes("Conceder essa permissão ao PowerPack?", default=False):
            raise core.PowerPackError("Permissão negada; nenhuma autorização foi gravada.")

        if browser.automation == "extension-attach":
            print("\nO PowerPack vai solicitar conexão pela Playwright Extension.")
            print("Se a página da extensão abrir, clique 'Allow & select' na aba do ChatGPT que deseja liberar.")
            print("Não feche o navegador enquanto a conexão estiver sendo estabelecida.")
        elif browser.automation == "endpoint-cdp":
            print(f"\nMantenha {browser.label} aberto com o endpoint CDP {cdp_endpoint} ativo.")

        try:
            session = _attach_existing_browser(
                profile=profile,
                browser=browser,
                cdp_endpoint=cdp_endpoint,
                env=env,
            )
            evidence = desktop.chatgpt_login_evidence(session, env=env)
            if not evidence.get("authenticated"):
                raise desktop.DesktopBrowserBridgeError(
                    "A conexão com o navegador foi estabelecida, mas a aba selecionada não é uma sessão "
                    "ChatGPT autenticada com o composer normal visível. No fluxo da extensão, escolha "
                    "explicitamente a aba ChatGPT em 'Allow & select'."
                )
        except desktop.DesktopBrowserBridgeError as exc:
            print(f"\nFalha ao validar {browser.label}: {exc}")
            retry = input(
                "[R]=repetir MESMO navegador  [T]=outro navegador/conta  [C]=encerrar com erro: "
            ).strip().casefold()
            if retry in {"r", "repetir", "retry"}:
                previous_id = browser.browser_id
                continue
            if retry in {"t", "trocar", "tentar", "outro"}:
                print("Nenhum fallback automático foi executado e nenhuma autorização foi gravada.")
                previous_id = None
                continue
            raise core.PowerPackError(
                f"Falha no browser selecionado ({browser.browser_id}); nenhum fallback foi executado."
            ) from exc

        print(f"\nSessão ChatGPT validada: {evidence.get('title') or evidence.get('href')}")
        if not desktop_auth._yes(
            f"Confirmar que essa sessão corresponde ao reviewer '{account_label}'?",
            default=False,
        ):
            retry = input("[T]=outra conta/browser  [C]=cancelar: ").strip().casefold()
            if retry in {"t", "trocar", "tentar", "outro"}:
                previous_id = None
                continue
            raise core.PowerPackError("Identidade não confirmada; nenhuma autorização foi gravada.")

        invalidated = desktop_auth._persist_desktop_account(
            profile=profile,
            account_label=account_label,
            env=env,
            login_browser=browser,
            automation_browser=browser,
            cdp_endpoint=cdp_endpoint,
        )
        print(
            f"Conta '{account_label}' autorizada como '{profile}' em {browser.label} "
            f"usando {browser.automation}."
        )
        if invalidated:
            print("Bindings anteriores marcados como stale: " + ", ".join(sorted(set(invalidated))))
        return


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    # Chrome/Edge existing-session automation is extension-first. This is the
    # Playwright transport designed for SSO/2FA and already-authenticated tabs.
    desktop.detect_browsers = _detect_browsers_extension_first
    desktop.BrowserCandidate.automatable_existing_context = property(
        lambda self: self.automation in {"extension-attach", "channel-cdp", "endpoint-cdp"}
    )

    # All Windows Node/npm/Playwright CLI calls start outside the WSL UNC cwd.
    winbridge._windows_cmd = _windows_cmd_local_cwd

    # Use the same extension-aware attach path for configure, validate, Project
    # discovery/binding and the functional smoke test.
    desktop.attach_existing_browser = _attach_existing_browser
    accounts._print_browser_matrix = _print_browser_matrix
    accounts._prepare_attach = _prepare_attach
    accounts._configure_desktop_account = _configure_desktop_account
    desktop_auth._print_environment = _print_environment
