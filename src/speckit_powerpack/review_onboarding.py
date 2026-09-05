from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable
from urllib.parse import urljoin, urlparse


CHATGPT_ORIGINS = {"chatgpt.com", "www.chatgpt.com"}
LOGIN_PATH_PREFIXES = ("/auth", "/login", "/signup", "/sign-up")
LOGIN_PROMPT_TOKENS = (
    "continue with google",
    "continue with microsoft",
    "continue with apple",
    "log in",
    "sign up",
    "entrar",
    "continuar com google",
    "continuar com microsoft",
    "continuar com apple",
)


@dataclass(frozen=True)
class AccountAuthorizationResult:
    granted: bool
    profile: str
    platform: str
    profile_dir: str
    account_label: str | None = None
    granted_at: str | None = None


@dataclass(frozen=True)
class ProjectCandidate:
    name: str
    url: str


@dataclass(frozen=True)
class ReviewAuthorizationResult:
    """Backward-compatible project-scoped result used by older callers/tests."""

    granted: bool
    profile: str
    project_alias: str
    project_url: str
    platform: str
    profile_dir: str
    granted_at: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def playwright_version() -> str:
    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return "unknown"


def browser_install_receipt(config_root: Path, platform: str) -> Path:
    return config_root / "browser-install" / f"{platform}.json"


def browser_install_ready(config_root: Path, platform: str) -> bool:
    path = browser_install_receipt(config_root, platform)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("browser") == "chromium"
        and payload.get("playwright_version") == playwright_version()
        and payload.get("platform") == platform
    )


