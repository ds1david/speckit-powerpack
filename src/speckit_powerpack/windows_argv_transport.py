from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable

from . import windows_browser_bridge as winbridge


_APPLIED = False


def _windows_local_cwd() -> str | None:
    for candidate in (Path("/mnt/c/Windows/System32"), Path("/mnt/c/Windows"), Path("/mnt/c")):
        if candidate.is_dir():
            return str(candidate)
    return None


def _decode(value: bytes | str | None) -> str:
    return winbridge._decode_windows_output(value)


def _encoded_powershell_argv(args: Iterable[str]) -> str:
    argv = list(args)
    if not argv:
        raise winbridge.WindowsBrowserBridgeError("Windows command argv cannot be empty.")

    argv_json = json.dumps(argv, ensure_ascii=False)
    argv_b64 = base64.b64encode(argv_json.encode("utf-8")).decode("ascii")
    script = f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$workspace = Join-Path $env:TEMP 'speckit-powerpack-playwright'
New-Item -ItemType Directory -Force -Path $workspace | Out-Null
Set-Location -LiteralPath $workspace
$json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{argv_b64}'))
$decoded = ConvertFrom-Json -InputObject $json
if ($null -eq $decoded) {{ throw 'Decoded Windows argv is empty.' }}
$exe = [string]$decoded[0]
$rest = @()
if ($decoded.Count -gt 1) {{
  $rest = [string[]]$decoded[1..($decoded.Count - 1)]
}}
try {{
  $commandInfo = Get-Command $exe -ErrorAction Stop
  $resolved = if ($commandInfo.Source) {{ [string]$commandInfo.Source }} else {{ [string]$commandInfo.Name }}
  & $resolved @rest
  $code = $LASTEXITCODE
  if ($null -eq $code) {{ $code = 0 }}
  exit [int]$code
}} catch {{
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}}
"""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def windows_cmd_argv(
    args: Iterable[str],
    *,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Execute a finite Windows command from WSL without shell re-parsing.

    Playwright CLI eval/run-code expressions contain spaces, quotes, braces,
    ampersands and parentheses. Serialize argv as UTF-8 JSON, reconstruct the
    array inside Windows PowerShell and invoke it via array splatting.

    This function is intentionally for commands expected to terminate. Long-
    lived attach transports use ``start_windows_cmd_argv`` and are proven ready
    by probing the named Playwright session instead of waiting for npx to exit.
    """
    if not winbridge.is_wsl():
        raise winbridge.WindowsBrowserBridgeError(
            "Windows browser-context mode is supported from WSL only."
        )

    encoded = _encoded_powershell_argv(args)
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=_windows_local_cwd(),
            text=False,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise winbridge.WindowsBrowserBridgeError("powershell.exe is unavailable from WSL.") from exc
    except subprocess.TimeoutExpired as exc:
        raise winbridge.WindowsBrowserBridgeError("Windows browser command timed out.") from exc

    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        stdout=_decode(proc.stdout),
        stderr=_decode(proc.stderr),
    )


def start_windows_cmd_argv(args: Iterable[str]) -> subprocess.Popen[bytes]:
    """Start a long-lived Windows command without waiting for its process tree.

    Extension attach can keep a relay/daemon alive after the browser accepts the
    connection. Capturing its stdout/stderr and waiting for EOF can therefore
    make a successful attach look like a timeout. Start it with detached stdio;
    callers must prove readiness by executing a command against the named
    Playwright session.
    """
    if not winbridge.is_wsl():
        raise winbridge.WindowsBrowserBridgeError(
            "Windows browser-context mode is supported from WSL only."
        )

    encoded = _encoded_powershell_argv(args)
    try:
        return subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=_windows_local_cwd(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise winbridge.WindowsBrowserBridgeError("powershell.exe is unavailable from WSL.") from exc
    except OSError as exc:
        raise winbridge.WindowsBrowserBridgeError(
            f"Could not start Windows browser command: {exc}"
        ) from exc


def windows_node_version() -> str | None:
    """Return the Windows-host Node version using the same argv-safe boundary."""
    proc = windows_cmd_argv(["node", "--version"], timeout=30)
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    match = re.search(r"v?\d+(?:\.\d+){0,2}", text)
    return match.group(0) if match else None


def windows_node_compatible() -> bool:
    value = windows_node_version()
    if not value:
        return False
    match = re.search(r"(\d+)", value)
    return bool(match and int(match.group(1)) >= 20)


def ensure_windows_playwright_cli() -> None:
    """Validate the actual Windows Playwright CLI path, not a separate proxy gate."""
    proc = windows_cmd_argv(
        ["npx.cmd", "--yes", winbridge.PLAYWRIGHT_CLI_PACKAGE, "--help"],
        timeout=180,
    )
    if proc.returncode == 0:
        return

    node = windows_node_version()
    detail = (proc.stderr or proc.stdout or "unknown Windows npx/@playwright/cli failure").strip()
    node_text = node or "not detected through PowerPack transport"
    raise winbridge.WindowsBrowserBridgeError(
        "Could not prepare Playwright CLI on Windows through the WSL host bridge. "
        f"Windows Node observed by PowerPack: {node_text}. Underlying npx error: {detail}"
    )


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    winbridge._windows_cmd = windows_cmd_argv
    winbridge.windows_node_version = windows_node_version
    winbridge.windows_node_compatible = windows_node_compatible
    winbridge.ensure_windows_playwright_cli = ensure_windows_playwright_cli
