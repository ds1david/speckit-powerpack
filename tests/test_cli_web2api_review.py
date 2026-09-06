from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import chatgpt_web2api_backend as backend
from speckit_powerpack import cli_user_state
from speckit_powerpack import cli_web2api_review as review


def _parser_action(parser: argparse.ArgumentParser, name: str):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError(name)


def test_cli_exposes_service_run_and_web2api_auth_commands():
    parser = cli_user_state.build_parser()
    review_parser = _parser_action(parser, "review")
    service = _parser_action(review_parser, "service")
    assert service is not None
    run = _parser_action(review_parser, "run")
    assert run is not None
    auth = _parser_action(review_parser, "auth")
    configure = _parser_action(auth, "configure")
    assert configure.get_default("func") is review.cmd_auth_configure
    validate = _parser_action(auth, "validate")
    assert validate.get_default("func") is review.cmd_auth_validate
    project = _parser_action(review_parser, "project")
    select = _parser_action(project, "select")
    assert select.get_default("func") is review.cmd_project_select


def test_smoke_test_calls_bound_project_id(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        review,
        "_run_prompt",
        lambda project, prompt, timeout, model=None: (
            {
                "project_alias": "atsel",
                "project_name": "ATSEL",
                "project_id": "g-p-abc123",
                "project_url": "https://chatgpt.com/g/g-p-abc123/project",
            },
            "ds1david",
            {"account_label": "ds1david-plus", "endpoint": "http://127.0.0.1:8080"},
            backend.ChatResult("O projeto é ATSEL. Sua missão é evoluir estratégias. 1 + 1 = 2.", "conv-1", "auto"),
        ),
    )
    args = argparse.Namespace(path=str(tmp_path), prompt=None, timeout=120, json=False)
    review.cmd_review_smoke_test(args)
    out = capsys.readouterr().out
    assert "SMOKE TEST PASSED" in out
    assert "g-p-abc123" in out
    assert "1 + 1 = 2" in out


def test_review_run_uses_prompt_file_and_can_write_raw_response(monkeypatch, tmp_path, capsys):
    prompt_file = tmp_path / "prompt.txt"
    output_file = tmp_path / "response.json"
    prompt_file.write_text("review snapshot", encoding="utf-8")
    seen = {}

    def fake_run(project, prompt, timeout, model=None):
        seen["prompt"] = prompt
        return (
            {"project_alias": "atsel", "project_name": "ATSEL", "project_id": "g-p-1", "project_url": "https://chatgpt.com/g/g-p-1/project"},
            "reviewer",
            {"account_label": "plus", "endpoint": "http://127.0.0.1:8080"},
            backend.ChatResult('{"schema_version":"2.0","verdict":"APPROVED"}', "conv-2", "auto"),
        )

    monkeypatch.setattr(review, "_run_prompt", fake_run)
    args = argparse.Namespace(
        path=str(tmp_path),
        prompt=None,
        prompt_file=str(prompt_file),
        model=None,
        timeout=180,
        output=str(output_file),
        json=False,
    )
    review.cmd_review_run(args)
    assert seen["prompt"] == "review snapshot"
    assert '"verdict":"APPROVED"' in output_file.read_text(encoding="utf-8")
    assert '"schema_version":"2.0"' in capsys.readouterr().out
