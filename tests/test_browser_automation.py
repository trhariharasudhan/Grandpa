from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.browser import BrowserExecutor, BrowserParser, handle_browser_command
from grandpa.browser.urls import normalize_url, search_url
from grandpa.cli.chat_cmd import _handle_browser_slash_command, chat
from grandpa.core.config import GrandpaConfig
from grandpa.voice.operator import (
    execute_voice_operator_intent,
    parse_voice_operator_command,
)


def test_parser_open_known_website() -> None:
    action = BrowserParser().parse("Open YouTube")

    assert action is not None
    assert action.action == "open_url"
    assert action.target == "YouTube"
    assert action.url == "https://www.youtube.com"


def test_parser_open_explicit_url() -> None:
    action = BrowserParser().parse("open https://example.com")

    assert action is not None
    assert action.action == "open_url"
    assert action.url == "https://example.com"


@pytest.mark.parametrize(
    ("text", "provider", "query"),
    [
        ("Search Google for FastAPI tutorials", "google", "FastAPI tutorials"),
        ("Search YouTube for Python automation", "youtube", "Python automation"),
        ("Search GitHub for FastAPI starter", "github", "FastAPI starter"),
        (
            "Search Stack Overflow for Python import error",
            "stack overflow",
            "Python import error",
        ),
        ("Google Python decorators", "google", "Python decorators"),
    ],
)
def test_parser_searches(text: str, provider: str, query: str) -> None:
    action = BrowserParser().parse(text)

    assert action is not None
    assert action.action == "search"
    assert action.provider == provider
    assert action.query == query


@pytest.mark.parametrize(
    ("text", "action_name"),
    [
        ("open a new tab", "new_tab"),
        ("close current tab", "close_tab"),
        ("refresh page", "refresh"),
        ("go back", "back"),
        ("go forward", "forward"),
        ("reopen closed tab", "reopen_closed_tab"),
        ("focus address bar", "focus_address_bar"),
    ],
)
def test_parser_navigation(text: str, action_name: str) -> None:
    action = BrowserParser().parse(text)

    assert action is not None
    assert action.action == action_name


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("open browser history", "history"),
        ("open browser downloads", "downloads"),
        ("open browser bookmarks", "bookmarks"),
        ("open browser settings", "settings"),
    ],
)
def test_parser_browser_pages(text: str, target: str) -> None:
    action = BrowserParser().parse(text)

    assert action is not None
    assert action.action == "open_page"
    assert action.target == target


def test_parser_unrelated_chat_does_not_match() -> None:
    assert BrowserParser().parse("tell me a story about browsers") is None
    assert BrowserParser().parse("search invoice.pdf") is None


def test_url_normalization_and_blocked_schemes() -> None:
    assert normalize_url("example.com") == "https://example.com"

    for value in ("javascript:alert(1)", "file:///C:/secret.txt", "data:text/plain,hi"):
        with pytest.raises(ValueError):
            normalize_url(value)


def test_search_url_encodes_query() -> None:
    label, url = search_url("google", "FastAPI tutorials & examples")

    assert label == "Google"
    assert url == "https://www.google.com/search?q=FastAPI+tutorials+%26+examples"


def test_executor_opens_website_with_mocked_opener() -> None:
    opened: list[str] = []
    action = BrowserParser().parse("open github")
    assert action is not None

    result = BrowserExecutor(
        opener=lambda url: opened.append(url) is None or True, confirmed=True
    ).execute(action)

    assert result.status == "handled"
    assert opened == ["https://github.com"]
    assert result.message == "GitHub opened."


def test_executor_generates_search_url_with_mocked_opener() -> None:
    opened: list[str] = []
    action = BrowserParser().parse("search youtube for Python automation")
    assert action is not None

    result = BrowserExecutor(
        opener=lambda url: opened.append(url) is None or True, confirmed=True
    ).execute(action)

    assert result.status == "handled"
    assert opened == ["https://www.youtube.com/results?search_query=Python+automation"]
    assert result.message == "Searching YouTube for Python automation."


def test_executor_browser_hotkeys_are_mockable() -> None:
    keys_seen: list[tuple[str, ...]] = []
    action = BrowserParser().parse("open a new tab")
    assert action is not None

    result = BrowserExecutor(
        hotkey_runner=lambda keys: keys_seen.append(keys) is None or True
    ).execute(action)

    assert result.status == "handled"
    assert keys_seen == [("ctrl", "t")]


def test_unsafe_url_returns_friendly_blocked_error() -> None:
    result = handle_browser_command(
        "open javascript:alert(1)", opener=lambda _url: True, confirmed=True
    )

    assert result.status == "blocked"
    assert "Blocked unsafe URL scheme" in result.message


