from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from typing import Any

from . import windows_browser_bridge as winbridge
from .chatgpt_web2api_backend import (
    WEB2API_INSTALL_URL,
    WEB2API_REVISION,
    Web2APIError,
    health,
)


def _decode_windows(value: bytes | str | None) -> str:
    return winbridge._decode_windows_output(value)


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def start_windows_service(
    *,
    profile: str,
    port: int,
    cdp_port: int,
    install: bool = True,
) -> dict[str, Any]:
    """Start ChatGPT-Web2API detached from the WSL/PowerShell console lifetime.

    First-time ChatGPT login can take several minutes. A normal Start-Process
    child can still share enough console/job lifetime with powershell.exe that
    terminating the WSL wrapper closes the service and its owned Chrome. This
    launcher uses Windows DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP from a
    tiny Python bootstrap and records the PID for idempotent reuse.
    """
    if not winbridge.is_wsl():
        raise Web2APIError("Detached Windows reviewer bootstrap is only valid under WSL.")
    if not (1024 <= port <= 65535 and 1024 <= cdp_port <= 65535):
        raise Web2APIError("REST/CDP ports must be between 1024 and 65535.")

    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "-", profile).strip("-._") or "reviewer"
    install_literal = "$true" if install else "$false"
    source_url = _ps_quote(WEB2API_INSTALL_URL)

    launcher_source = r'''from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

spec_path = Path(sys.argv[1])
with spec_path.open("r", encoding="utf-8-sig") as handle:
    spec = json.load(handle)

flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
)
stdout = open(spec["stdout"], "ab", buffering=0)
stderr = open(spec["stderr"], "ab", buffering=0)
proc = subprocess.Popen(
    spec["argv"],
    stdin=subprocess.DEVNULL,
    stdout=stdout,
    stderr=stderr,
    cwd=spec["cwd"],
    close_fds=True,
    creationflags=flags,
)
print(proc.pid)
'''
    launcher_b64 = base64.b64encode(launcher_source.encode("utf-8")).decode("ascii")

    script = f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$python = $null
foreach ($name in @('py.exe','python.exe','python')) {{
  $candidate = Get-Command $name -ErrorAction SilentlyContinue
  if ($candidate) {{ $python = $candidate; break }}
}}
if (-not $python) {{
  [Console]::Error.WriteLine('Python 3.11+ is required on Windows. Install Python, then retry.')
  exit 10
}}
$pythonExe = if ($python.Source) {{ [string]$python.Source }} else {{ [string]$python.Name }}
$versionText = & $pythonExe -c "import sys; print(f'{{sys.version_info.major}}.{{sys.version_info.minor}}')"
$parts = $versionText.Trim().Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {{
  [Console]::Error.WriteLine("Python 3.11+ is required on Windows; detected $versionText")
  exit 11
}}

$root = Join-Path $env:LOCALAPPDATA 'SpecKitPowerPack\\reviewers\\{_ps_quote(safe_profile)}'
$venv = Join-Path $root 'venv'
$chromeProfile = Join-Path $root 'chrome-profile'
$logs = Join-Path $root 'logs'
$pidFile = Join-Path $root 'service.pid'
$launcherPath = Join-Path $root 'launch-detached.py'
$specPath = Join-Path $root 'service-launch.json'
New-Item -ItemType Directory -Force -Path $root,$chromeProfile,$logs | Out-Null
$servicePython = Join-Path $venv 'Scripts\\python.exe'

if ({install_literal} -and -not (Test-Path $servicePython)) {{
  & $pythonExe -m venv $venv
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $servicePython)) {{
    [Console]::Error.WriteLine('Could not create the dedicated ChatGPT-Web2API virtual environment.')
    exit 12
  }}
}}
if (-not (Test-Path $servicePython)) {{
  [Console]::Error.WriteLine("Dedicated reviewer environment is missing: $servicePython. Re-run service start without --no-install.")
  exit 13
}}

if ({install_literal}) {{
  $source = '{source_url}'
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {{
    $pipOutput = (& $servicePython -m pip install --disable-pip-version-check --no-warn-script-location --upgrade $source 2>&1 | Out-String)
    $pipExitCode = $LASTEXITCODE
  }} finally {{
    $ErrorActionPreference = $previousErrorActionPreference
  }}
  if ($pipExitCode -ne 0) {{
    [Console]::Error.WriteLine("Could not install pinned ChatGPT-Web2API from $source.`n$($pipOutput.Trim())")
    exit 14
  }}
}}

