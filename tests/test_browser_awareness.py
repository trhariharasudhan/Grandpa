from __future__ import annotations

from types import SimpleNamespace

from click.testing import CliRunner

from grandpa.browser_awareness import (
    BrowserAwareness,
    BrowserAwarenessParser,
    BrowserPageSnapshot,
)
from grandpa.browser_awareness.safety import sanitize_visible_text
from grandpa.cli.chat_cmd import _handle_browser_slash_command, chat
from grandpa.core.config import GrandpaConfig
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.operator import (
    execute_voice_operator_intent,
    parse_voice_operator_command,
)


def _snapshot() -> BrowserPageSnapshot:
    return BrowserPageSnapshot(
        supported=True,
        title="FastAPI Documentation",
        url="https://fastapi.tiangolo.com/",
        visible_text=(
            "FastAPI is a modern Python web framework. "
            "Installation uses pip. The installation guide covers deployment."
        ),
        selected_text="Selected visible text",
        links=(
            {"text": "Tutorial", "href": "https://fastapi.tiangolo.com/tutorial/"},
            {"text": "Reference", "href": "https://fastapi.tiangolo.com/reference/"},
        ),
        tabs=("FastAPI Documentation", "Grandpa Docs"),
    )


def test_parse_current_page_query() -> None:
    action = BrowserAwarenessParser().parse("What page am I on?")

    assert action is not None
    assert action.action == "current"


def test_parse_summarize_page() -> None:
    action = BrowserAwarenessParser().parse("Summarize this page")

    assert action is not None
    assert action.action == "summarize"


def test_parse_url_and_title_requests() -> None:
    assert BrowserAwarenessParser().parse("show the current URL").action == "url"  # type: ignore[union-attr]
    assert BrowserAwarenessParser().parse("what is the title of this page").action == "title"  # type: ignore[union-attr]


def test_parse_find_text() -> None:
    action = BrowserAwarenessParser().parse('Find text "installation" on this page')

    assert action is not None
    assert action.action == "find_text"
    assert action.query == "installation"


def test_unrelated_chat_does_not_match() -> None:
    assert BrowserAwarenessParser().parse("tell me about browsers") is None
    assert BrowserAwarenessParser().parse("open youtube") is None


def test_safe_capture_mocked_current_page() -> None:
    result = BrowserAwareness(capture=_snapshot).handle("what page am I on")

    assert result.status == "handled"
    assert "Title: FastAPI Documentation" in result.message
    assert "URL: https://fastapi.tiangolo.com/" in result.message


def test_summarize_visible_content() -> None:
    result = BrowserAwareness(capture=_snapshot).handle("summarize this page")

    assert result.status == "handled"
    assert "Summary:" in result.message
    assert "FastAPI is a modern Python web framework" in result.message


def test_find_visible_text_count() -> None:
    result = BrowserAwareness(capture=_snapshot).handle('find text "installation" on this page')

    assert result.status == "handled"
    assert 'Found "installation" 2 times' in result.message


def test_list_visible_links() -> None:
    result = BrowserAwareness(capture=_snapshot).handle("list the links on this page")

    assert result.status == "handled"
    assert "Visible links:" in result.message
    assert "1. Tutorial" in result.message


def test_read_selected_text() -> None:
    result = BrowserAwareness(capture=_snapshot).handle("read selected text")

    assert result.status == "handled"
    assert "Selected visible text" in result.message


def test_tabs_when_safely_available() -> None:
    result = BrowserAwareness(capture=_snapshot).handle("what tabs are open")

    assert result.status == "handled"
    assert "FastAPI Documentation" in result.message


def test_text_truncation_and_secret_redaction() -> None:
    text = "api_key=abcd1234abcd1234 token=secretsecret123456 4111 1111 1111 1111 " + ("x" * 9000)

    cleaned = sanitize_visible_text(text, limit=120)

    assert "abcd1234" not in cleaned
    assert "4111" not in cleaned
    assert "[redacted]" in cleaned
    assert cleaned.endswith("...")
    assert len(cleaned) <= 123


def test_unsupported_browser_returns_friendly_result() -> None:
    result = BrowserAwareness(capture=lambda: BrowserPageSnapshot(False, message="No visible supported browser page.")).handle(
        "summarize this page"
    )

    assert result.status == "unsupported"
    assert "No visible supported browser page" in result.message


def test_browser_slash_awareness_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.browser_awareness.handle_browser_awareness_command",
        lambda command: SimpleNamespace(message=f"aware {command}", should_fallback=False),
    )

    assert _handle_browser_slash_command("/browser current") == "aware what page am i on"
    assert _handle_browser_slash_command("/browser find installation") == "aware find text installation on this page"


def test_chat_awareness_does_not_call_llm(monkeypatch) -> None:
    engine = SimpleNamespace(engine_id="mock")
    calls = {"generate": 0}

    def generate(*_args, **_kwargs):
        calls["generate"] += 1
        return {"content": "should not run"}

    engine.generate = generate
    config = GrandpaConfig()
    config.intelligence.default_model = "test-model"

    monkeypatch.setattr("grandpa.cli.chat_cmd.load_config", lambda: config)
    monkeypatch.setattr("grandpa.engine.get_engine", lambda *_args, **_kwargs: ("mock", engine))
    monkeypatch.setattr("grandpa.intelligence.register_builtin_models", lambda: None)
    monkeypatch.setattr(
        "grandpa.browser_awareness.handle_browser_awareness_command",
        lambda _text: SimpleNamespace(
            status="handled",
            message="Current page:\nTitle: FastAPI Documentation",
            snapshot=SimpleNamespace(url="https://fastapi.tiangolo.com/"),
            should_fallback=False,
        ),
    )

    result = CliRunner().invoke(chat, ["--model", "test-model"], input="what page am I on?\n/quit\n")

    assert result.exit_code == 0
    assert "FastAPI Documentation" in result.output
    assert calls["generate"] == 0


def test_voice_assistant_routes_awareness(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.browser_awareness.handle_browser_awareness_command",
        lambda _text: SimpleNamespace(
            status="handled",
            message="Summary:\nA visible page summary.",
            should_fallback=False,
        ),
    )

    result = VoiceCommandProcessor().handle_user_input("summarize this page")

    assert result.kind == "browser_awareness"
    assert "visible page summary" in result.text


def test_voice_operator_routes_awareness(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.browser_awareness.handle_browser_awareness_command",
        lambda command: SimpleNamespace(
            status="handled",
            message=f"aware {command}",
            should_fallback=False,
        ),
    )
    intent = parse_voice_operator_command("what page am I on")

    assert intent.kind == "browser_awareness"
    result = execute_voice_operator_intent(intent)
    assert result.status == "handled"
    assert result.message == "aware what page am i on"


def test_no_click_or_form_actions_introduced() -> None:
    assert BrowserAwarenessParser().parse("click the login button") is None
    assert BrowserAwarenessParser().parse("fill the password field") is None
