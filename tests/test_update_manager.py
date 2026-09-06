from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from speckit_powerpack import update_manager as updates


class FakeDistribution:
    def __init__(self, payload):
        self.payload = payload

    def read_text(self, name):
        assert name == "direct_url.json"
        return json.dumps(self.payload)


def test_effective_source_follows_installed_feature_branch(monkeypatch):
    monkeypatch.setattr(
        updates.metadata,
        "distribution",
        lambda name: FakeDistribution({
            "url": "https://github.com/ds1david/speckit-powerpack.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "a" * 40,
                "requested_revision": "feat/example",
            },
        }),
    )
    source = updates.effective_source({})
    assert source["ref"] == "feat/example"
    assert source["installed_commit"] == "a" * 40
    assert source["pinned"] is False


def test_exact_commit_install_remains_pinned_instead_of_falling_back_to_main(monkeypatch):
    commit = "a" * 40
    monkeypatch.setattr(
        updates.metadata,
        "distribution",
        lambda name: FakeDistribution({
            "url": updates.DEFAULT_REPOSITORY,
            "vcs_info": {
                "vcs": "git",
                "commit_id": commit,
                "requested_revision": commit,
            },
        }),
    )
    source = updates.effective_source({})
    assert source["ref"] == commit
    assert source["pinned"] is True


def test_check_update_does_not_compare_pinned_sha_with_main(monkeypatch):
    commit = "a" * 40
    monkeypatch.setattr(
        updates,
        "effective_source",
        lambda config=None: {
            "repository": updates.DEFAULT_REPOSITORY,
            "ref": commit,
            "installed_commit": commit,
            "installed_requested_revision": commit,
            "pinned": True,
        },
    )

    def should_not_run(*args, **kwargs):
        raise AssertionError("remote_sha must not run for an immutable pinned build")

    monkeypatch.setattr(updates, "remote_sha", should_not_run)
    result = updates.check_update({})
    assert result["status"] == "PINNED"
    assert result["installed_commit"] == commit
    assert result["remote_commit"] == commit
    assert result["ref"] == commit


def test_explicit_config_ref_can_move_away_from_pinned_install(monkeypatch):
    commit = "a" * 40
    monkeypatch.setattr(
        updates.metadata,
        "distribution",
        lambda name: FakeDistribution({
            "url": updates.DEFAULT_REPOSITORY,
            "vcs_info": {
                "vcs": "git",
                "commit_id": commit,
                "requested_revision": commit,
            },
        }),
    )
    source = updates.effective_source({"ref": "main"})
    assert source["ref"] == "main"
    assert source["pinned"] is False


def test_check_update_compares_installed_and_remote_commit(monkeypatch):
    monkeypatch.setattr(
        updates,
        "effective_source",
        lambda config=None: {
            "repository": updates.DEFAULT_REPOSITORY,
            "ref": "main",
            "installed_commit": "a" * 40,
            "installed_requested_revision": "main",
            "pinned": False,
        },
    )
    monkeypatch.setattr(updates, "remote_sha", lambda repository, ref: "b" * 40)
    result = updates.check_update({})
    assert result["status"] == "UPDATE_AVAILABLE"
    assert result["remote_commit"] == "b" * 40


def test_update_argv_is_explicit_forced_uv_reinstall(monkeypatch):
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    argv = updates.update_argv(updates.DEFAULT_REPOSITORY, "main")
    assert argv[:4] == ["/usr/bin/uv", "tool", "install", "--force"]
    assert argv[4].startswith("git+https://github.com/ds1david/speckit-powerpack.git@")
    assert argv[4].endswith("@main")
    assert "--from" not in argv
