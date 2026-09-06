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


_DETACHED_LAUNCHER_SOURCE = r"""from __future__ import annotations
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
"""

_TCP_BRIDGE_SOURCE = r"""from __future__ import annotations
import select
import socket
import socketserver
import sys

listen_port = int(sys.argv[1])
target_port = int(sys.argv[2])


class BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = socket.AF_INET


class BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        upstream = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        upstream.settimeout(10)
        try:
            upstream.connect(("::1", target_port, 0, 0))
            self.request.setblocking(False)
            upstream.setblocking(False)
            sockets = [self.request, upstream]
            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 30)
                if exceptional:
                    return
                if not readable:
                    continue
                for source in readable:
                    try:
                        chunk = source.recv(65536)
                    except (ConnectionResetError, OSError):
                        return
                    if not chunk:
                        return
                    target = upstream if source is self.request else self.request
                    try:
                        target.sendall(chunk)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
        finally:
            try:
                upstream.close()
            except OSError:
                pass


with BridgeServer(("127.0.0.1", listen_port), BridgeHandler) as server:
    server.serve_forever(poll_interval=0.5)
"""


def start_windows_service(
    *,
    profile: str,
    port: int,
    cdp_port: int,
    install: bool = True,
) -> dict[str, Any]:
    """Start a Windows reviewer while isolating Chrome from Web2API lifecycle.

    Modern Chrome on Windows can expose the DevTools endpoint only on IPv6
    loopback (``[::1]``), while the pinned ChatGPT-Web2API revision probes CDP
    exclusively through ``127.0.0.1``. PowerPack therefore:

    * owns a detached, persistent Chrome profile/browser;
    * waits for explicit remote-debugging consent without starting Web2API;
    * probes both IPv4 and IPv6 loopback;
    * when Chrome is IPv6-only, starts a user-space IPv4->IPv6 TCP bridge on a
      private dynamic loopback port and gives that port to Web2API;
    * starts Web2API only after a usable IPv4 CDP endpoint is proven live.

    No elevation, ``netsh portproxy`` or silent browser/account fallback is
    required. The bridge is profile-scoped and persisted beside the reviewer.
    """
    if not winbridge.is_wsl():
        raise Web2APIError("Detached Windows reviewer bootstrap is only valid under WSL.")
    if not (1024 <= port <= 65535 and 1024 <= cdp_port <= 65535):
        raise Web2APIError("REST/CDP ports must be between 1024 and 65535.")

    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "-", profile).strip("-._") or "reviewer"
    install_literal = "$true" if install else "$false"
    source_url = _ps_quote(WEB2API_INSTALL_URL)
    launcher_b64 = base64.b64encode(_DETACHED_LAUNCHER_SOURCE.encode("utf-8")).decode("ascii")
    bridge_b64 = base64.b64encode(_TCP_BRIDGE_SOURCE.encode("utf-8")).decode("ascii")

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
    Start-Sleep -Milliseconds 400
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

