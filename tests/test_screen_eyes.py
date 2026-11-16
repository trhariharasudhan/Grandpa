"""C1: "What's on my screen?" = capture + OCR + grandpa-eyes.

No Ollama here: the vision model is a fake that records what it was sent.
"""

from __future__ import annotations

import io
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from PIL import Image

import grandpa.screen_awareness as sa
from grandpa.screen import eyes
from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.models import (
    OcrResult,
    ScreenCommandResult,
    ScreenDescription,
    ScreenshotResult,
)
from grandpa.screen.service import ScreenVisionService


class FakeEyes:
    def __init__(self, answer: str = "", *, available: bool = True, error=None):
        self.answer = answer
        self.available = available
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, data, filename, mime_type, prompt, *, timeout):
        self.calls.append(
            {"data": data, "mime": mime_type, "prompt": prompt, "timeout": timeout}
        )
        return {
            "available": self.available,
            "model": "grandpa-eyes:latest",
            "analysis": self.answer,
            "error": self.error,
        }


@pytest.fixture(autouse=True)
def _eyes_on(monkeypatch):
    monkeypatch.delenv("GRANDPA_SCREEN_EYES", raising=False)
    monkeypatch.delenv("GRANDPA_SCREEN_EYES_TIMEOUT", raising=False)


@pytest.fixture
def screenshot(tmp_path):
    path = tmp_path / "shot.png"
    Image.new("RGB", (1920, 1080), "white").save(path)
    return path


# --- grandpa.screen.eyes ------------------------------------------------------


def test_look_returns_the_models_summary(screenshot):
    fake = FakeEyes("VS Code is open with a Python file. No errors are visible.")

    result = eyes.look(
        screenshot, ocr_text="def main():", window_title="app.py", analyze=fake
    )

    assert result.available
    assert result.text.startswith("VS Code is open")
    assert result.model == "grandpa-eyes:latest"


def test_look_sends_a_downscaled_jpeg_with_ocr_hint(screenshot):
    fake = FakeEyes("A browser shows the weather in Chennai.")

    result = eyes.look(
        screenshot, ocr_text="Chennai 31°C", window_title="Weather", analyze=fake
    )

    assert result.available
    call = fake.calls[0]
    assert call["mime"] == "image/jpeg"
    image = Image.open(io.BytesIO(call["data"]))
    assert max(image.size) <= eyes.MAX_IMAGE_SIDE
    assert "Chennai 31°C" in call["prompt"]
    assert "Weather" in call["prompt"]
    assert call["timeout"] == eyes.DEFAULT_TIMEOUT_SECONDS


def test_ocr_hint_is_redacted_before_the_model_sees_it(screenshot):
    fake = FakeEyes("A notepad window.")

    eyes.look(screenshot, ocr_text="Password: hunter2hunter2", analyze=fake)

    assert "hunter2hunter2" not in fake.calls[0]["prompt"]


def test_models_answer_is_redacted(screenshot):
    fake = FakeEyes("Notepad shows api_key: sk_live_ABCDEFGH12345678 in a file.")

    result = eyes.look(screenshot, analyze=fake)

    assert result.available
    assert "sk_live_ABCDEFGH12345678" not in result.text


def test_a_credential_screen_seen_only_by_the_model_is_flagged(screenshot):
    fake = FakeEyes("This is a password manager listing saved logins.")

    result = eyes.look(screenshot, analyze=fake)

    assert result.sensitive
    assert not result.available
    assert result.text == ""


def test_ollama_down_is_a_quiet_note_not_an_error(screenshot):
    fake = FakeEyes(available=False, error="Ollama is not available.")

    result = eyes.look(screenshot, analyze=fake)

    assert not result.available
    assert "Ollama is not available" in result.note


def test_a_model_that_raises_is_a_note(screenshot):
    def boom(*_args, **_kwargs):
        raise RuntimeError("socket closed")

    result = eyes.look(screenshot, analyze=boom)

    assert not result.available
    assert "socket closed" in result.note


