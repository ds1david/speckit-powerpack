from __future__ import annotations

from importlib import metadata
import json
import re
import shutil
import subprocess
from typing import Any

DEFAULT_REPOSITORY = "https://github.com/ds1david/speckit-powerpack.git"
DEFAULT_REF = "main"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class UpdateError(RuntimeError):
    pass


def installed_vcs_info() -> dict[str, Any]:
    """Return PEP 610 VCS metadata when PowerPack was installed from Git."""
    try:
        dist = metadata.distribution("speckit-powerpack")
        raw = dist.read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    vcs = data.get("vcs_info") if isinstance(data, dict) else None
    if not isinstance(vcs, dict):
        return {}
    return {
        "url": data.get("url"),
        "vcs": vcs.get("vcs"),
        "commit_id": vcs.get("commit_id"),
        "requested_revision": vcs.get("requested_revision"),
    }


def effective_source(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    installed = installed_vcs_info()
    repository = str(config.get("repository") or installed.get("url") or DEFAULT_REPOSITORY)
    configured_ref = config.get("ref")
    installed_ref = installed.get("requested_revision")

    # A user who explicitly installed @<commit-sha> selected an immutable build.
    # Do not silently reinterpret that choice as @main during install/init update
    # checks. Moving away from the pinned build requires an explicit configured
    # ref (for example `speckit-powerpack update . --ref main ...`) or a fresh
    # `uv tool install ...@<other-ref>`.
    pinned = False
    if configured_ref:
        ref = str(configured_ref)
    elif installed_ref:
        ref = str(installed_ref)
        pinned = bool(_SHA_RE.fullmatch(ref))
    else:
        ref = DEFAULT_REF

    return {
        "repository": repository,
        "ref": ref,
        "installed_commit": str(installed.get("commit_id")) if installed.get("commit_id") else None,
        "installed_requested_revision": str(installed_ref) if installed_ref else None,
        "pinned": pinned,
    }


def remote_sha(repository: str, ref: str) -> str:
    git = shutil.which("git")
    if not git:
        raise UpdateError("git is required to check PowerPack updates")
    # Prefer a branch, then the peeled commit of an annotated tag, then the
    # tag object/lightweight tag, then the raw ref supplied by the operator.
    refs = [f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", ref]
    for candidate in refs:
        proc = subprocess.run([git, "ls-remote", repository, candidate], text=True, capture_output=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "git ls-remote failed").strip()
            raise UpdateError(detail)
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and _SHA_RE.match(parts[0]):
                return parts[0].lower()
    raise UpdateError(f"could not resolve remote ref '{ref}' from {repository}")


def check_update(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = effective_source(config)
    installed = source.get("installed_commit")

    # Immutable explicit SHA installations are already at the exact revision
    # the operator requested. Do not compare them with DEFAULT_REF/main and do
    # not offer a misleading downgrade/sidegrade as an "update".
    if source.get("pinned") and installed and _SHA_RE.fullmatch(str(installed)):
        return {
            "status": "PINNED",
            "repository": source["repository"],
            "ref": source["ref"],
            "installed_commit": installed,
            "remote_commit": installed,
            "installed_requested_revision": source.get("installed_requested_revision"),
            "pinned": True,
        }

    remote = remote_sha(str(source["repository"]), str(source["ref"]))
    if installed and _SHA_RE.fullmatch(str(installed)):
        status = "CURRENT" if str(installed).lower() == remote else "UPDATE_AVAILABLE"
    else:
        status = "UNKNOWN_INSTALLED_SOURCE"
    return {
        "status": status,
        "repository": source["repository"],
        "ref": source["ref"],
        "installed_commit": installed,
        "remote_commit": remote,
        "installed_requested_revision": source.get("installed_requested_revision"),
        "pinned": bool(source.get("pinned")),
    }


def git_source(repository: str, ref: str) -> str:
    return f"git+{repository}@{ref}"


def update_argv(repository: str, ref: str) -> list[str]:
    uv = shutil.which("uv")
    if not uv:
        raise UpdateError("uv is required to update the installed PowerPack CLI")
    return [uv, "tool", "install", "--force", git_source(repository, ref)]


def apply_self_update(repository: str, ref: str) -> dict[str, Any]:
    argv = update_argv(repository, ref)
    proc = subprocess.run(argv, text=True, capture_output=True)
    if proc.returncode != 0:
        raise UpdateError((proc.stderr or proc.stdout or "PowerPack update failed").strip())
    return {
        "status": "UPDATED",
        "repository": repository,
        "ref": ref,
        "argv": argv,
        "output": (proc.stdout or proc.stderr or "").strip(),
    }
