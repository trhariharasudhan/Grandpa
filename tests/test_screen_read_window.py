"""C2: "Read the active window" -- the window's own text, OCR as a fallback.

No Windows here: the UI Automation walk is replaced by a fake node reader, and
the active window by a fixed WindowInfo. What is tested is everything around
the walk: password fields skipped, credential screens refused, redaction, the
OCR fallback, the phrases, the CLI and the catalogue action.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from PIL import Image

from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.intents import handle_screen_command
from grandpa.screen.models import OcrResult, ScreenshotResult, WindowInfo
from grandpa.screen.service import ScreenVisionService
from grandpa.screen.window_text import UiNode, collect_text, read_uia_nodes

ARTICLE = [
    UiNode("other", "Minimize"),
    UiNode("other", "Close"),
    UiNode("document", "Weather", text="Chennai weather\nSunny, 31 C\nHumidity 70%"),
    UiNode("other", "Chennai weather"),  # the same line again, as UIA does
    UiNode("other", "Updated 10:00"),
]


def _window(title: str = "Weather - Google Chrome", process: str = "chrome.exe"):
    return WindowInfo(title=title, process_name=process, handle=4242)


def _service(nodes=(), *, ocr_text: str = "", ocr_available: bool = True, title=None):
    shot = ScreenshotResult(
        image=Image.new("RGB", (400, 300), "white"),
        width=400,
        height=300,
        monitor_index=1,
        capture_region=(0, 0, 400, 300),
        active_window_title="x",
    )
    capture = Mock()
    capture.capture.return_value = shot
    ocr = Mock()
    ocr.extract_text.return_value = OcrResult(
        ocr_text,
        available=ocr_available,
        message="" if ocr_available else "Tesseract not found.",
    )
    reader = Mock(return_value=list(nodes))
    window = _window() if title is None else _window(title)
    service = ScreenVisionService(
        capture=capture,
        ocr=ocr,
        analyzer=Mock(),
        window_reader=reader,
        active_window_provider=lambda: window,
    )
    return service, capture, ocr, reader


# --- collect_text -------------------------------------------------------------


def test_collect_text_reads_documents_and_drops_furniture_and_repeats():
    text, truncated = collect_text(ARTICLE)

    assert text.splitlines() == [
        "Chennai weather",
        "Sunny, 31 C",
        "Humidity 70%",
        "Updated 10:00",
    ]
    assert not truncated


def test_collect_text_skips_password_fields_whole():
    nodes = [
        UiNode("other", "Sign up for the newsletter"),
        UiNode("edit", "Password", text="hunter2", is_password=True),
        UiNode("edit", "Email", text="me@example.com"),
    ]

    text, _ = collect_text(nodes)

    assert "hunter2" not in text
    assert "Password" not in text
    assert "me@example.com" in text


def test_collect_text_stops_at_max_chars():
    nodes = [UiNode("other", f"Line number {index}") for index in range(100)]

    text, truncated = collect_text(nodes, max_chars=60)

    assert truncated
    assert len(text) <= 60
    assert text.startswith("Line number 0")


def test_the_uia_walk_is_off_outside_windows_or_under_pytest():
    # Never touches a real desktop from the suite.
    assert read_uia_nodes(4242) == []


# --- ScreenVisionService.read_window ------------------------------------------


def test_read_window_uses_the_windows_own_text_not_ocr():
    service, capture, ocr, reader = _service(ARTICLE)

    result = service.read_window()

    assert result.status == "handled"
    assert result.action == "read_window"
    assert result.message.startswith(
        "Weather - Google Chrome (chrome.exe), read from its own text:"
    )
    assert "Sunny, 31 C" in result.message
    assert result.spoken_text.startswith("Weather - Google Chrome says:")
    assert result.data["source"] == "accessibility"
    reader.assert_called_once_with(4242)
    capture.capture.assert_not_called()
    ocr.extract_text.assert_not_called()


def test_read_window_falls_back_to_ocr_of_that_window_only():
    service, capture, _ocr, _reader = _service([], ocr_text="Game paused\nPress Start")

    result = service.read_window()

    assert result.status == "handled"
    assert result.data["source"] == "ocr"
    assert "read from OCR" in result.message
    assert "Press Start" in result.message
    capture.capture.assert_called_once_with(active_window=True)


def test_read_window_without_text_or_ocr_says_so():
    service, *_ = _service([], ocr_available=False)

    result = service.read_window()

    assert result.status == "unsupported"
    assert "Tesseract not found" in result.message


def test_read_window_refuses_a_credential_title_before_reading():
    service, capture, _ocr, reader = _service(
        ARTICLE, title="Windows Security - Enter password"
    )

    with pytest.raises(SensitiveScreenDetectedError):
        service.read_window()

    reader.assert_not_called()
    capture.capture.assert_not_called()


def test_read_window_refuses_when_the_text_shows_a_credential_screen():
    nodes = [UiNode("other", "Online banking"), UiNode("other", "Welcome back")]
    service, *_ = _service(nodes)

    with pytest.raises(SensitiveScreenDetectedError):
        service.read_window()


def test_read_window_redacts_secrets_in_the_text():
    nodes = [UiNode("document", "", text="Config\napi_key = sk-abcdefghijklmnop1234")]
    service, *_ = _service(nodes)

    result = service.read_window()

    assert "sk-abcdefghijklmnop1234" not in result.message
    assert "[REDACTED_TOKEN]" in result.message
    assert result.data["redactions"] >= 1


def test_read_window_marks_a_long_window_as_cut_short():
    nodes = [UiNode("other", f"Paragraph {index} " + "x" * 40) for index in range(50)]
    service, *_ = _service(nodes)

    result = service.read_window(max_chars=300)

    assert result.data["truncated"] is True
    assert result.message.endswith("(Only the first part is shown.)")


# --- phrases ------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "Read the active window",
        "read this window",
        "Read this to me.",
        "what does this window say?",
        "read the current page",
    ],
)
def test_phrases_read_the_window(phrase):
    service, *_ = _service(ARTICLE)

    result = handle_screen_command(phrase, service=service)

    assert result.action == "read_window"
    assert "Sunny, 31 C" in result.message


def test_read_my_screen_still_reads_the_whole_screen():
    service = Mock()
    handle_screen_command("read my screen", service=service)
    service.read.assert_called_once_with()
    service.read_window.assert_not_called()


def test_a_refusal_is_a_message_not_a_crash():
    service, *_ = _service(ARTICLE, title="Password Manager")

    result = handle_screen_command("read this window", service=service)

    assert result.status == "error"
    assert "sensitive" in result.message


def test_the_local_parser_and_screen_intents_agree_on_the_phrases():
    from grandpa.local.parsers import READ_WINDOW_PHRASES
    from grandpa.screen.intents import _match_action

    for phrase in READ_WINDOW_PHRASES:
        assert _match_action(phrase) == "read_window", phrase


def test_the_local_parser_routes_to_the_catalogue_action():
    from grandpa.local.parsers import READ_WINDOW_PHRASES, _parse_screen_action
    from grandpa.natural_actions import MIGRATED

    for phrase in READ_WINDOW_PHRASES:
        parsed = _parse_screen_action(phrase)
        assert (parsed.kind, parsed.target) == ("screen", "read_window"), phrase
    assert MIGRATED[("screen", "read_window")] == ("read_window", {})


# --- the catalogue action and the CLI -----------------------------------------


def test_read_window_is_a_low_risk_catalogued_action():
    from grandpa.action_layer.catalogue import DOMAINS, get

    spec = get("read_window")

    assert spec.risk.name == "LOW"
    assert spec.implementation == "grandpa.screen_awareness.read_window_answer"
    assert "read_window" in DOMAINS["windows"]


@pytest.mark.real_actions(
    reason="ScreenVisionService.read_window is replaced; nothing reads the desktop"
)
def test_read_window_answer_blocks_sensitive_and_reports_unsupported(monkeypatch):
    import grandpa.screen_awareness as sa
    from grandpa.screen.errors import ActiveWindowUnavailableError

    def sensitive(self, **_kwargs):
        raise SensitiveScreenDetectedError("sensitive")

    monkeypatch.setattr(ScreenVisionService, "read_window", sensitive)
    assert sa.read_window_answer().status == "blocked"

    def missing(self, **_kwargs):
        raise ActiveWindowUnavailableError("Windows only.")

    monkeypatch.setattr(ScreenVisionService, "read_window", missing)
    answer = sa.read_window_answer()
    assert (answer.status, answer.message) == ("unsupported", "Windows only.")


def test_cli_screen_window(monkeypatch):
    from grandpa.cli import screen_cmd

    service, *_ = _service(ARTICLE)
    monkeypatch.setattr(screen_cmd, "_service", lambda **_kwargs: service)

    result = CliRunner().invoke(screen_cmd.screen, ["window", "--max-chars", "500"])

    assert result.exit_code == 0, result.output
    assert "Sunny, 31 C" in result.output