def test_turned_off_never_calls_the_model(monkeypatch, screenshot):
    monkeypatch.setenv("GRANDPA_SCREEN_EYES", "off")
    fake = FakeEyes("unused")

    result = eyes.look(screenshot, analyze=fake)

    assert not result.available
    assert fake.calls == []


def test_not_an_image_never_calls_the_model(tmp_path):
    bogus = tmp_path / "shot.png"
    bogus.write_bytes(b"not really an image")
    fake = FakeEyes("unused")

    result = eyes.look(bogus, analyze=fake)

    assert not result.available
    assert fake.calls == []


def test_timeout_comes_from_the_environment(monkeypatch, screenshot):
    monkeypatch.setenv("GRANDPA_SCREEN_EYES_TIMEOUT", "30")
    fake = FakeEyes("ok screen")

    eyes.look(screenshot, analyze=fake)

    assert fake.calls[0]["timeout"] == 30.0


def test_long_answers_are_trimmed(screenshot):
    fake = FakeEyes("word " * 400)

    result = eyes.look(screenshot, analyze=fake)

    assert len(result.text) <= eyes.MAX_SUMMARY_CHARS + 3


# --- chat and voice: screen_awareness.describe_screen -------------------------


def _patch_screen(monkeypatch, shot, *, title="Weather - Chrome", text=""):
    monkeypatch.setattr(
        sa,
        "get_active_window_info",
        lambda: sa.ScreenContext(supported=True, window_title=title, app_name=""),
    )
    monkeypatch.setattr(
        sa,
        "capture_screenshot",
        lambda: sa.ScreenContext(supported=True, screenshot_path=str(shot)),
    )
    monkeypatch.setattr(sa, "extract_ocr_result", lambda _p: sa.OcrResult(text=text))
    monkeypatch.setattr(sa, "get_visible_windows", lambda: [])
    monkeypatch.setattr(sa, "_record_visual_context", lambda context: None)


def _patch_model(monkeypatch, fake):
    import grandpa.vision.local_model as local_model

    monkeypatch.setattr(local_model, "analyze_image_with_local_model", fake)


def test_whats_on_my_screen_leads_with_grandpa_eyes(monkeypatch, screenshot):
    _patch_screen(monkeypatch, screenshot, text="Chennai 31 C Sunny")
    fake = FakeEyes("Chrome shows the weather in Chennai: sunny, 31 degrees.")
    _patch_model(monkeypatch, fake)

    context = sa.describe_screen()

    assert context.message.splitlines()[0] == (
        "Grandpa sees: Chrome shows the weather in Chennai: sunny, 31 degrees."
    )
    assert "Visible text" in context.message  # OCR is still there
    assert context.eyes_summary.startswith("Chrome shows")
    assert "Chennai 31 C Sunny" in fake.calls[0]["prompt"]


def test_voice_describe_without_ocr_still_uses_eyes(monkeypatch, screenshot):
    _patch_screen(monkeypatch, screenshot)
    fake = FakeEyes("The desktop is empty apart from the taskbar.")
    _patch_model(monkeypatch, fake)

    context = sa.describe_screen(include_ocr=False)

    assert context.message.startswith("Grandpa sees: The desktop is empty")


def test_without_ollama_the_ocr_answer_stands(monkeypatch, screenshot):
    _patch_screen(monkeypatch, screenshot, text="Inbox (3)")
    _patch_model(
        monkeypatch, FakeEyes(available=False, error="Ollama is not available.")
    )

    context = sa.describe_screen()

    assert "Grandpa sees" not in context.message
    assert "Inbox (3)" in context.message
    assert "Vision model not used: Ollama is not available." in context.message
    assert sa._status(context) == "handled"


