from __future__ import annotations

import json

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


def test_exact_commit_install_falls_back_to_default_ref(monkeypatch):
    monkeypatch.setattr(
        updates.metadata,
        "distribution",
        lambda name: FakeDistribution({
            "url": updates.DEFAULT_REPOSITORY,
            "vcs_info": {
                "vcs": "git",
                "commit_id": "a" * 40,
                "requested_revision": "b" * 40,
            },
        }),
    )
    assert updates.effective_source({})["ref"] == "main"


def test_check_update_compares_installed_and_remote_commit(monkeypatch):
    monkeypatch.setattr(
        updates,
        "effective_source",
        lambda config=None: {
            "repository": updates.DEFAULT_REPOSITORY,
            "ref": "main",
            "installed_commit": "a" * 40,
            "installed_requested_revision": "main",
        },
    )
    monkeypatch.setattr(updates, "remote_sha", lambda repository, ref: "b" * 40)
    result = updates.check_update({})
    assert result["status"] == "UPDATE_AVAILABLE"
    assert result["remote_commit"] == "b" * 40


def test_update_argv_is_explicit_forced_uv_reinstall(monkeypatch):
    monkeypatch.setattr(updates.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    argv = updates.update_argv(updates.DEFAULT_REPOSITORY, "main")
    assert argv[:5] == ["/usr/bin/uv", "tool", "install", "--force", "speckit-powerpack"]
    assert argv[-1].endswith("@main")
