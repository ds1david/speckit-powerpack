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
.actions {{ display: flex; gap: 12px; margin-top: 28px; }}
button {{ border: 0; border-radius: 8px; padding: 12px 18px; font-weight: 700; cursor: pointer; }}
.primary {{ background: #f9fafb; color: #111827; }}
.secondary {{ background: #374151; color: #f9fafb; }}
#grant {{ display: none; }}
.small {{ color: #d1d5db; font-size: 0.92rem; }}
</style>
<script>
window.__powerpackDecision = null;
window.__powerpackGrant = null;
function authorize() {{ window.__powerpackDecision = 'authorize'; }}
function cancel() {{ window.__powerpackDecision = 'cancel'; window.__powerpackGrant = 'cancel'; }}
function grant() {{ window.__powerpackGrant = 'grant'; }}
function showGrant() {{
  document.getElementById('initial').style.display = 'none';
  document.getElementById('grant').style.display = 'block';
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
<section id=\"grant\">
<h1>Concluir autorização da conta</h1>
<p>Faça login na conta desejada na outra aba. Quando a página normal do ChatGPT estiver aberta, volte aqui.</p>
<div class=\"notice\">
Ao clicar em <strong>Conceder acesso à conta</strong>, você autoriza o PowerPack a reutilizar somente este perfil isolado para reviews Web e seleção de Projects acessíveis por esta conta.
</div>
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
                consent.evaluate("showGrant()")
                consent.bring_to_front()
                consent.wait_for_function("window.__powerpackGrant !== null", timeout=0)
                if consent.evaluate("window.__powerpackGrant") != "grant":
                    return AccountAuthorizationResult(False, profile, platform, str(profile_dir), account_label)
                if not is_chatgpt_url(chatgpt.url):
                    raise RuntimeError(
                        "ChatGPT account authorization was not recorded because the browser did not finish on chatgpt.com. "
                        "Complete login in the ChatGPT tab and authorize again."
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
                print("Confirm the intended account is active and the Projects sidebar is visible, then press Enter here.")
                input()
                page.wait_for_timeout(750)
                return _project_candidates_from_page(page)
            finally:
                context.close()
    except PlaywrightError as exc:
        raise RuntimeError("Could not discover ChatGPT Projects from the selected Playwright profile") from exc


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
