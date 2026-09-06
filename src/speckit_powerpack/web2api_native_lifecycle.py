from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib import parse as urlparse

from . import chatgpt_web2api_backend as backend
from . import windows_browser_bridge as winbridge
from .chatgpt_web2api_backend import (
    WEB2API_INSTALL_URL,
    WEB2API_REVISION,
    Web2APIError,
)


_BROWSER_CANDIDATES = (
    ("Microsoft Edge", "microsoft-edge"),
    ("Microsoft Edge", "microsoft-edge-stable"),
    ("Google Chrome", "google-chrome"),
    ("Google Chrome", "google-chrome-stable"),
    ("Chromium", "chromium"),
    ("Chromium", "chromium-browser"),
)


def detect_native_browser() -> dict[str, str] | None:
    """Return a Chromium browser installed in the current Linux/macOS runtime.

    WSLg browsers are intentionally preferred for reviewer automation because
    browser, CDP and ChatGPT-Web2API then share one network/process namespace;
    no PowerShell argv transport, Windows loopback bridge or cross-OS CDP proxy
    is required.
    """
    for name, command in _BROWSER_CANDIDATES:
        path = shutil.which(command)
        if path:
            return {"name": name, "command": command, "path": str(Path(path).resolve())}
    return None


def _decode_http_result(result: backend.HttpResult) -> Any:
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


