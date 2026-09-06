from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from speckit_powerpack import desktop_browser_bridge as desktop
from speckit_powerpack import playwright_eval_compat as compat


def _env() -> desktop.DesktopEnvironment:
    return desktop.DesktopEnvironment("linux", "windows", True, "Windows", "WSLg/Wayland")


def test_chatgpt_login_evidence_uses_direct_raw_eval(monkeypatch):
    calls = []

    def fake_pwcli(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"href":"https://chatgpt.com/","title":"ChatGPT","loginRoute":false,"composer":true,"authenticated":true}\n', "")

    monkeypatch.setattr(desktop, "_host_pwcli", fake_pwcli)
    value = compat.chatgpt_login_evidence("review", env=_env())

    assert value["authenticated"] is True
    assert value["href"] == "https://chatgpt.com/"
    assert calls[0][0:3] == ["-s=review", "--raw", "eval"]
    expression = calls[0][3]
    assert "POWERPACK_JSON" not in expression
    assert "return JSON.stringify" in expression
    assert "JSON.stringify((() =>" not in expression


def test_raw_json_parser_accepts_double_encoded_json_string():
    value = compat._parse_raw_json(
        '"{\\"href\\":\\"https://chatgpt.com/\\",\\"authenticated\\":true}"',
        "",
        expected=dict,
    )
    assert value == {"href": "https://chatgpt.com/", "authenticated": True}


def test_capture_project_uses_direct_eval(monkeypatch):
    calls = []
    browser = desktop.BrowserCandidate("msedge", "Microsoft Edge", "edge.exe", "extension-attach", "msedge")

    monkeypatch.setattr(desktop, "attach_existing_browser", lambda **kwargs: "review")

    def fake_pwcli(args, **kwargs):
        calls.append(args)
        if "eval" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                '{"href":"https://chatgpt.com/g/g-p-123-example/project","title":"Example"}\n',
                "",
            )
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    monkeypatch.setattr(desktop, "_host_pwcli", fake_pwcli)

    value = compat.capture_project_from_url(
        profile="review",
        browser=browser,
        url="https://chatgpt.com/g/g-p-123-example/project",
        env=_env(),
    )

    assert value == {"name": "Example", "url": "https://chatgpt.com/g/g-p-123-example/project"}
    eval_call = next(args for args in calls if "eval" in args)
    assert eval_call[0:3] == ["-s=review", "--raw", "eval"]
    assert eval_call[3] == "() => JSON.stringify({href:location.href,title:document.title})"
