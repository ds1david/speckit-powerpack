from __future__ import annotations

from speckit_powerpack import cli_browser_accounts as cli
from speckit_powerpack import desktop_browser_bridge as desktop


def browser(browser_id: str, automation: str) -> desktop.BrowserCandidate:
    return desktop.BrowserCandidate(
        browser_id=browser_id,
        label=browser_id,
        executable=f"/{browser_id}",
        automation=automation,
        cdp_channel=browser_id if automation == "channel-cdp" else None,
        inspect_url=f"{browser_id}://inspect/#remote-debugging" if automation == "channel-cdp" else None,
        host_scope="linux",
    )


def test_reviewer_browser_selection_excludes_manual_only_firefox(monkeypatch):
    browsers = [
        browser("msedge", "channel-cdp"),
        browser("chrome", "channel-cdp"),
        browser("firefox", "manual-only"),
    ]
    answers = iter(["2"])
    monkeypatch.setattr(cli.base, "_ask", lambda *args, **kwargs: next(answers))

    selected = cli._choose_reviewer_browser(
        browsers,
        default_id="msedge",
        previous_id=None,
    )

    assert selected.browser_id == "chrome"
    assert selected.automatable_existing_context is True


def test_previous_browser_is_only_default_not_silent_selection(monkeypatch):
    browsers = [
        browser("msedge", "channel-cdp"),
        browser("chrome", "channel-cdp"),
    ]
    seen = {}

    def ask(prompt, *, default=None):
        seen["default"] = default
        return "1"  # user explicitly chooses Edge even though previous is Chrome

    monkeypatch.setattr(cli.base, "_ask", ask)
    selected = cli._choose_reviewer_browser(
        browsers,
        default_id="msedge",
        previous_id="chrome",
    )

    assert seen["default"] == "2"
    assert selected.browser_id == "msedge"


def test_no_automatable_browser_fails_closed():
    browsers = [browser("firefox", "manual-only")]
    try:
        cli._choose_reviewer_browser(browsers, default_id="firefox", previous_id=None)
    except cli.core.PowerPackError as exc:
        text = str(exc).casefold()
        assert "nenhum navegador compatível" in text
        assert "fallback automático" in text
    else:
        raise AssertionError("manual-only browser must not satisfy automated Web review")


def test_windows_candidate_augmentation_can_find_browser_outside_path(monkeypatch):
    env = desktop.DesktopEnvironment(
        runtime_os="linux",
        host_scope="windows",
        is_wsl=True,
        desktop="Windows",
        display_server="WSLg/Wayland",
    )
    monkeypatch.setattr(
        cli,
        "_windows_app_path",
        lambda exe: "C:/Program Files/Microsoft/Edge/Application/msedge.exe" if exe == "msedge.exe" else None,
    )

    values = cli._augment_windows_candidates(env, [])

    assert [item.browser_id for item in values] == ["msedge"]
    assert values[0].automation == "channel-cdp"
