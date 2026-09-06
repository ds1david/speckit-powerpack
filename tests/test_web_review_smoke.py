from __future__ import annotations

import json

from speckit_powerpack import cli_web_review
from speckit_powerpack.web_review_smoke import (
    DEFAULT_SMOKE_PROMPT,
    _parse_result,
    _playwright_script,
)


def test_default_smoke_prompt_matches_real_project_context_request():
    assert DEFAULT_SMOKE_PROMPT == (
        "me diga qual é o nome do projeto e sua principal missão, produza uma resposta simplificada "
        "de no máximo 100 palavras. e me responda quanto é 1 +1"
    )


def test_smoke_script_opens_exact_project_and_waits_for_assistant_response():
    script = _playwright_script(
        "https://chatgpt.com/g/g-p-example-project/project",
        DEFAULT_SMOKE_PROMPT,
        120000,
    )
    assert "Project navigation mismatch" in script
    assert "#prompt-textarea" in script
    assert 'data-message-author-role=\\"assistant\\"' in script or 'data-message-author-role="assistant"' in script
    assert "page.keyboard.press('Enter')" in script
    assert "POWERPACK_REVIEW_JSON:" in script
    assert "arithmetic_check" in script
    assert "max_words_check" in script


def test_parse_smoke_result_from_raw_playwright_output():
    payload = {
        "project_url_requested": "https://chatgpt.com/g/g-p-test/project",
        "project_url_loaded": "https://chatgpt.com/g/g-p-test/project",
        "conversation_url": "https://chatgpt.com/g/g-p-test/c/123",
        "response": "O projeto Teste existe para validar o fluxo. 1 + 1 = 2.",
        "response_words": 13,
        "arithmetic_check": True,
        "max_words_check": True,
    }
    result = _parse_result("POWERPACK_REVIEW_JSON:" + json.dumps(payload), "")
    assert result.response.endswith("1 + 1 = 2.")
    assert result.arithmetic_check is True
    assert result.max_words_check is True
    assert result.project_url_requested.endswith("/project")


def test_cli_exposes_review_smoke_test_without_required_parameters():
    parser = cli_web_review.build_parser()
    args = parser.parse_args(["review", "smoke-test"])
    assert args.path == "."
    assert args.timeout == 120
    assert args.prompt is None
    assert args.func is cli_web_review.cmd_review_smoke_test
