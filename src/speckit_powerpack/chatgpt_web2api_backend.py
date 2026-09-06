from __future__ import annotations

from dataclasses import dataclass
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from . import windows_browser_bridge as winbridge


BACKEND_ID = "chatgpt-web2api"
DEFAULT_ENDPOINT = "http://127.0.0.1:8080"
DEFAULT_MODEL = "auto"
PROJECT_ID_RE = re.compile(r"g-p-[A-Za-z0-9]+")


class Web2APIError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: str

    def json(self) -> Any:
        try:
            return json.loads(self.body or "null")
        except json.JSONDecodeError as exc:
            raise Web2APIError(f"ChatGPT-Web2API returned invalid JSON (HTTP {self.status}).") from exc


@dataclass(frozen=True)
class ProjectInfo:
    project_id: str
    name: str


@dataclass(frozen=True)
class ChatResult:
    response: str
    conversation_id: str | None
    model: str


def normalize_endpoint(value: str | None) -> str:
    raw = (value or DEFAULT_ENDPOINT).strip().rstrip("/")
    parsed = urlparse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise Web2APIError("Reviewer endpoint must be an http(s) URL, for example http://127.0.0.1:8080.")
    return raw


def project_id_from_value(value: str) -> str | None:
    match = PROJECT_ID_RE.search(value or "")
    return match.group(0) if match else None


def _decode_windows(value: bytes | str | None) -> str:
    return winbridge._decode_windows_output(value)


def _powershell_json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None,
    timeout: int,
) -> HttpResult:
    """Execute loopback HTTP on the Windows host when PowerPack runs in WSL.

    A service bound to Windows 127.0.0.1 is not guaranteed to be reachable from
    WSL's Linux network namespace. Execute the HTTP request in Windows itself,
    then return only status/body across the WSL boundary. No browser/session
    credentials cross that boundary.
    """
    request_body = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    method_b64 = base64.b64encode(method.encode("utf-8")).decode("ascii")
    url_b64 = base64.b64encode(url.encode("utf-8")).decode("ascii")
    body_b64 = base64.b64encode(request_body.encode("utf-8")).decode("ascii")
    script = f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$method = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{method_b64}'))
$url = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{url_b64}'))
$body = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{body_b64}'))
$status = 0
$content = ''
try {{
  if ($body.Length -gt 0) {{
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -Method $method -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec {int(timeout)}
  }} else {{
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -Method $method -TimeoutSec {int(timeout)}
  }}
  $status = [int]$response.StatusCode
  $content = [string]$response.Content
}} catch {{
  $resp = $_.Exception.Response
  if ($null -ne $resp) {{
    try {{ $status = [int]$resp.StatusCode }} catch {{ $status = 500 }}
    try {{
      $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $content = $reader.ReadToEnd()
      $reader.Dispose()
    }} catch {{ $content = $_.Exception.Message }}
  }} else {{
    $status = 599
    $content = $_.Exception.Message
  }}
}}
$result = @{{ status = $status; body = $content }} | ConvertTo-Json -Compress
[Console]::Out.WriteLine($result)
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            text=False,
            capture_output=True,
            timeout=timeout + 20,
        )
    except FileNotFoundError as exc:
        raise Web2APIError("powershell.exe is unavailable from WSL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise Web2APIError(f"Windows ChatGPT-Web2API request timed out after {timeout}s.") from exc
    stdout = _decode_windows(proc.stdout).strip()
    stderr = _decode_windows(proc.stderr).strip()
    if proc.returncode != 0 or not stdout:
        raise Web2APIError(stderr or stdout or "Windows ChatGPT-Web2API request failed.")
    try:
        wrapper = json.loads(stdout.splitlines()[-1])
        return HttpResult(int(wrapper.get("status") or 0), str(wrapper.get("body") or ""))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Web2APIError(f"Could not decode Windows reviewer response: {stdout[-500:]}") from exc


def _urllib_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None,
    timeout: int,
) -> HttpResult:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"} if body is not None else {},
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return HttpResult(int(resp.status), resp.read().decode("utf-8", errors="replace"))
    except urlerror.HTTPError as exc:
        return HttpResult(int(exc.code), exc.read().decode("utf-8", errors="replace"))
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        raise Web2APIError(f"Could not reach ChatGPT-Web2API at {url}: {exc}") from exc


