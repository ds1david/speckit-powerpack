from __future__ import annotations

import base64
import json
from pathlib import Path
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


def windows_cmd_argv(
    args: Iterable[str],
    *,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Execute a Windows command from WSL without cmd.exe argument re-parsing.

    Playwright CLI eval/run-code expressions contain spaces, quotes, braces,
    ampersands and parentheses. Building a cmd.exe command line can split one
    expression into multiple CLI operands. Serialize argv as UTF-8 JSON, embed
    it as Base64 in an EncodedCommand, reconstruct an argument array inside
    PowerShell, and invoke the executable with array splatting.
    """
    if not winbridge.is_wsl():
        raise winbridge.WindowsBrowserBridgeError(
            "Windows browser-context mode is supported from WSL only."
        )

    argv = list(args)
    if not argv:
        raise winbridge.WindowsBrowserBridgeError("Windows command argv cannot be empty.")

    argv_json = json.dumps(argv, ensure_ascii=False)
    argv_b64 = base64.b64encode(argv_json.encode("utf-8")).decode("ascii")
    script = f"""
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$workspace = Join-Path $env:TEMP 'speckit-powerpack-playwright'
New-Item -ItemType Directory -Force -Path $workspace | Out-Null
Set-Location -LiteralPath $workspace
$json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{argv_b64}'))
$argv = @($json | ConvertFrom-Json)
$exe = [string]$argv[0]
$rest = @()
if ($argv.Count -gt 1) {{ $rest = @($argv[1..($argv.Count - 1)]) }}
try {{
  & $exe @rest
  $code = $LASTEXITCODE
  if ($null -eq $code) {{ $code = 0 }}
  exit [int]$code
}} catch {{
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}}
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

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


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    winbridge._windows_cmd = windows_cmd_argv
