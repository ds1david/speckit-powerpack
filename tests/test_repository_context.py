from __future__ import annotations

import json
from pathlib import Path
import subprocess

from speckit_powerpack import cli
from speckit_powerpack import repository_context as repoctx


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, text=True, capture_output=True)


def _repo(tmp_path: Path, remote: str | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    if remote:
        _git(repo, "remote", "add", "origin", remote)
    (repo / ".specify" / "powerpack").mkdir(parents=True)
    (repo / ".specify" / "powerpack" / "review.json").write_text(
        json.dumps({
            "schema_version": 3,
            "chatgpt_web": {
                "required": True,
                "enabled": True,
                "profile_scope": "platform",
                "profile": None,
                "project_alias": None,
                "project_url": None,
                "authorization": None,
            },
        }),
        encoding="utf-8",
    )
    return repo


def test_repository_identity_supports_github_gitlab_bitbucket_and_generic(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "global_root", lambda: tmp_path / "config")
    cases = [
        ("git@github.com:ds1david/example.git", "github"),
        ("https://gitlab.com/team/example.git", "gitlab"),
        ("https://bitbucket.org/team/example.git", "bitbucket"),
        ("ssh://git@git.company.local/platform/example.git", "generic-git"),
    ]
    for index, (remote, expected_provider) in enumerate(cases):
        root = tmp_path / f"case-{index}"
        root.mkdir()
        _git(root, "init")
        _git(root, "remote", "add", "origin", remote)
        identity = repoctx.repository_identity(root)
        assert identity.provider == expected_provider
        assert identity.portable is True
        assert identity.remote_name == "origin"
        assert "example" in (identity.path or "")
        assert "@" not in (identity.remote_url or "")


def test_same_remote_gets_same_user_scope_key_across_clones(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir(); second.mkdir()
    for repo in (first, second):
        _git(repo, "init")
        _git(repo, "remote", "add", "origin", "https://github.com/ds1david/shared.git")
    assert repoctx.repository_identity(first).key == repoctx.repository_identity(second).key


def test_no_remote_falls_back_to_local_nonportable_identity(tmp_path: Path):
    repo = tmp_path / "local"
    repo.mkdir(); _git(repo, "init")
    identity = repoctx.repository_identity(repo)
    assert identity.provider == "local"
    assert identity.portable is False
    assert identity.key.startswith("local-")


def test_review_binding_is_written_outside_worktree(monkeypatch, tmp_path: Path):
    config_root = tmp_path / "user-config"
    monkeypatch.setattr(cli, "global_root", lambda: config_root)
    repo = _repo(tmp_path, "https://github.com/ds1david/example.git")
    user_path, effective = repoctx.review_config(repo)
    assert config_root in user_path.parents
    assert repo not in user_path.parents
    assert effective["chatgpt_web"]["required"] is True


def test_legacy_binding_is_migrated_then_removed_from_versioned_review(monkeypatch, tmp_path: Path):
    config_root = tmp_path / "user-config"
    monkeypatch.setattr(cli, "global_root", lambda: config_root)
    repo = _repo(tmp_path, "https://gitlab.com/team/example.git")
    tracked = repo / ".specify" / "powerpack" / "review.json"
    data = json.loads(tracked.read_text(encoding="utf-8"))
    data["chatgpt_web"].update({
        "profile": "ds1david-edge",
        "account_label": "ds1david-plus",
        "project_alias": "atsel",
        "project_url": "https://chatgpt.com/g/g-p-test/project",
        "authorization": "playwright-account-consent",
    })
    tracked.write_text(json.dumps(data), encoding="utf-8")

    assert repoctx.migrate_versioned_local_binding(repo) is True
    sanitized = json.loads(tracked.read_text(encoding="utf-8"))
    assert sanitized["chatgpt_web"]["profile"] is None
    assert sanitized["chatgpt_web"]["project_url"] is None

    user_path, effective = repoctx.review_config(repo)
    assert user_path.is_file()
    assert effective["chatgpt_web"]["profile"] == "ds1david-edge"
    assert effective["chatgpt_web"]["project_alias"] == "atsel"


def test_git_info_exclude_is_managed_without_touching_root_gitignore(tmp_path: Path):
    repo = _repo(tmp_path, "https://bitbucket.org/team/example.git")
    root_ignore = repo / ".gitignore"
    root_ignore.write_text("target/\n", encoding="utf-8")
    exclude = repoctx.ensure_local_git_excludes(repo)
    assert exclude is not None
    text = exclude.read_text(encoding="utf-8")
    assert ".playwright-cli/" in text
    assert ".specify/powerpack/*.local.json" in text
    assert root_ignore.read_text(encoding="utf-8") == "target/\n"

    repoctx.ensure_local_git_excludes(repo)
    text2 = exclude.read_text(encoding="utf-8")
    assert text2.count("# >>> speckit-powerpack local state >>>") == 1