function Get-FreeIpv4LoopbackPort {{
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  try {{
    $listener.Start()
    return [int]$listener.LocalEndpoint.Port
  }} finally {{
    $listener.Stop()
  }}
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
$bridgePidFile = Join-Path $root 'cdp-bridge.pid'
$bridgePortFile = Join-Path $root 'cdp-bridge.port'
$launcherPath = Join-Path $root 'launch-detached.py'
$bridgePath = Join-Path $root 'cdp-ipv4-ipv6-bridge.py'
$serviceSpecPath = Join-Path $root 'service-launch.json'
$browserSpecPath = Join-Path $root 'browser-launch.json'
$bridgeSpecPath = Join-Path $root 'cdp-bridge-launch.json'
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

[IO.File]::WriteAllBytes($launcherPath, [Convert]::FromBase64String('{launcher_b64}'))
[IO.File]::WriteAllBytes($bridgePath, [Convert]::FromBase64String('{bridge_b64}'))

$endpoint = 'http://127.0.0.1:{port}'
$healthUrl = "$endpoint/health"
$requestedCdpPort = {cdp_port}
$cdpV4Url = "http://127.0.0.1:$requestedCdpPort/json/version"
$cdpV6Url = "http://[::1]:$requestedCdpPort/json/version"
$serviceOut = Join-Path $logs 'web2api.out.log'
$serviceErr = Join-Path $logs 'web2api.err.log'
$browserOut = Join-Path $logs 'chrome.out.log'
$browserErr = Join-Path $logs 'chrome.err.log'
$bridgeOut = Join-Path $logs 'cdp-bridge.out.log'
$bridgeErr = Join-Path $logs 'cdp-bridge.err.log'

if (Test-HttpOk $healthUrl 2) {{
  $servicePid = 0
  if (Test-Path $servicePidFile) {{
    [int]::TryParse([string](Get-Content $servicePidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$servicePid) | Out-Null
  }}
  $browserPid = 0
  if (Test-Path $browserPidFile) {{
    [int]::TryParse([string](Get-Content $browserPidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$browserPid) | Out-Null
  }}
  $bridgePid = 0
  if (Test-Path $bridgePidFile) {{
    [int]::TryParse([string](Get-Content $bridgePidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$bridgePid) | Out-Null
  }}
  @{{ phase='ready'; pid=$servicePid; browser_pid=$browserPid; bridge_pid=$bridgePid; endpoint=$endpoint; profile_dir=$chromeProfile; stdout=$serviceOut; stderr=$serviceErr; browser_stderr=$browserErr; cdp_transport='existing'; upstream_revision='{WEB2API_REVISION}' }} | ConvertTo-Json -Compress
  exit 0
}}

if (Test-Path $servicePidFile) {{
  $existingPid = 0
  [int]::TryParse([string](Get-Content $servicePidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$existingPid) | Out-Null
  $existing = if ($existingPid -gt 0) {{ Get-Process -Id $existingPid -ErrorAction SilentlyContinue }} else {{ $null }}
  if ($existing) {{ Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue }}
  Remove-Item $servicePidFile -Force -ErrorAction SilentlyContinue
}}

$chromeExe = $null
$chromeCandidates = @()
$programFiles = [Environment]::GetEnvironmentVariable('ProgramFiles')
$programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
if ($programFiles) {{ $chromeCandidates += (Join-Path $programFiles 'Google\\Chrome\\Application\\chrome.exe') }}
if ($programFilesX86) {{ $chromeCandidates += (Join-Path $programFilesX86 'Google\\Chrome\\Application\\chrome.exe') }}
if ($env:LOCALAPPDATA) {{ $chromeCandidates += (Join-Path $env:LOCALAPPDATA 'Google\\Chrome\\Application\\chrome.exe') }}
foreach ($candidate in $chromeCandidates) {{
  if (Test-Path $candidate) {{ $chromeExe = $candidate; break }}
}}
if (-not $chromeExe) {{
  $chromeCommand = Get-Command chrome.exe -ErrorAction SilentlyContinue
  if ($chromeCommand) {{
    $chromeExe = if ($chromeCommand.Source) {{ [string]$chromeCommand.Source }} else {{ [string]$chromeCommand.Name }}
  }}
}}
if (-not $chromeExe) {{
  [Console]::Error.WriteLine('Google Chrome was not found on Windows. Install Chrome, then retry.')
  exit 16
}}

$browserPid = 0
$browserAlive = $false
if (Test-Path $browserPidFile) {{
  [int]::TryParse([string](Get-Content $browserPidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$browserPid) | Out-Null
  if ($browserPid -gt 0) {{
    $browserAlive = $null -ne (Get-Process -Id $browserPid -ErrorAction SilentlyContinue)
  }}
  if (-not $browserAlive) {{ Remove-Item $browserPidFile -Force -ErrorAction SilentlyContinue }}
}}

if (-not $browserAlive) {{
  $browserArgv = @(
    $chromeExe,
    "--remote-debugging-port=$requestedCdpPort",
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

$v6Live = Test-HttpOk $cdpV6Url 2
$v4Live = Test-HttpOk $cdpV4Url 2
if (-not $v6Live -and -not $v4Live) {{
  @{{ phase='waiting-remote-debugging'; pid=0; browser_pid=$browserPid; endpoint=$endpoint; chrome_cdp_ipv4=$cdpV4Url; chrome_cdp_ipv6=$cdpV6Url; profile_dir=$chromeProfile; stdout=$serviceOut; stderr=$serviceErr; browser_stderr=$browserErr; cdp_transport='not-ready'; upstream_revision='{WEB2API_REVISION}' }} | ConvertTo-Json -Compress
  exit 0
}}

$web2apiCdpPort = $requestedCdpPort
$cdpTransport = 'ipv4-direct'
$bridgePid = 0
$bridgePort = 0

if ($v6Live) {{
  $cdpTransport = 'ipv6-via-user-bridge'

  $bridgeReady = $false
  if ((Test-Path $bridgePidFile) -and (Test-Path $bridgePortFile)) {{
    [int]::TryParse([string](Get-Content $bridgePidFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$bridgePid) | Out-Null
    [int]::TryParse([string](Get-Content $bridgePortFile -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$bridgePort) | Out-Null
    $bridgeProc = if ($bridgePid -gt 0) {{ Get-Process -Id $bridgePid -ErrorAction SilentlyContinue }} else {{ $null }}
    if ($bridgeProc -and $bridgePort -gt 0) {{
      $bridgeReady = Test-HttpOk "http://127.0.0.1:$bridgePort/json/version" 2
    }}
    if (-not $bridgeReady) {{
      if ($bridgeProc) {{ Stop-Process -Id $bridgePid -Force -ErrorAction SilentlyContinue }}
      Remove-Item $bridgePidFile,$bridgePortFile -Force -ErrorAction SilentlyContinue
      $bridgePid = 0
      $bridgePort = 0
    }}
  }}

  if (-not $bridgeReady) {{
    $bridgePort = Get-FreeIpv4LoopbackPort
    $bridgeArgv = @($pythonExe,$bridgePath,[string]$bridgePort,[string]$requestedCdpPort)
    @{{ argv=$bridgeArgv; stdout=$bridgeOut; stderr=$bridgeErr; cwd=$root }} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $bridgeSpecPath
    try {{
      $bridgePid = Start-DetachedFromSpec $pythonExe $launcherPath $bridgeSpecPath
    }} catch {{
      [Console]::Error.WriteLine("Could not start IPv4-to-IPv6 CDP bridge: $($_.Exception.Message)")
      exit 18
    }}
    [IO.File]::WriteAllText($bridgePidFile, [string]$bridgePid)
    [IO.File]::WriteAllText($bridgePortFile, [string]$bridgePort)
    if (-not (Wait-HttpOk "http://127.0.0.1:$bridgePort/json/version" 5)) {{
      [Console]::Error.WriteLine("Chrome CDP is live on [::1]:$requestedCdpPort, but the local IPv4 bridge on 127.0.0.1:$bridgePort did not become ready. See $bridgeErr")
      exit 19
    }}
  }}

  $web2apiCdpPort = $bridgePort
}}

$serviceArgv = @(
  $servicePython,
  '-m','chatgpt_web2api','start',
  '--host','127.0.0.1',
  '--port','{port}',
  '--cdp-port',[string]$web2apiCdpPort,
  '--user-data-dir',$chromeProfile
)
@{{ argv=$serviceArgv; stdout=$serviceOut; stderr=$serviceErr; cwd=$root }} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $serviceSpecPath
try {{
  $servicePid = Start-DetachedFromSpec $pythonExe $launcherPath $serviceSpecPath
}} catch {{
  $tail = ''
  if (Test-Path $serviceErr) {{
    $tail = (Get-Content $serviceErr -Tail 40 -ErrorAction SilentlyContinue | Out-String).Trim()
  }}
  [Console]::Error.WriteLine("Could not start detached reviewer service: $($_.Exception.Message)`n$tail")
  exit 20
}}
[IO.File]::WriteAllText($servicePidFile, [string]$servicePid)

@{{
  phase='service-started';
  pid=$servicePid;
  browser_pid=$browserPid;
  bridge_pid=$bridgePid;
  bridge_port=$bridgePort;
  endpoint=$endpoint;
  chrome_cdp_ipv4=$cdpV4Url;
  chrome_cdp_ipv6=$cdpV6Url;
  web2api_cdp_port=$web2apiCdpPort;
  cdp_transport=$cdpTransport;
  profile_dir=$chromeProfile;
  stdout=$serviceOut;
  stderr=$serviceErr;
  browser_stderr=$browserErr;
  bridge_stderr=$bridgeErr;
  upstream_revision='{WEB2API_REVISION}'
}} | ConvertTo-Json -Compress
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