def test_browser_slash_routes_to_automation(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        "webbrowser.open", lambda url, new=0: opened.append(url) is None or True
    )

    message = _handle_browser_slash_command(
        "/browser search youtube Python automation",
        confirm=lambda _prompt, _tier: True,
    )

    assert message == "Searching YouTube for Python automation."
    assert opened == ["https://www.youtube.com/results?search_query=Python+automation"]


def test_voice_operator_parses_browser_command() -> None:
    intent = parse_voice_operator_command("open YouTube")

    assert intent.kind == "browser_automation"
    assert intent.action == "open_url"
    assert intent.target == "YouTube"


def test_voice_operator_executes_browser_command(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.browser.handle_browser_command",
        lambda command, **_kwargs: SimpleNamespace(
            status="handled",
            message=f"handled {command}",
            should_fallback=False,
        ),
    )
    intent = parse_voice_operator_command("search Google for FastAPI tutorials")

    result = execute_voice_operator_intent(intent)

    assert result.status == "handled"
    assert result.message == "handled search google for fastapi tutorials"


def test_chat_browser_command_does_not_call_llm(monkeypatch) -> None:
    engine = SimpleNamespace(engine_id="mock")
    engine.generate = lambda *_args, **_kwargs: {"content": "should not run"}
    config = GrandpaConfig()
    config.intelligence.default_model = "test-model"

    monkeypatch.setattr("grandpa.cli.chat_cmd.load_config", lambda: config)
    monkeypatch.setattr(
        "grandpa.engine.get_engine", lambda *_args, **_kwargs: ("mock", engine)
    )
    monkeypatch.setattr("grandpa.intelligence.register_builtin_models", lambda: None)
    monkeypatch.setattr(
        "grandpa.browser.handle_browser_command",
        lambda _text, **_kwargs: SimpleNamespace(
            status="handled",
            message="YouTube opened.",
            url="https://www.youtube.com",
            action=SimpleNamespace(target="YouTube"),
            should_fallback=False,
        ),
    )

    result = CliRunner().invoke(
        chat, ["--model", "test-model"], input="open youtube\n/quit\n"
    )

    assert result.exit_code == 0
    assert "YouTube opened." in result.output


def test_app_file_browser_ambiguity() -> None:
    assert BrowserParser().parse("open chrome") is None
    assert BrowserParser().parse("open downloads") is None
    assert BrowserParser().parse("open browser downloads").action == "open_page"  # type: ignore[union-attr]
    assert BrowserParser().parse("search invoice.pdf") is None
    assert BrowserParser().parse("search google for invoice templates") is not None


# --- browser shortcuts: they run, and only into a browser ----------------------


@pytest.fixture
def recorded_keys(monkeypatch):
    """Record the keys the automation service is asked to press; press nothing."""
    import grandpa.desktop.control.automation as automation

    pressed: list[str] = []

    class _Ok:
        ok = True
        message = "Pressed hotkey."

    monkeypatch.setattr(
        automation.AutomationControlService,
        "execute",
        lambda self, request, action, platform: pressed.append(request.target) or _Ok(),
    )
    return pressed


def test_a_shortcut_is_not_sent_to_a_window_that_is_not_a_browser(
    monkeypatch, recorded_keys
) -> None:
    """Ctrl+W sent to a text editor closes the document, not a tab."""
    from grandpa.browser.executor import BrowserExecutor
    from grandpa.browser.models import BrowserAction

    monkeypatch.setattr(
        "grandpa.browser_control._find_visible_browser_window", lambda: None
    )

    result = BrowserExecutor().execute(BrowserAction("close_tab"))

    assert result.status == "blocked"
    assert result.error == "browser_not_in_front"
    assert recorded_keys == []


def test_a_shortcut_runs_when_a_browser_is_in_front(monkeypatch, recorded_keys) -> None:
    """They used to be staged as a generic keyboard_hotkey approval and never ran."""
    from grandpa.browser.executor import BrowserExecutor
    from grandpa.browser.models import BrowserAction

    monkeypatch.setattr(
        "grandpa.browser_control._find_visible_browser_window",
        lambda: (1, "Chrome", "Some Page"),
    )
    staged: list[str] = []
    monkeypatch.setattr(
        "grandpa.pc_control._create_pending",
        lambda request: staged.append(request.action_type) or "never",
    )

    for name, keys in (
        ("back", "alt+left"),
        ("forward", "alt+right"),
        ("new_tab", "ctrl+t"),
    ):
        result = BrowserExecutor().execute(BrowserAction(name))
        assert result.status == "handled", result

    assert recorded_keys == ["alt+left", "alt+right", "ctrl+t"]
    assert staged == []