def test_the_model_never_sees_a_credential_screen(monkeypatch, screenshot):
    _patch_screen(monkeypatch, screenshot, title="Windows Security")
    fake = FakeEyes("unused")
    _patch_model(monkeypatch, fake)

    context = sa.describe_screen()

    assert context.message == sa.SENSITIVE_SCREEN_MESSAGE
    assert fake.calls == []


def test_a_credential_screen_found_by_the_model_is_refused_and_removed(
    monkeypatch, screenshot
):
    _patch_screen(monkeypatch, screenshot, title="Chrome")
    _patch_model(monkeypatch, FakeEyes("An online banking page with your balance."))

    context = sa.describe_screen()

    assert context.message == sa.SENSITIVE_SCREEN_MESSAGE
    assert not screenshot.exists()
    assert sa._status(context) == "blocked"


def test_include_eyes_false_skips_the_model(monkeypatch, screenshot):
    _patch_screen(monkeypatch, screenshot)
    fake = FakeEyes("unused")
    _patch_model(monkeypatch, fake)

    sa.describe_screen(include_eyes=False)

    assert fake.calls == []


# --- `grandpa screen describe`: ScreenVisionService ---------------------------


def _service(look):
    shot = ScreenshotResult(
        image=Image.new("RGB", (800, 600), "white"),
        width=800,
        height=600,
        monitor_index=1,
        capture_region=(0, 0, 800, 600),
        active_window_title="Editor",
    )
    capture = Mock()
    capture.capture.return_value = shot
    ocr = Mock()
    ocr.extract_text.return_value = OcrResult("hello world", available=True)
    analyzer = Mock()
    analyzer.describe.return_value = ScreenDescription(
        summary="Local description.",
        content_type="editor",
        active_window_title="Editor",
        visible_windows=(),
        dimensions=(800, 600),
    )
    return ScreenVisionService(capture=capture, ocr=ocr, analyzer=analyzer, eyes=look)


def test_service_describe_adds_the_eyes_summary(monkeypatch):
    import grandpa.screen.service as service_module

    monkeypatch.setattr(service_module, "_optional_active_window", lambda: None)
    monkeypatch.setattr(service_module, "list_windows", lambda: [])
    fake = FakeEyes("An editor with a short note.")

    result = _service(
        lambda image, **kw: eyes.look(image, analyze=fake, **kw)
    ).describe()

    assert result.message.startswith("Grandpa sees: An editor with a short note.")
    assert "Local description." in result.message
    assert result.data["eyes_model"] == "grandpa-eyes:latest"
    assert "hello world" in fake.calls[0]["prompt"]


def test_service_describe_refuses_when_eyes_says_sensitive(monkeypatch):
    import grandpa.screen.service as service_module

    monkeypatch.setattr(service_module, "_optional_active_window", lambda: None)
    monkeypatch.setattr(service_module, "list_windows", lambda: [])
    fake = FakeEyes("A Windows Security prompt asks for a PIN.")

    with pytest.raises(SensitiveScreenDetectedError):
        _service(lambda image, **kw: eyes.look(image, analyze=fake, **kw)).describe()


def test_service_without_eyes_is_unchanged(monkeypatch):
    import grandpa.screen.service as service_module

    monkeypatch.setattr(service_module, "_optional_active_window", lambda: None)
    monkeypatch.setattr(service_module, "list_windows", lambda: [])

    assert _service(None).describe().message == "Local description."


def test_cli_describe_wires_eyes_and_no_eyes_turns_it_off():
    from unittest.mock import patch

    from grandpa.cli.screen_cmd import screen

    service = Mock()
    service.describe.return_value = ScreenCommandResult("handled", "Grandpa sees: x")
    with patch("grandpa.cli.screen_cmd._service", return_value=service) as factory:
        result = CliRunner().invoke(screen, ["describe"])
        assert result.exit_code == 0
        assert factory.call_args.kwargs["eyes"] is eyes.look
        CliRunner().invoke(screen, ["describe", "--no-eyes"])
        assert factory.call_args.kwargs["eyes"] is None