def install_wsl_local_first_transport() -> None:
    """Prefer WSL-local loopback, retaining Windows-host loopback as fallback.

    The original backend routes every WSL localhost request through PowerShell
    because the reviewer initially lived on the Windows host. Once a browser and
    reviewer service are available natively in WSL, that routing is backwards.
    Patch the backend once so localhost is attempted in Linux first; only a
    connection-level failure falls back to the original Windows transport.
    """
    if not winbridge.is_wsl() or getattr(backend, "_powerpack_wsl_local_first", False):
        return

    original = backend.request_json

    def local_first_request_json(
        endpoint: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> Any:
        normalized = backend.normalize_endpoint(endpoint)
        host = (urlparse.urlparse(normalized).hostname or "").casefold()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return original(normalized, method, path, payload=payload, timeout=timeout)

        url = normalized + (path if path.startswith("/") else "/" + path)
        try:
            result = backend._urllib_request(method, url, payload=payload, timeout=timeout)
        except Web2APIError as local_error:
            try:
                return original(normalized, method, path, payload=payload, timeout=timeout)
            except Web2APIError as windows_error:
                raise Web2APIError(
                    "Could not reach the reviewer on WSL-local loopback or the Windows-host fallback. "
                    f"WSL: {local_error}; Windows: {windows_error}"
                ) from windows_error
        return _decode_http_result(result)

    backend.request_json = local_first_request_json
    setattr(backend, "_powerpack_wsl_local_first", True)


def _safe_profile(profile: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", profile).strip("-._") or "reviewer"


def _read_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _tail(path: Path, lines: int = 50) -> str:
    try:
        values = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(values[-lines:])
    except OSError:
        return ""


def _module_importable(python: Path) -> bool:
    proc = subprocess.run(
        [str(python), "-c", "import chatgpt_web2api"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _ensure_reviewer_environment(root: Path, *, install: bool) -> Path:
    venv = root / "venv"
    service_python = venv / "bin" / "python"
    revision_file = root / "web2api.revision"

    if not service_python.is_file():
        if not install:
            raise Web2APIError(
                f"Dedicated reviewer environment is missing: {service_python}. "
                "Re-run service start without --no-install."
            )
        proc = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not service_python.is_file():
            raise Web2APIError(
                "Could not create the dedicated WSL reviewer virtual environment. "
                + (proc.stderr.strip() or proc.stdout.strip())
            )

    installed_revision = revision_file.read_text(encoding="utf-8").strip() if revision_file.exists() else ""
    need_install = installed_revision != WEB2API_REVISION or not _module_importable(service_python)
    if need_install:
        if not install:
            raise Web2APIError(
                "Pinned ChatGPT-Web2API is not installed in the dedicated reviewer environment. "
                "Re-run without --no-install."
            )
        proc = subprocess.run(
            [
                str(service_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--upgrade",
                WEB2API_INSTALL_URL,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not _module_importable(service_python):
            diagnostic = (proc.stderr or proc.stdout)[-5000:]
            raise Web2APIError(
                "Could not install pinned ChatGPT-Web2API in the WSL reviewer environment.\n" + diagnostic
            )
        revision_file.write_text(WEB2API_REVISION + "\n", encoding="utf-8")

    return service_python


def start_native_service(
    *,
    config_root: Path,
    profile: str,
    port: int,
    cdp_port: int,
    install: bool = True,
    browser: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Install/start one headed ChatGPT-Web2API reviewer in the current OS.

    On WSL this is deliberately a WSL-native process using WSLg. Microsoft Edge
    is supported because upstream accepts an explicit ``--chrome-path`` and the
    browser is Chromium/CDP compatible.
    """
    if not (1024 <= port <= 65535 and 1024 <= cdp_port <= 65535):
        raise Web2APIError("REST/CDP ports must be between 1024 and 65535.")
    browser = browser or detect_native_browser()
    if not browser:
        raise Web2APIError("No native Chromium browser was found in the current runtime.")

    install_wsl_local_first_transport()
    safe_profile = _safe_profile(profile)
    root = config_root / "reviewers" / safe_profile
    browser_profile = root / "browser-profile"
    logs = root / "logs"
    pid_file = root / "service.pid"
    root.mkdir(parents=True, exist_ok=True)
    browser_profile.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass

    service_python = _ensure_reviewer_environment(root, install=install)
    endpoint = f"http://127.0.0.1:{port}"
    stdout_path = logs / "web2api.out.log"
    stderr_path = logs / "web2api.err.log"

    try:
        state = backend.health(endpoint, timeout=2)
        return {
            "phase": "ready",
            "pid": _read_pid(pid_file) or 0,
            "endpoint": endpoint,
            "profile_dir": str(browser_profile),
            "venv": str(root / "venv"),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "browser_name": browser["name"],
            "browser_path": browser["path"],
            "host_scope": "wsl-native" if winbridge.is_wsl() else "native",
            "upstream_revision": WEB2API_REVISION,
            "health": state,
            "reused": True,
        }
    except Web2APIError:
        pass

    existing_pid = _read_pid(pid_file)
    if _pid_alive(existing_pid):
        return {
            "phase": "waiting-login",
            "pid": existing_pid or 0,
            "endpoint": endpoint,
            "profile_dir": str(browser_profile),
            "venv": str(root / "venv"),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "browser_name": browser["name"],
            "browser_path": browser["path"],
            "host_scope": "wsl-native" if winbridge.is_wsl() else "native",
            "upstream_revision": WEB2API_REVISION,
            "reused": True,
        }
    pid_file.unlink(missing_ok=True)

    argv = [
        str(service_python),
        "-m",
        "chatgpt_web2api",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--cdp-port",
        str(cdp_port),
        "--chrome-path",
        browser["path"],
        "--user-data-dir",
        str(browser_profile),
    ]
    stdout_handle = stdout_path.open("ab", buffering=0)
    stderr_handle = stderr_path.open("ab", buffering=0)
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            cwd=str(root),
            close_fds=True,
            start_new_session=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()

    pid_file.write_text(str(proc.pid) + "\n", encoding="utf-8")
    time.sleep(1.0)
    if proc.poll() is not None:
        pid_file.unlink(missing_ok=True)
        raise Web2APIError(
            f"Native reviewer process exited during startup (code {proc.returncode}).\n{_tail(stderr_path)}"
        )

    return {
        "phase": "service-started",
        "pid": proc.pid,
        "endpoint": endpoint,
        "profile_dir": str(browser_profile),
        "venv": str(root / "venv"),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "browser_name": browser["name"],
        "browser_path": browser["path"],
        "host_scope": "wsl-native" if winbridge.is_wsl() else "native",
        "upstream_revision": WEB2API_REVISION,
        "reused": False,
    }


def wait_for_native_service(info: dict[str, Any], *, timeout: int = 45) -> dict[str, Any]:
    """Wait for REST while also proving the native reviewer process stays alive."""
    endpoint = str(info["endpoint"])
    pid = int(info.get("pid") or 0)
    stderr_path = Path(str(info.get("stderr") or ""))
    deadline = time.monotonic() + max(1, timeout)
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return backend.health(endpoint, timeout=min(3, max(1, timeout)))
        except Exception as exc:  # noqa: BLE001 - diagnostic preserved below
            last = exc
        if pid and not _pid_alive(pid):
            raise Web2APIError(
                "Native ChatGPT-Web2API reviewer exited before REST became ready.\n" + _tail(stderr_path)
            )
        time.sleep(0.5)
    return {
        "status": "waiting-login",
        "chrome_running": True,
        "cdp_connected": True,
        "detail": str(last) if last else "REST endpoint is not ready yet",
    }
