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
    """Start the Windows reviewer without letting Web2API own first-login Chrome.

    Chrome 144+ can require an explicit per-browser-instance remote-debugging
    consent at chrome://inspect/#remote-debugging. Starting Web2API before that
    consent is granted makes upstream wait 30 seconds for CDP and then close the
    Chrome process it owns. PowerPack therefore uses a two-phase bootstrap:

    * launch/reuse a detached dedicated Chrome owned by PowerPack;
    * if CDP is not live, return ``waiting-remote-debugging`` and leave Chrome
      open indefinitely so the user can grant consent and complete SSO/MFA;
    * only when CDP is proven live start Web2API, which then attaches as a
      non-owner and cannot close the browser on bridge failure/restart.
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

function Test-HttpOk([string]$url, [int]$timeoutSec = 2) {{
  try {{
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -Method Get -TimeoutSec $timeoutSec
    return ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500)
  }} catch {{
    return $false
  }}
}}

function Wait-HttpOk([string]$url, [int]$seconds) {{
  $deadline = [DateTime]::UtcNow.AddSeconds($seconds)
  while ([DateTime]::UtcNow -lt $deadline) {{
    if (Test-HttpOk $url 2) {{ return $true }}
    Start-Sleep -Milliseconds 500
  }}
  return (Test-HttpOk $url 2)
}}

function Start-DetachedFromSpec([string]$pythonExe, [string]$launcherPath, [string]$specPath) {{
  $childText = (& $pythonExe $launcherPath $specPath | Out-String).Trim()
  $childPid = 0
  if (-not [int]::TryParse($childText, [ref]$childPid)) {{
    throw "Detached launcher did not return a PID: $childText"
  }}
  Start-Sleep -Milliseconds 700
  $child = Get-Process -Id $childPid -ErrorAction SilentlyContinue
  if (-not $child) {{ throw "Detached process $childPid exited during startup." }}
  return $childPid
}}

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
$servicePidFile = Join-Path $root 'service.pid'
$browserPidFile = Join-Path $root 'browser.pid'
$launcherPath = Join-Path $root 'launch-detached.py'
$serviceSpecPath = Join-Path $root 'service-launch.json'
$browserSpecPath = Join-Path $root 'browser-launch.json'
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

$launcherBytes = [Convert]::FromBase64String('{launcher_b64}')
[IO.File]::WriteAllBytes($launcherPath, $launcherBytes)

$endpoint = 'http://127.0.0.1:{port}'
$healthUrl = "$endpoint/health"
$cdpUrl = 'http://127.0.0.1:{cdp_port}/json/version'
$serviceOut = Join-Path $logs 'web2api.out.log'
$serviceErr = Join-Path $logs 'web2api.err.log'
$browserOut = Join-Path $logs 'chrome.out.log'
$browserErr = Join-Path $logs 'chrome.err.log'

# A healthy existing REST bridge wins: do not disturb either service or Chrome.
if (Test-HttpOk $healthUrl 2) {{
  $servicePid = 0
  if (Test-Path $servicePidFile) {{ [int]::TryParse([string](Get-Content $servicePidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$servicePid) | Out-Null }}
  $browserPid = 0
  if (Test-Path $browserPidFile) {{ [int]::TryParse([string](Get-Content $browserPidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$browserPid) | Out-Null }}
  @{{ phase='ready'; pid=$servicePid; browser_pid=$browserPid; endpoint=$endpoint; profile_dir=$chromeProfile; venv=$venv; stdout=$serviceOut; stderr=$serviceErr; browser_stdout=$browserOut; browser_stderr=$browserErr; python=$servicePython; upstream_revision='{WEB2API_REVISION}'; reused=$true; detached=$true; browser_detached=$true }} | ConvertTo-Json -Compress
  exit 0
}}

# Stale bridge: never let it keep driving a browser whose CDP/login state is
# being repaired. The browser itself is handled separately below.
if (Test-Path $servicePidFile) {{
  $existingText = (Get-Content $servicePidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  $existingPid = 0
  if ([int]::TryParse([string]$existingText, [ref]$existingPid)) {{
    $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($existing) {{
      Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 500
    }}
  }}
  Remove-Item $servicePidFile -Force -ErrorAction SilentlyContinue
}}

# Resolve Chrome explicitly. PowerPack owns this browser process; Web2API will
# only attach after CDP consent is proven live.
$chromeExe = $null
$chromeCandidates = @()
if ($env:ProgramFiles) {{ $chromeCandidates += (Join-Path $env:ProgramFiles 'Google\\Chrome\\Application\\chrome.exe') }}
if ($env:'ProgramFiles(x86)') {{ $chromeCandidates += (Join-Path $env:'ProgramFiles(x86)' 'Google\\Chrome\\Application\\chrome.exe') }}
if ($env:LOCALAPPDATA) {{ $chromeCandidates += (Join-Path $env:LOCALAPPDATA 'Google\\Chrome\\Application\\chrome.exe') }}
foreach ($candidate in $chromeCandidates) {{ if (Test-Path $candidate) {{ $chromeExe = $candidate; break }} }}
if (-not $chromeExe) {{
  $chromeCommand = Get-Command chrome.exe -ErrorAction SilentlyContinue
  if ($chromeCommand) {{ $chromeExe = if ($chromeCommand.Source) {{ [string]$chromeCommand.Source }} else {{ [string]$chromeCommand.Name }} }}
}}
if (-not $chromeExe) {{
  [Console]::Error.WriteLine('Google Chrome was not found on Windows. Install Chrome, then retry.')
  exit 16
}}

$browserPid = 0
$browserAlive = $false
if (Test-Path $browserPidFile) {{
  $browserText = (Get-Content $browserPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  if ([int]::TryParse([string]$browserText, [ref]$browserPid)) {{
    $browserAlive = $null -ne (Get-Process -Id $browserPid -ErrorAction SilentlyContinue)
  }}
  if (-not $browserAlive) {{ Remove-Item $browserPidFile -Force -ErrorAction SilentlyContinue }}
}}

if (-not $browserAlive) {{
  $browserArgv = @(
    $chromeExe,
    '--remote-debugging-port={cdp_port}',
    "--user-data-dir=$chromeProfile",
    '--no-first-run',
    '--no-default-browser-check',
    'chrome://inspect/#remote-debugging',
    'https://chatgpt.com/'
  )
  @{{ argv=$browserArgv; stdout=$browserOut; stderr=$browserErr; cwd=$root }} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $browserSpecPath
  try {{
    $browserPid = Start-DetachedFromSpec $pythonExe $launcherPath $browserSpecPath
  }} catch {{
    [Console]::Error.WriteLine("Could not start detached reviewer Chrome: $($_.Exception.Message)")
    exit 17
  }}
  [IO.File]::WriteAllText($browserPidFile, [string]$browserPid)
  $browserAlive = $true
}}

# Chrome 144+ may ignore the requested CDP endpoint until the user explicitly
# checks 'Allow remote debugging for this browser instance'. This is a valid
# onboarding state, not a service failure. Crucially: do NOT start Web2API yet,
# because upstream would own/wait/kill Chrome after its 30s CDP timeout.
if (-not (Wait-HttpOk $cdpUrl 3)) {{
  @{{ phase='waiting-remote-debugging'; pid=0; browser_pid=$browserPid; endpoint=$endpoint; cdp_endpoint='http://127.0.0.1:{cdp_port}'; profile_dir=$chromeProfile; venv=$venv; stdout=$serviceOut; stderr=$serviceErr; browser_stdout=$browserOut; browser_stderr=$browserErr; python=$servicePython; upstream_revision='{WEB2API_REVISION}'; reused=$browserAlive; detached=$true; browser_detached=$true }} | ConvertTo-Json -Compress
  exit 0
}}

# CDP is now live. Web2API sees an existing Chrome and attaches as non-owner.
$serviceArgv = @($servicePython,'-m','chatgpt_web2api','start','--host','127.0.0.1','--port','{port}','--cdp-port','{cdp_port}','--user-data-dir',$chromeProfile)
@{{ argv=$serviceArgv; stdout=$serviceOut; stderr=$serviceErr; cwd=$root }} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $serviceSpecPath
try {{
  $servicePid = Start-DetachedFromSpec $pythonExe $launcherPath $serviceSpecPath
}} catch {{
  $tail = ''
  if (Test-Path $serviceErr) {{ $tail = (Get-Content $serviceErr -Tail 40 -ErrorAction SilentlyContinue | Out-String).Trim() }}
  [Console]::Error.WriteLine("Could not start detached reviewer service: $($_.Exception.Message)`n$tail")
  exit 19
}}
[IO.File]::WriteAllText($servicePidFile, [string]$servicePid)

@{{ phase='service-started'; pid=$servicePid; browser_pid=$browserPid; endpoint=$endpoint; cdp_endpoint='http://127.0.0.1:{cdp_port}'; profile_dir=$chromeProfile; venv=$venv; stdout=$serviceOut; stderr=$serviceErr; browser_stdout=$browserOut; browser_stderr=$browserErr; python=$servicePython; upstream_revision='{WEB2API_REVISION}'; reused=$false; detached=$true; browser_detached=$true }} | ConvertTo-Json -Compress
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


def wait_for_service(endpoint: str, *, timeout: int = 10) -> dict[str, Any]:
    """Wait briefly for REST readiness after CDP has already been proven live."""
    deadline = time.monotonic() + max(1, timeout)
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return health(endpoint, timeout=min(3, max(1, timeout)))
        except Exception as exc:  # noqa: BLE001 - preserve diagnostic only
            last = exc
            time.sleep(0.5)
    return {
        "status": "waiting-login",
        "chrome_running": True,
        "cdp_connected": True,
        "detail": str(last) if last else "REST endpoint is not ready yet",
    }
