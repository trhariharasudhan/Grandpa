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
        ("Search Stack Overflow for Python import error", "stack overflow", "Python import error"),
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

    result = BrowserExecutor(opener=lambda url: opened.append(url) is None or True).execute(action)

    assert result.status == "handled"
    assert opened == ["https://github.com"]
    assert result.message == "GitHub opened."


def test_executor_generates_search_url_with_mocked_opener() -> None:
    opened: list[str] = []
    action = BrowserParser().parse("search youtube for Python automation")
    assert action is not None

    result = BrowserExecutor(opener=lambda url: opened.append(url) is None or True).execute(action)

    assert result.status == "handled"
    assert opened == ["https://www.youtube.com/results?search_query=Python+automation"]
    assert result.message == "Searching YouTube for Python automation."


def test_executor_browser_hotkeys_are_mockable() -> None:
    keys_seen: list[tuple[str, ...]] = []
    action = BrowserParser().parse("open a new tab")
    assert action is not None

    result = BrowserExecutor(hotkey_runner=lambda keys: keys_seen.append(keys) is None or True).execute(action)

    assert result.status == "handled"
    assert keys_seen == [("ctrl", "t")]


def test_unsafe_url_returns_friendly_blocked_error() -> None:
    result = handle_browser_command("open javascript:alert(1)", opener=lambda _url: True)

    assert result.status == "blocked"
    assert "Blocked unsafe URL scheme" in result.message


def test_browser_slash_routes_to_automation(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: opened.append(url) is None or True)

    message = _handle_browser_slash_command("/browser search youtube Python automation")

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
        lambda command: SimpleNamespace(
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
    monkeypatch.setattr("grandpa.engine.get_engine", lambda *_args, **_kwargs: ("mock", engine))
    monkeypatch.setattr("grandpa.intelligence.register_builtin_models", lambda: None)
    monkeypatch.setattr(
        "grandpa.browser.handle_browser_command",
        lambda _text: SimpleNamespace(
            status="handled",
            message="YouTube opened.",
            url="https://www.youtube.com",
            action=SimpleNamespace(target="YouTube"),
            should_fallback=False,
        ),
    )

    result = CliRunner().invoke(chat, ["--model", "test-model"], input="open youtube\n/quit\n")

    assert result.exit_code == 0
    assert "YouTube opened." in result.output


def test_app_file_browser_ambiguity() -> None:
    assert BrowserParser().parse("open chrome") is None
    assert BrowserParser().parse("open downloads") is None
    assert BrowserParser().parse("open browser downloads").action == "open_page"  # type: ignore[union-attr]
    assert BrowserParser().parse("search invoice.pdf") is None
    assert BrowserParser().parse("search google for invoice templates") is not None