def ensure_chromium(
    config_root: Path,
    platform: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    argv = [sys.executable, "-m", "playwright", "install", "chromium"]
    proc = runner(argv, text=True, capture_output=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Playwright Chromium installation failed").strip()
        raise RuntimeError(detail)
    receipt = browser_install_receipt(config_root, platform)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "browser": "chromium",
                "platform": platform,
                "playwright_version": playwright_version(),
                "installed_at": utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def is_chatgpt_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in CHATGPT_ORIGINS


def is_chatgpt_project_url(url: str) -> bool:
    parsed = urlparse(url)
    return is_chatgpt_url(url) and parsed.path.rstrip("/").endswith("/project")


def same_chatgpt_project(actual_url: str, requested_url: str) -> bool:
    actual = urlparse(actual_url)
    requested = urlparse(requested_url)
    return (
        is_chatgpt_url(actual_url)
        and is_chatgpt_url(requested_url)
        and actual.path.rstrip("/") == requested.path.rstrip("/")
    )


def chatgpt_login_verified(url: str, visible_text: str = "") -> bool:
    """Best-effort UI-level proof that the selected Playwright tab left the login flow.

    This deliberately avoids reading/storing auth cookies or tokens. The actual Web review
    still re-establishes the browser session when it runs.
    """
    if not is_chatgpt_url(url):
        return False
    path = urlparse(url).path.rstrip("/").casefold()
    if any(path == prefix or path.startswith(prefix + "/") for prefix in LOGIN_PATH_PREFIXES):
        return False
    normalized = " ".join((visible_text or "").casefold().split())
    if any(token in normalized for token in LOGIN_PROMPT_TOKENS):
        return False
    return True


def account_consent_html(*, profile: str, account_label: str | None, profile_dir: Path) -> str:
    profile_text = escape(profile)
    account_text = escape(account_label or profile)
    dir_text = escape(str(profile_dir))
    return f"""<!doctype html>
<html lang=\"pt-BR\">
<head>
<meta charset=\"utf-8\">
<title>SpecKit PowerPack — autorização da conta ChatGPT</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; background: #111827; color: #f9fafb; }}
main {{ max-width: 780px; margin: 48px auto; padding: 32px; background: #1f2937; border-radius: 16px; }}
h1 {{ margin-top: 0; }}
code {{ background: #111827; padding: 2px 6px; border-radius: 6px; overflow-wrap: anywhere; }}
.notice {{ padding: 16px; background: #0f172a; border-left: 4px solid #60a5fa; margin: 20px 0; }}
.success {{ border-left-color: #34d399; }}
.error {{ border-left-color: #f87171; }}
.actions {{ display: flex; gap: 12px; margin-top: 28px; flex-wrap: wrap; }}
button {{ border: 0; border-radius: 8px; padding: 12px 18px; font-weight: 700; cursor: pointer; }}
.primary {{ background: #f9fafb; color: #111827; }}
.secondary {{ background: #374151; color: #f9fafb; }}
#login-step, #grant {{ display: none; }}
.small {{ color: #d1d5db; font-size: 0.92rem; }}
.steps li {{ margin: 9px 0; }}
</style>
<script>
window.__powerpackDecision = null;
window.__powerpackLoginCheck = null;
window.__powerpackGrant = null;
function authorize() {{ window.__powerpackDecision = 'authorize'; showLoginStep(); }}
function cancel() {{
  window.__powerpackDecision = 'cancel';
  window.__powerpackLoginCheck = 'cancel';
  window.__powerpackGrant = 'cancel';
}}
function requestLoginCheck() {{ window.__powerpackLoginCheck = 'check'; }}
function resetLoginCheck() {{ window.__powerpackLoginCheck = null; }}
function grant() {{ window.__powerpackGrant = 'grant'; }}
function showLoginStep() {{
  document.getElementById('initial').style.display = 'none';
  document.getElementById('login-step').style.display = 'block';
  document.getElementById('grant').style.display = 'none';
}}
function showLoginError(message) {{
  showLoginStep();
  const box = document.getElementById('login-error');
  box.textContent = message;
  box.style.display = 'block';
  resetLoginCheck();
}}
function showVerified(message) {{
  document.getElementById('initial').style.display = 'none';
  document.getElementById('login-step').style.display = 'none';
  document.getElementById('grant').style.display = 'block';
  document.getElementById('verified-message').textContent = message;
}}
</script>
</head>
<body>
<main>
<section id=\"initial\">
<h1>Autorizar esta conta ChatGPT para reviews Web?</h1>
<p>O perfil Playwright representa a identidade da conta que executará o segundo gate de code review.</p>
<div class=\"notice\">
<strong>Perfil isolado:</strong> o PowerPack usa um Chromium persistente próprio em<br>
<code>{dir_text}</code>.
</div>
<ul>
<li>Não reutiliza cookies, histórico ou sessão do Edge/Chrome do Windows.</li>
<li>Credenciais e MFA são digitados somente no site oficial do ChatGPT.</li>
<li>Esta autorização é da <strong>conta/perfil</strong>, não de um Project específico.</li>
<li>Depois do login você poderá descobrir, aceitar convites e vincular qualquer Project acessível a esta conta.</li>
<li>Para duas assinaturas/contas, crie dois perfis PowerPack separados.</li>
</ul>
<p class=\"small\">Perfil: <code>{profile_text}</code> · identificação local: <code>{account_text}</code></p>
<div class=\"actions\">
<button class=\"primary\" onclick=\"authorize()\">Autorizar e abrir ChatGPT</button>
<button class=\"secondary\" onclick=\"cancel()\">Cancelar</button>
</div>
</section>
<section id=\"login-step\">
<h1>1. Faça login na aba do ChatGPT</h1>
<ol class=\"steps\">
<li>Vá para a aba <strong>ChatGPT</strong> que acabou de ser aberta.</li>
<li>Conclua todo o login, MFA/OTP e eventuais confirmações da sua conta.</li>
<li>Espere até enxergar a interface normal do ChatGPT.</li>
<li>Só então volte a esta aba e clique em <strong>Já concluí o login — validar conta</strong>.</li>
</ol>
<div class=\"notice\">
<strong>Importante:</strong> este botão não concede acesso. Ele apenas pede ao PowerPack para verificar se a aba do ChatGPT realmente saiu do fluxo de autenticação. A concessão final aparece somente depois dessa verificação.
</div>
<div id=\"login-error\" class=\"notice error\" style=\"display:none\"></div>
<div class=\"actions\">
<button class=\"primary\" onclick=\"requestLoginCheck()\">Já concluí o login — validar conta</button>
<button class=\"secondary\" onclick=\"cancel()\">Cancelar</button>
</div>
</section>
<section id=\"grant\">
<h1>2. Conta validada</h1>
<div class=\"notice success\">
<strong id=\"verified-message\">A aba do ChatGPT foi validada.</strong>
</div>
<p>Agora você pode conceder ao PowerPack permissão para reutilizar <strong>somente este perfil isolado</strong> em reviews Web e na descoberta/seleção de Projects acessíveis por esta conta.</p>
<div class=\"actions\">
<button class=\"primary\" onclick=\"grant()\">Conceder acesso à conta</button>
<button class=\"secondary\" onclick=\"cancel()\">Cancelar</button>
</div>
</section>
</main>
</body>
</html>"""


def consent_html(*, profile: str, project_alias: str, project_url: str, profile_dir: Path) -> str:
    """Legacy project-scoped consent page retained for compatibility."""
    return account_consent_html(profile=profile, account_label=f"{project_alias}: {project_url}", profile_dir=profile_dir)


def _page_visible_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def authorize_chatgpt_account(
    *,
    config_root: Path,
    platform: str,
    profile: str,
    profile_dir: Path,
    account_label: str | None = None,
) -> AccountAuthorizationResult:
    ensure_chromium(config_root, platform)
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the PowerPack environment") from exc

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
            try:
                consent = context.pages[0] if context.pages else context.new_page()
                consent.set_content(account_consent_html(profile=profile, account_label=account_label, profile_dir=profile_dir))
                consent.wait_for_function("window.__powerpackDecision !== null", timeout=0)
                if consent.evaluate("window.__powerpackDecision") != "authorize":
                    return AccountAuthorizationResult(False, profile, platform, str(profile_dir), account_label)

                chatgpt = context.new_page()
                chatgpt.goto("https://chatgpt.com/", wait_until="domcontentloaded")
                # Keep ChatGPT in the foreground. The consent tab waits until the user returns
                # and explicitly asks PowerPack to validate that login is complete.
                chatgpt.bring_to_front()

                while True:
                    consent.wait_for_function("window.__powerpackLoginCheck !== null", timeout=0)
                    login_decision = consent.evaluate("window.__powerpackLoginCheck")
                    if login_decision == "cancel":
                        return AccountAuthorizationResult(False, profile, platform, str(profile_dir), account_label)
                    if login_decision != "check":
                        consent.evaluate("resetLoginCheck()")
                        continue

                    if not chatgpt_login_verified(chatgpt.url, _page_visible_text(chatgpt)):
                        consent.evaluate(
                            "message => showLoginError(message)",
                            "Login ainda não foi confirmado. Volte à aba do ChatGPT, conclua autenticação/MFA e espere a interface normal carregar antes de validar novamente.",
                        )
                        consent.bring_to_front()
                        continue

                    consent.evaluate(
                        "message => showVerified(message)",
                        "Login confirmado na aba do ChatGPT. A concessão abaixo autoriza apenas o perfil Playwright isolado atual.",
                    )
                    consent.bring_to_front()
                    break

                consent.wait_for_function("window.__powerpackGrant !== null", timeout=0)
                if consent.evaluate("window.__powerpackGrant") != "grant":
                    return AccountAuthorizationResult(False, profile, platform, str(profile_dir), account_label)

                # Re-check immediately before persisting the grant so a stale/changed tab
                # cannot satisfy account authorization accidentally.
                if not chatgpt_login_verified(chatgpt.url, _page_visible_text(chatgpt)):
                    raise RuntimeError(
                        "ChatGPT account authorization was not recorded because the ChatGPT tab no longer appears authenticated. "
                        "Complete login in the ChatGPT tab and run authorization again."
                    )

                return AccountAuthorizationResult(
                    True,
                    profile,
                    platform,
                    str(profile_dir),
                    account_label,
                    utc_now(),
                )
            finally:
                context.close()
    except PlaywrightError as exc:
        raise RuntimeError("Playwright authorization window was closed or failed before permission was completed") from exc


def _project_candidates_from_page(page) -> list[ProjectCandidate]:
    values: dict[str, ProjectCandidate] = {}
    anchors = page.locator("a[href]")
    for index in range(anchors.count()):
        anchor = anchors.nth(index)
        href = anchor.get_attribute("href") or ""
        absolute = urljoin(page.url, href)
        if not is_chatgpt_project_url(absolute):
            continue
        name = (anchor.inner_text() or "").strip() or urlparse(absolute).path.split("/")[-2]
        normalized = absolute.split("?", 1)[0].split("#", 1)[0]
        values[normalized] = ProjectCandidate(name=name, url=normalized)
    return sorted(values.values(), key=lambda item: item.name.casefold())


def discover_chatgpt_projects(*, profile_dir: Path) -> list[ProjectCandidate]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the PowerPack environment") from exc
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
                print("ChatGPT opened in the selected PowerPack profile.")
                print("Confirm the intended account is active, expand the Projects sidebar/list as needed, then press Enter here.")
                input()
                page.wait_for_timeout(750)
                return _project_candidates_from_page(page)
            finally:
                context.close()
    except PlaywrightError as exc:
        raise RuntimeError("Could not discover ChatGPT Projects from the selected Playwright profile") from exc


def select_chatgpt_project_interactively(*, profile_dir: Path) -> ProjectCandidate:
    """Fallback when sidebar discovery is incomplete: user navigates to any accessible Project."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the PowerPack environment") from exc
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
                print("Navigate in ChatGPT to the Project you want to bind, then press Enter here.")
                input()
                if not is_chatgpt_project_url(page.url):
                    raise RuntimeError("The selected page is not a ChatGPT Project URL ending in /project")
                title = (page.title() or "").strip()
                normalized = page.url.split("?", 1)[0].split("#", 1)[0]
                return ProjectCandidate(name=title or urlparse(normalized).path.split("/")[-2], url=normalized)
            finally:
                context.close()
    except PlaywrightError as exc:
        raise RuntimeError("ChatGPT Project selection browser flow was closed before a Project was selected") from exc


def open_link_and_capture_project(*, profile_dir: Path, url: str, purpose: str) -> ProjectCandidate:
    if not is_chatgpt_url(url):
        raise RuntimeError("Invite/shared link must use https://chatgpt.com")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the PowerPack environment") from exc
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                print(f"Browser opened for {purpose}.")
                print("Complete/accept the invite if necessary and navigate to the target Project, then press Enter here.")
                input()
                if not is_chatgpt_project_url(page.url):
                    raise RuntimeError(
                        "The current ChatGPT page is not a Project. Finish accepting the invite/open the Project and retry."
                    )
                title = (page.title() or "").strip()
                return ProjectCandidate(name=title or urlparse(page.url).path.split("/")[-2], url=page.url.split("?", 1)[0].split("#", 1)[0])
            finally:
                context.close()
    except PlaywrightError as exc:
        raise RuntimeError("ChatGPT invite/project browser flow closed before a Project was selected") from exc


def authorize_chatgpt_project(
    *,
    config_root: Path,
    platform: str,
    profile: str,
    profile_dir: Path,
    project_alias: str,
    project_url: str,
) -> ReviewAuthorizationResult:
    """Compatibility wrapper: authorize account, then validate the requested Project can be opened."""
    account = authorize_chatgpt_account(
        config_root=config_root,
        platform=platform,
        profile=profile,
        profile_dir=profile_dir,
        account_label=profile,
    )
    if not account.granted:
        return ReviewAuthorizationResult(False, profile, project_alias, project_url, platform, str(profile_dir))
    project = open_link_and_capture_project(profile_dir=profile_dir, url=project_url, purpose="ChatGPT Project authorization")
    if not same_chatgpt_project(project.url, project_url):
        raise RuntimeError("The selected ChatGPT Project does not match the requested Project URL")
    return ReviewAuthorizationResult(True, profile, project_alias, project_url, platform, str(profile_dir), account.granted_at)