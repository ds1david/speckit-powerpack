from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import cli
from speckit_powerpack import web_review_runner as runner


def test_extract_json_accepts_fenced_review():
    payload = runner._extract_json('```json\n{"schema_version":"2.0","verdict":"APPROVED"}\n```')
    assert payload["schema_version"] == "2.0"
    assert payload["verdict"] == "APPROVED"


def test_extract_json_accepts_small_wrapper_but_not_non_json():
    payload = runner._extract_json('Review complete:\n{"schema_version":"2.0","verdict":"CHANGES_REQUIRED"}\nDone')
    assert payload["verdict"] == "CHANGES_REQUIRED"
    with pytest.raises(cli.PowerPackError):
        runner._extract_json("No structured review was returned")


def test_resolve_config_requires_full_web_readiness(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    review_dir = project / ".specify" / "powerpack"
    review_dir.mkdir(parents=True)
    (review_dir / "review.json").write_text(json.dumps({
        "chatgpt_web": {
            "required": True,
            "enabled": True,
            "project_url": "https://chatgpt.com/g/g-p-demo/project",
            "profile": "reviewer",
            "account_label": "reviewer-plus",
            "headless": False,
            "prompt_path": ".specify/powerpack/runtime/web-review-prompt.txt"
        }
    }), encoding="utf-8")
    monkeypatch.setattr(runner.binding, "review_readiness", lambda _: {
        "web-review-required": True,
        "playwright-package": True,
        "playwright-browser": True,
        "chatgpt-account-authenticated": True,
        "chatgpt-project-bound": False,
    })
    args = argparse.Namespace(
        path=str(project), prompt=None, output=None, raw_output=None,
        timeout=600, headless=False, headed=False,
    )
    with pytest.raises(cli.PowerPackError, match="not ready"):
        runner.resolve_config(args)


def test_resolve_config_uses_bound_project_profile_and_headed_override(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    review_dir = project / ".specify" / "powerpack"
    review_dir.mkdir(parents=True)
    (review_dir / "review.json").write_text(json.dumps({
        "chatgpt_web": {
            "required": True,
            "enabled": True,
            "project_url": "https://chatgpt.com/g/g-p-demo/project",
            "profile": "reviewer",
            "account_label": "reviewer-plus",
            "headless": True,
            "prompt_path": ".specify/powerpack/runtime/custom-prompt.txt"
        }
    }), encoding="utf-8")
    monkeypatch.setattr(runner.binding, "review_readiness", lambda _: {
        "web-review-required": True,
        "playwright-package": True,
        "playwright-browser": True,
        "chatgpt-account-authenticated": True,
        "chatgpt-project-bound": True,
    })
    args = argparse.Namespace(
        path=str(project), prompt=None, output=None, raw_output=None,
        timeout=600, headless=False, headed=True,
    )
    resolved = runner.resolve_config(args)
    assert resolved.project_url == "https://chatgpt.com/g/g-p-demo/project"
    assert resolved.profile == "reviewer"
    assert resolved.account_label == "reviewer-plus"
    assert resolved.headless is False
    assert resolved.prompt_path == project / ".specify/powerpack/runtime/custom-prompt.txt"
    assert resolved.output_path == project / ".specify/powerpack/runtime/web-review.json"


def test_prepare_prompt_fails_closed_when_manifest_protocol_blocks(tmp_path: Path, monkeypatch):
    config = runner.WebReviewConfig(
        project=tmp_path,
        project_url="https://chatgpt.com/g/g-p-demo/project",
        profile="reviewer",
        account_label="reviewer-plus",
        prompt_path=tmp_path / "prompt.txt",
        output_path=tmp_path / "review.json",
        raw_path=tmp_path / "raw.txt",
        headless=False,
        timeout_seconds=600,
    )
    monkeypatch.setattr(runner, "_run_protocol", lambda *_args: SimpleNamespace(
        returncode=4,
        stdout='{"status":"BLOCKED","reason":"stale-review-context-manifest"}',
        stderr="",
    ))
    with pytest.raises(cli.PowerPackError, match="fresh manifest"):
        runner.prepare_prompt(config)