def request_json(
    endpoint: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    endpoint = normalize_endpoint(endpoint)
    url = endpoint + (path if path.startswith("/") else "/" + path)
    host = (urlparse.urlparse(endpoint).hostname or "").casefold()
    if winbridge.is_wsl() and host in {"127.0.0.1", "localhost", "::1"}:
        result = _powershell_json_request(method, url, payload=payload, timeout=timeout)
    else:
        result = _urllib_request(method, url, payload=payload, timeout=timeout)

    if result.status < 200 or result.status >= 300:
        detail = result.body.strip()
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                err = parsed.get("error")
                if isinstance(err, dict) and err.get("message"):
                    detail = str(err["message"])
        except json.JSONDecodeError:
            pass
        raise Web2APIError(f"ChatGPT-Web2API HTTP {result.status}: {detail or 'request failed'}")
    return result.json()


def health(endpoint: str, *, timeout: int = 10) -> dict[str, Any]:
    value = request_json(endpoint, "GET", "/health", timeout=timeout)
    if not isinstance(value, dict):
        raise Web2APIError("ChatGPT-Web2API /health returned a non-object payload.")
    return value


def list_projects(endpoint: str, *, timeout: int = 30) -> list[ProjectInfo]:
    value = request_json(endpoint, "GET", "/v1/projects", timeout=timeout)
    items = value.get("data", []) if isinstance(value, dict) else []
    result: list[ProjectInfo] = []
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        project_id = str(raw.get("id") or raw.get("project_id") or raw.get("gizmo_id") or "").strip()
        if not project_id:
            continue
        name = str(raw.get("name") or raw.get("title") or raw.get("display_name") or project_id).strip()
        result.append(ProjectInfo(project_id=project_id, name=name or project_id))
    return result


def chat(
    endpoint: str,
    *,
    project_id: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 180,
) -> ChatResult:
    if not project_id_from_value(project_id):
        raise Web2APIError(f"Invalid ChatGPT Project id: {project_id!r}")
    if not prompt.strip():
        raise Web2APIError("Reviewer prompt is empty.")
    value = request_json(
        endpoint,
        "POST",
        "/v1/chat/completions",
        payload={
            "model": model or DEFAULT_MODEL,
            "stream": False,
            "project_id": project_id,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    if not isinstance(value, dict):
        raise Web2APIError("ChatGPT-Web2API completion returned a non-object payload.")
    choices = value.get("choices")
    message: dict[str, Any] | None = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        candidate = choices[0].get("message")
        if isinstance(candidate, dict):
            message = candidate
    response = str((message or {}).get("content") or "").strip()
    if not response:
        raise Web2APIError("ChatGPT-Web2API returned an empty assistant response.")
    return ChatResult(
        response=response,
        conversation_id=str(value.get("id")) if value.get("id") else None,
        model=str(value.get("model") or model or DEFAULT_MODEL),
    )


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def start_windows_service(
    *,
    profile: str,
    port: int,
    cdp_port: int,
    install: bool = True,
) -> dict[str, Any]:
    """Install/start one dedicated headed ChatGPT-Web2API reviewer on Windows.

    The service and Chrome profile live on the Windows host. PowerPack in WSL
    communicates with the REST endpoint through Windows loopback, so no port
    proxy or browser-cookie copying is needed.
    """
    if not winbridge.is_wsl():
        raise Web2APIError("Windows reviewer bootstrap is only valid when PowerPack runs under WSL.")
    if not (1024 <= port <= 65535 and 1024 <= cdp_port <= 65535):
        raise Web2APIError("REST/CDP ports must be between 1024 and 65535.")
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "-", profile).strip("-._") or "reviewer"
    install_literal = "$true" if install else "$false"
    script = f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$python = $null
foreach ($name in @('py.exe','python.exe','python')) {{
  $candidate = Get-Command $name -ErrorAction SilentlyContinue
  if ($candidate) {{ $python = $candidate; break }}
}}
if (-not $python) {{ throw 'Python 3.11+ is required on Windows. Install Python, then retry.' }}
$pythonExe = if ($python.Source) {{ [string]$python.Source }} else {{ [string]$python.Name }}
$versionText = & $pythonExe -c "import sys; print(f'{{sys.version_info.major}}.{{sys.version_info.minor}}')"
$parts = $versionText.Trim().Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {{
  throw "Python 3.11+ is required on Windows; detected $versionText"
}}
if ({install_literal}) {{
  & $pythonExe -m pip install --user --upgrade chatgpt-web2api
  if ($LASTEXITCODE -ne 0) {{ throw 'pip install chatgpt-web2api failed.' }}
}}
& $pythonExe -c "import chatgpt_web2api" 2>$null
if ($LASTEXITCODE -ne 0) {{ throw 'chatgpt-web2api is not installed for the selected Windows Python.' }}
$root = Join-Path $env:LOCALAPPDATA 'SpecKitPowerPack\\reviewers\\{_ps_quote(safe_profile)}'
$chromeProfile = Join-Path $root 'chrome-profile'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $chromeProfile,$logs | Out-Null
$stdout = Join-Path $logs 'web2api.out.log'
$stderr = Join-Path $logs 'web2api.err.log'
$args = @('-m','chatgpt_web2api','start','--host','127.0.0.1','--port','{port}','--cdp-port','{cdp_port}','--user-data-dir',$chromeProfile)
$proc = Start-Process -FilePath $pythonExe -ArgumentList $args -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
@{{ pid=$proc.Id; endpoint='http://127.0.0.1:{port}'; profile_dir=$chromeProfile; stdout=$stdout; stderr=$stderr; python=$pythonExe }} | ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            text=False,
            capture_output=True,
            timeout=240,
        )
    except FileNotFoundError as exc:
        raise Web2APIError("powershell.exe is unavailable from WSL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise Web2APIError("Windows ChatGPT-Web2API installation/start timed out.") from exc
    stdout = _decode_windows(proc.stdout).strip()
    stderr = _decode_windows(proc.stderr).strip()
    if proc.returncode != 0:
        raise Web2APIError(stderr or stdout or "Could not start ChatGPT-Web2API on Windows.")
    try:
        return json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise Web2APIError(f"Could not parse Windows service bootstrap response: {stdout[-500:]}") from exc


def wait_for_service(endpoint: str, *, timeout: int = 45) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return health(endpoint, timeout=5)
        except Exception as exc:  # noqa: BLE001 - retain last transport failure for diagnostic
            last = exc
            time.sleep(1)
    raise Web2APIError(f"Reviewer service did not become reachable at {endpoint}: {last}")
