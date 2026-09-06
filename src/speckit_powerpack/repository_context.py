from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import cli as core


_EXCLUDE_BEGIN = "# >>> speckit-powerpack local state >>>"
_EXCLUDE_END = "# <<< speckit-powerpack local state <<<"
_EXCLUDE_RULES = (
    ".playwright-cli/",
    ".specify/powerpack/review.local.json",
    ".specify/powerpack/reviews.local.json",
    ".specify/powerpack/auth/",
    ".specify/powerpack/*.local.json",
)
_LOCAL_WEB_KEYS = (
    "project_alias",
    "project_url",
    "project_name",
    "profile",
    "account_label",
    "account_backend",
    "host_scope",
    "automation_browser_id",
    "automation_browser_label",
    "browser_channel",
    "browser_automation",
    "cdp_endpoint",
    "profile_platform",
    "authorization",
)


@dataclass(frozen=True)
class RepositoryIdentity:
    key: str
    canonical: str
    provider: str
    host: str | None
    path: str | None
    remote_name: str | None
    remote_url: str | None
    root: str
    portable: bool


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _repo_root(project: Path) -> Path:
    proc = _git(project, "rev-parse", "--show-toplevel")
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return project.resolve()


def _remote(project: Path) -> tuple[str | None, str | None]:
    origin = _git(project, "remote", "get-url", "origin")
    if origin.returncode == 0 and origin.stdout.strip():
        return "origin", origin.stdout.strip()
    remotes = _git(project, "remote")
    names = [line.strip() for line in remotes.stdout.splitlines() if line.strip()] if remotes.returncode == 0 else []
    if not names:
        return None, None
    name = names[0]
    value = _git(project, "remote", "get-url", name)
    return (name, value.stdout.strip()) if value.returncode == 0 and value.stdout.strip() else (None, None)


def _provider(host: str | None) -> str:
    value = (host or "").casefold()
    if value in {"github.com", "www.github.com"} or "github" in value:
        return "github"
    if value == "gitlab.com" or "gitlab" in value:
        return "gitlab"
    if value == "bitbucket.org" or "bitbucket" in value:
        return "bitbucket"
    if "dev.azure.com" in value or "visualstudio.com" in value or "azure" in value:
        return "azure-devops"
    return "generic-git" if value else "local"


def _strip_credentials_http(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    clean = urlunsplit((parsed.scheme, host + port, parsed.path, parsed.query, ""))
    return host.casefold(), parsed.path, clean


def _normalize_remote(url: str) -> tuple[str, str, str]:
    value = url.strip()
    if "://" in value:
        host, path, clean = _strip_credentials_http(value)
    else:
        # SCP-like Git syntax: git@host:owner/repository.git
        match = re.match(r"^(?:[^@]+@)?([^:]+):(.+)$", value)
        if not match:
            return "", value, value
        host = match.group(1).casefold()
        path = "/" + match.group(2)
        clean = f"{host}:{match.group(2)}"
    path = "/" + path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.rstrip("/")
    return host, path, clean


def repository_identity(project: Path) -> RepositoryIdentity:
    root = _repo_root(project)
    remote_name, remote_url = _remote(root)
    if remote_url:
        host, path, clean_url = _normalize_remote(remote_url)
        canonical = f"git:{host}{path}"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return RepositoryIdentity(
            key=f"git-{digest}",
            canonical=canonical,
            provider=_provider(host),
            host=host or None,
            path=path or None,
            remote_name=remote_name,
            remote_url=clean_url,
            root=str(root),
            portable=True,
        )
    canonical = f"local:{root}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return RepositoryIdentity(
        key=f"local-{digest}",
        canonical=canonical,
        provider="local",
        host=None,
        path=None,
        remote_name=None,
        remote_url=None,
        root=str(root),
        portable=False,
    )


def repository_state_dir(project: Path) -> Path:
    identity = repository_identity(project)
    path = core.global_root() / "repositories" / identity.key
    path.mkdir(parents=True, exist_ok=True)
    if core.os.name != "nt":
        path.chmod(0o700)
    identity_path = path / "identity.json"
    identity_path.write_text(
        json.dumps(asdict(identity), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if core.os.name != "nt":
        identity_path.chmod(0o600)
    return path


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise core.PowerPackError(f"Cannot read PowerPack review config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise core.PowerPackError(f"PowerPack review config {path} must contain an object.")
    return value


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        current = result.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _local_web_values(web: dict[str, Any]) -> dict[str, Any]:
    return {key: web.get(key) for key in _LOCAL_WEB_KEYS if web.get(key) not in {None, ""}}


def migrate_versioned_local_binding(project: Path) -> bool:
    """Move legacy per-user ChatGPT binding fields out of tracked review.json.

    Returns True when review.json was sanitized. The effective local binding is
    preserved in the user-scoped repository state before the tracked file is
    changed.
    """
    project = project.resolve()
    base_path = project / ".specify" / "powerpack" / "review.json"
    if not base_path.is_file():
        return False
    base = _read_object(base_path)
    web = base.get("chatgpt_web")
    if not isinstance(web, dict):
        return False
    local_values = _local_web_values(web)
    if not local_values:
        return False

    user_path = repository_state_dir(project) / "review.json"
    existing_user = _read_object(user_path)
    effective = _deep_merge(base, existing_user)
    user_path.write_text(json.dumps(effective, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if core.os.name != "nt":
        user_path.chmod(0o600)

    sanitized = json.loads(json.dumps(base))
    sanitized_web = sanitized.setdefault("chatgpt_web", {})
    for key in _LOCAL_WEB_KEYS:
        if key in sanitized_web:
            sanitized_web[key] = None
    base_path.write_text(json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def review_config(project: Path) -> tuple[Path, dict[str, Any]]:
    """Return user-scoped repository review path plus effective base+user config.

    Existing callers can keep writing the returned dictionary/path, but writes go
    to ~/.config/speckit-powerpack/repositories/<repo-id>/review.json rather than
    into the Git worktree.
    """
    project = project.resolve()
    base_path = project / ".specify" / "powerpack" / "review.json"
    if not base_path.is_file():
        raise core.PowerPackError("PowerPack review config is missing; install/refresh PowerPack first.")
    base = _read_object(base_path)
    user_path = repository_state_dir(project) / "review.json"
    overlay = _read_object(user_path)
    return user_path, _deep_merge(base, overlay)


def ensure_local_git_excludes(project: Path) -> Path | None:
    """Add local-only ignores without modifying the repository's .gitignore."""
    project = project.resolve()
    proc = _git(project, "rev-parse", "--git-path", "info/exclude")
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    raw = Path(proc.stdout.strip())
    path = raw if raw.is_absolute() else (_repo_root(project) / raw).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = "\n".join((_EXCLUDE_BEGIN, *_EXCLUDE_RULES, _EXCLUDE_END))

    pattern = re.compile(
        re.escape(_EXCLUDE_BEGIN) + r".*?" + re.escape(_EXCLUDE_END),
        flags=re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(block, existing)
    else:
        prefix = existing.rstrip("\n")
        updated = (prefix + "\n\n" if prefix else "") + block + "\n"
    if updated != existing:
        path.write_text(updated, encoding="utf-8")
    return path


def describe_binding(project: Path) -> dict[str, Any]:
    identity = repository_identity(project)
    user_path, effective = review_config(project)
    return {
        "repository": asdict(identity),
        "user_config": str(user_path),
        "chatgpt_web": effective.get("chatgpt_web", {}),
    }
