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


@dataclass(frozen=True)
class ReviewAuthorizationResult:
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


def consent_html(*, profile: str, project_alias: str, project_url: str, profile_dir: Path) -> str:
    profile_text = escape(profile)
    alias_text = escape(project_alias)
    url_text = escape(project_url)
    dir_text = escape(str(profile_dir))
    return f"""<!doctype html>
<html lang=\"pt-BR\">
<head>
<meta charset=\"utf-8\">
<title>SpecKit PowerPack — autorização ChatGPT Web</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; background: #111827; color: #f9fafb; }}
main {{ max-width: 760px; margin: 48px auto; padding: 32px; background: #1f2937; border-radius: 16px; }}
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
<h1>Autorizar acesso do PowerPack ao ChatGPT Web?</h1>
<p>O SpecKit PowerPack usa o ChatGPT Web como um segundo gate independente de revisão.</p>
<div class=\"notice\">
<strong>Perfil isolado:</strong> esta autorização usa um Chromium controlado pelo Playwright com armazenamento próprio em<br>
<code>{dir_text}</code>.
</div>
<ul>
<li>Não reutiliza cookies, histórico ou sessão do Edge/Chrome do Windows.</li>
<li>Credenciais e MFA são digitados somente no site oficial do ChatGPT.</li>
<li>A autorização será vinculada somente ao projeto <strong>{alias_text}</strong>.</li>
<li>URL solicitada: <code>{url_text}</code></li>
<li>Você pode revogar removendo o perfil PowerPack posteriormente.</li>
</ul>
<p class=\"small\">Perfil PowerPack: <code>{profile_text}</code></p>
<div class=\"actions\">
<button class=\"primary\" onclick=\"authorize()\">Autorizar e abrir ChatGPT</button>
<button class=\"secondary\" onclick=\"cancel()\">Cancelar</button>
</div>
</section>
<section id=\"grant\">
<h1>Concluir autorização</h1>
<p>O projeto foi aberto em outra aba. Faça login no ChatGPT, confirme que o projeto correto abriu e volte a esta aba.</p>
<div class=\"notice\">
Ao clicar em <strong>Conceder acesso ao projeto</strong>, você confirma que o PowerPack pode reutilizar este perfil isolado nas revisões futuras deste projeto.
</div>
<div class=\"actions\">
<button class=\"primary\" onclick=\"grant()\">Conceder acesso ao projeto</button>
<button class=\"secondary\" onclick=\"cancel()\">Cancelar</button>
</div>
</section>
</main>
</body>
</html>"""


def authorize_chatgpt_project(
    *,
    config_root: Path,
    platform: str,
    profile: str,
    profile_dir: Path,
    project_alias: str,
    project_url: str,
) -> ReviewAuthorizationResult:
    ensure_chromium(config_root, platform)
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed in the PowerPack environment") from exc

    granted = False
    granted_at: str | None = None
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
            try:
                consent = context.pages[0] if context.pages else context.new_page()
                consent.set_content(
                    consent_html(
                        profile=profile,
                        project_alias=project_alias,
                        project_url=project_url,
                        profile_dir=profile_dir,
                    )
                )
                consent.wait_for_function("window.__powerpackDecision !== null", timeout=0)
                decision = consent.evaluate("window.__powerpackDecision")
                if decision != "authorize":
                    return ReviewAuthorizationResult(
                        False, profile, project_alias, project_url, platform, str(profile_dir)
                    )

                chatgpt = context.new_page()
                chatgpt.goto(project_url, wait_until="domcontentloaded")
                consent.evaluate("showGrant()")
                consent.bring_to_front()
                consent.wait_for_function("window.__powerpackGrant !== null", timeout=0)
                final_decision = consent.evaluate("window.__powerpackGrant")
                if final_decision == "grant":
                    granted = True
                    granted_at = utc_now()
                return ReviewAuthorizationResult(
                    granted,
                    profile,
                    project_alias,
                    project_url,
                    platform,
                    str(profile_dir),
                    granted_at,
                )
            finally:
                context.close()
    except PlaywrightError as exc:
        raise RuntimeError(
            "Playwright authorization window was closed or failed before permission was completed"
        ) from exc