& $servicePython -c "import chatgpt_web2api" 2>$null
if ($LASTEXITCODE -ne 0) {{
  [Console]::Error.WriteLine('ChatGPT-Web2API is not importable from the dedicated reviewer environment after installation.')
  exit 15
}}

$stdout = Join-Path $logs 'web2api.out.log'
$stderr = Join-Path $logs 'web2api.err.log'

if (Test-Path $pidFile) {{
  $existingText = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  $existingPid = 0
  if ([int]::TryParse([string]$existingText, [ref]$existingPid)) {{
    $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($existing) {{
      @{{ pid=$existingPid; endpoint='http://127.0.0.1:{port}'; profile_dir=$chromeProfile; venv=$venv; stdout=$stdout; stderr=$stderr; python=$servicePython; upstream_revision='{WEB2API_REVISION}'; reused=$true; detached=$true }} | ConvertTo-Json -Compress
      exit 0
    }}
  }}
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}}

$launcherBytes = [Convert]::FromBase64String('{launcher_b64}')
[IO.File]::WriteAllBytes($launcherPath, $launcherBytes)
$argv = @($servicePython,'-m','chatgpt_web2api','start','--host','127.0.0.1','--port','{port}','--cdp-port','{cdp_port}','--user-data-dir',$chromeProfile)
@{{ argv=$argv; stdout=$stdout; stderr=$stderr; cwd=$root }} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $specPath

$childText = (& $pythonExe $launcherPath $specPath | Out-String).Trim()
$childPid = 0
if (-not [int]::TryParse($childText, [ref]$childPid)) {{
  [Console]::Error.WriteLine("Detached reviewer launcher did not return a PID: $childText")
  exit 16
}}
Start-Sleep -Milliseconds 1000
$child = Get-Process -Id $childPid -ErrorAction SilentlyContinue
if (-not $child) {{
  $tail = ''
  if (Test-Path $stderr) {{ $tail = (Get-Content $stderr -Tail 40 -ErrorAction SilentlyContinue | Out-String).Trim() }}
  [Console]::Error.WriteLine("Detached reviewer process exited during startup.`n$tail")
  exit 17
}}
[IO.File]::WriteAllText($pidFile, [string]$childPid)
@{{ pid=$childPid; endpoint='http://127.0.0.1:{port}'; profile_dir=$chromeProfile; venv=$venv; stdout=$stdout; stderr=$stderr; python=$servicePython; upstream_revision='{WEB2API_REVISION}'; reused=$false; detached=$true }} | ConvertTo-Json -Compress
"""

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            text=False,
            capture_output=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise Web2APIError("powershell.exe is unavailable from WSL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise Web2APIError("Windows ChatGPT-Web2API installation/start timed out.") from exc

    stdout = _decode_windows(proc.stdout).strip()
    stderr = _decode_windows(proc.stderr).strip()
    if proc.returncode != 0:
        raise Web2APIError(stderr or stdout or "Could not start detached ChatGPT-Web2API on Windows.")
    try:
        return json.loads(stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise Web2APIError(f"Could not parse detached reviewer bootstrap response: {stdout[-500:]}") from exc


def wait_for_service(endpoint: str, *, timeout: int = 45) -> dict[str, Any]:
    """Wait briefly for REST readiness without killing a legitimate login flow.

    ChatGPT-Web2API starts the REST listener only after the browser session is
    authenticated. On first setup the user may legitimately need several
    minutes for Google/SSO/MFA. Timeout therefore means WAITING_FOR_LOGIN, not
    service failure; explicit `review service status` remains the live gate.
    """
    deadline = time.monotonic() + max(1, timeout)
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return health(endpoint, timeout=min(5, max(1, timeout)))
        except Exception as exc:  # noqa: BLE001 - preserve diagnostic only
            last = exc
            time.sleep(1)
    return {
        "status": "waiting-login",
        "chrome_running": None,
        "cdp_connected": None,
        "detail": str(last) if last else "REST endpoint is not ready yet",
    }
