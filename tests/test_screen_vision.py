"""Hermetic tests for read-only Screen Vision v1."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from grandpa.cli.chat_cmd import _handle_natural_assistant_intent
from grandpa.screen.analyzer import DeterministicScreenAnalyzer, detect_visible_error
from grandpa.screen.capture import ScreenCapture
from grandpa.screen.config import ScreenConfig
from grandpa.screen.errors import (
    InvalidScreenshotPathError,
    MonitorNotFoundError,
    ScreenCaptureError,
    ScreenConfigurationError,
    SensitiveScreenDetectedError,
)
from grandpa.screen.intents import handle_screen_command
from grandpa.screen.models import (
    MonitorInfo,
    OcrResult,
    ScreenCommandResult,
    ScreenshotResult,
    WindowInfo,
)
from grandpa.screen.ocr import TesseractOcrEngine, normalize_ocr_text, preprocess_image
from grandpa.screen.redaction import is_sensitive_screen, redact_screen_text
from grandpa.screen.service import ScreenVisionService
from grandpa.screen.windows import (
    _deduplicate_windows,
    _is_user_facing_window,
    virtual_desktop_bounds,
)
from grandpa.voice.assistant import VoiceCommandProcessor


def _screenshot(
    image: Image.Image | None = None, *, title: str = "Editor"
) -> ScreenshotResult:
    image = image or Image.new("RGB", (100, 60), "white")
    return ScreenshotResult(
        image=image,
        width=image.width,
        height=image.height,
        monitor_index=1,
        capture_region=(0, 0, image.width, image.height),
        active_window_title=title,
        captured_at=datetime(2026, 7, 22, 12, 0),
        backend="test",
    )


class _FakeCapture:
    def __init__(self, screenshot: ScreenshotResult | None = None) -> None:
        self.screenshot = screenshot or _screenshot()
        self.calls: list[tuple[int | None, bool]] = []

    def capture(
        self, *, monitor: int | None = None, active_window: bool = False
    ) -> ScreenshotResult:
        self.calls.append((monitor, active_window))
        return self.screenshot

    def save(self, screenshot: ScreenshotResult, **_kwargs) -> ScreenshotResult:
        return ScreenshotResult(
            **{**screenshot.__dict__, "saved_path": r"D:\Screenshots\screen.png"}
        )


class _FakeOcr:
    def __init__(self, result: OcrResult) -> None:
        self.result = result

    def extract_text(self, _image, *, language=None) -> OcrResult:
        return self.result

    def status(self) -> dict[str, object]:
        return {
            "available": True,
            "provider": "test",
            "executable": "test.exe",
            "language": "eng",
        }


def test_virtual_desktop_supports_negative_monitor_coordinates() -> None:
    monitors = [
        MonitorInfo(1, 0, 0, 1920, 1080, True),
        MonitorInfo(2, -1280, -200, 1280, 1024),
    ]
    assert virtual_desktop_bounds(monitors) == (-1280, -200, 1920, 1080)


def test_visible_window_filter_rejects_infrastructure_and_tool_windows() -> None:
    assert not _is_user_facing_window(
        title="Program Manager",
        class_name="Progman",
        exstyle=0,
        bounds=(0, 0, 100, 100),
        include_all=False,
    )
    assert not _is_user_facing_window(
        title="Tool",
        class_name="Tool",
        exstyle=0x80,
        bounds=(0, 0, 100, 100),
        include_all=False,
    )
    assert _is_user_facing_window(
        title="Visual Studio Code",
        class_name="Chrome_WidgetWin_1",
        exstyle=0,
        bounds=(0, 0, 100, 100),
        include_all=False,
    )


def test_visible_window_filter_rejects_empty_or_zero_size_windows() -> None:
    assert not _is_user_facing_window(
        title="",
        class_name="App",
        exstyle=0,
        bounds=(0, 0, 100, 100),
        include_all=False,
    )
    assert not _is_user_facing_window(
        title="App",
        class_name="App",
        exstyle=0,
        bounds=(0, 0, 1, 1),
        include_all=False,
    )


def test_window_titles_are_deduplicated_case_insensitively() -> None:
    records = [WindowInfo("Editor"), WindowInfo("editor"), WindowInfo("Browser")]
    assert [item.title for item in _deduplicate_windows(records)] == [
        "Editor",
        "Browser",
    ]


def test_full_desktop_and_single_monitor_capture_are_in_memory(monkeypatch) -> None:
    monitors = [MonitorInfo(1, -100, 0, 100, 80), MonitorInfo(2, 0, 0, 120, 90, True)]
    monkeypatch.setattr("grandpa.screen.capture.list_monitors", lambda: monitors)
    capture = ScreenCapture(ScreenConfig())
    regions: list[tuple[int, int, int, int]] = []

    def fake_capture(region):
        regions.append(region)
        return Image.new(
            "RGB", (region[2] - region[0], region[3] - region[1]), "white"
        ), "test"

    monkeypatch.setattr(capture, "_capture_region", fake_capture)
    full = capture.capture()
    second = capture.capture(monitor=2)

    assert regions == [(-100, 0, 120, 90), (0, 0, 120, 90)]
    assert full.temporary_path == ""
    assert full.saved_path == ""
    assert second.monitor_index == 2


def test_capture_does_not_create_temp_directory_or_file_by_default(
    tmp_path: Path, monkeypatch
) -> None:
    config = ScreenConfig(temp_dir=tmp_path / "screen-temp")
    monkeypatch.setattr(
        "grandpa.screen.capture.list_monitors",
        lambda: [MonitorInfo(1, 0, 0, 20, 20, True)],
    )
    capture = ScreenCapture(config)
    monkeypatch.setattr(
        capture,
        "_capture_region",
        lambda _region: (Image.new("RGB", (20, 20), "white"), "test"),
    )
    result = capture.capture()
    assert result.temporary_path == ""
    assert not config.temp_dir.exists()


def test_active_window_capture_uses_window_bounds(monkeypatch) -> None:
    window = WindowInfo("Editor", bounds=(-20, 10, 80, 70), monitor_index=2)
    monkeypatch.setattr("grandpa.screen.capture.list_monitors", lambda: [])
    monkeypatch.setattr("grandpa.screen.capture.get_active_window", lambda: window)
    capture = ScreenCapture(ScreenConfig())
    monkeypatch.setattr(
        capture,
        "_capture_region",
        lambda region: (Image.new("RGB", (100, 60), "white"), "test"),
    )
    result = capture.capture(active_window=True)
    assert result.capture_region == (-20, 10, 80, 70)
    assert result.active_window_title == "Editor"
    assert result.monitor_index == 2


def test_invalid_monitor_has_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.screen.capture.list_monitors", lambda: [MonitorInfo(1, 0, 0, 10, 10)]
    )
    with pytest.raises(MonitorNotFoundError, match="grandpa screen monitors"):
        ScreenCapture(ScreenConfig()).capture(monitor=3)


def test_capture_backend_failure_has_exact_install_guidance(monkeypatch) -> None:
    capture = ScreenCapture(ScreenConfig())
    monkeypatch.setattr(
        "grandpa.screen.capture.importlib_util.find_spec", lambda _name: None
    )
    monkeypatch.setattr(
        "PIL.ImageGrab.grab",
        Mock(side_effect=OSError("capture unavailable")),
    )
    with pytest.raises(ScreenCaptureError, match="uv sync --extra screen"):
        capture._capture_region((0, 0, 10, 10))


def test_explicit_save_and_overwrite_protection(tmp_path: Path) -> None:
    capture = ScreenCapture(ScreenConfig(screenshots_dir=tmp_path))
    screenshot = _screenshot()
    output = tmp_path / "saved.png"
    saved = capture.save(screenshot, output=output)
    assert output.is_file()
    assert saved.saved_path == str(output.resolve())
    with pytest.raises(InvalidScreenshotPathError, match="already exists"):
        capture.save(screenshot, output=output)
    capture.save(screenshot, output=output, overwrite=True)


def test_save_rejects_traversal_and_unknown_extension(tmp_path: Path) -> None:
    capture = ScreenCapture(ScreenConfig(screenshots_dir=tmp_path))
    with pytest.raises(InvalidScreenshotPathError):
        capture.save(_screenshot(), output=tmp_path / ".." / "secret.png")
    with pytest.raises(InvalidScreenshotPathError, match="PNG"):
        capture.save(_screenshot(), output=tmp_path / "screen.txt")


def test_screen_config_rejects_invalid_character_limit(monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_SCREEN_MAX_OCR_CHARS", "many")
    with pytest.raises(ScreenConfigurationError, match="must be an integer"):
        ScreenConfig.load()


def test_ocr_text_normalization_and_preprocessing() -> None:
    assert (
        normalize_ocr_text(" Hello   world\r\n\r\n\r\n Next ") == "Hello world\n\nNext"
    )
    original = Image.new("RGB", (100, 50), "blue")
    processed = preprocess_image(original)
    assert original.mode == "RGB"
    assert processed.mode == "L"
    assert processed.size == (200, 100)


def test_tesseract_success_empty_and_configured_path(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"")
    engine = TesseractOcrEngine(
        ScreenConfig(tesseract_cmd=str(executable), preprocess_ocr=False)
    )
    fake = SimpleNamespace(
        pytesseract=SimpleNamespace(tesseract_cmd=""),
        Output=SimpleNamespace(DICT="dict"),
        image_to_string=Mock(return_value="  Hello   screen  "),
        image_to_data=Mock(
            return_value={
                "text": ["Hello"],
                "conf": ["90"],
                "left": [1],
                "top": [2],
                "width": [3],
                "height": [4],
            }
        ),
    )
    monkeypatch.setattr("grandpa.screen.ocr.import_module", lambda _name: fake)
    result = engine.extract_text(Image.new("RGB", (20, 20), "white"))
    assert result.text == "Hello screen"
    assert result.confidence == pytest.approx(0.9)
    fake.image_to_string.return_value = "   "
    assert engine.extract_text(Image.new("RGB", (20, 20), "white")).text == ""
    assert fake.pytesseract.tesseract_cmd == str(executable)


def test_tesseract_status_is_friendly_when_executable_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.screen.ocr.find_tesseract", lambda _configured="": "")
    status = TesseractOcrEngine(ScreenConfig()).status()
    assert status["available"] is False
    assert "Screenshot capture and window inspection still work" in str(
        status["message"]
    )


def test_redacts_tokens_passwords_cards_otp_and_database_urls() -> None:
    source = (
        "Authorization: Bearer abcdefghijklmnop\n"
        "password=hunter2\n"
        "card 4111 1111 1111 1111\n"
        "OTP: 123456\n"
        "postgres://user:secret@localhost/db"
    )
    result = redact_screen_text(source)
    assert result.count >= 5
    assert "hunter2" not in result.text
    assert "4111" not in result.text
    assert "123456" not in result.text
    assert "postgres://" not in result.text
    assert "[REDACTED_TOKEN]" in result.text


def test_sensitive_context_detection_is_conservative() -> None:
    assert is_sensitive_screen(title="Windows Security - Enter password")
    assert is_sensitive_screen(text="Payment details and card verification")
    assert not is_sensitive_screen(
        title="Visual Studio Code", text="normal source code"
    )


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (
            "Traceback (most recent call last):\nModuleNotFoundError: No module named 'respx'",
            "python_traceback",
        ),
        ("Windows error: Access denied", "permission"),
    ],
)
def test_error_detection(text: str, kind: str) -> None:
    result = detect_visible_error(text)
    assert result.error_detected is True
    assert result.error_type == kind


def test_normal_text_is_not_reported_as_an_error() -> None:
    assert (
        detect_visible_error("Build documentation and open the editor").error_detected
        is False
    )


def test_deterministic_description_uses_only_supplied_local_context() -> None:
    analyzer = DeterministicScreenAnalyzer()
    description = analyzer.describe(
        _screenshot(title="Visual Studio Code"),
        OcrResult("Traceback\nModuleNotFoundError: No module named 'respx'"),
        active_window=WindowInfo("Visual Studio Code"),
        windows=[WindowInfo("Google Chrome")],
    )
    assert "Visual Studio Code" in description.summary
    assert "likely python traceback" in description.summary
    assert description.provider == "deterministic"


def test_service_ocr_fallback_and_voice_truncation() -> None:
    unavailable = OcrResult(
        "", available=False, provider="none", message="Tesseract OCR is not available."
    )
    service = ScreenVisionService(capture=_FakeCapture(), ocr=_FakeOcr(unavailable))
    assert service.read().status == "unsupported"

    long_text = "visible words " * 100
    service = ScreenVisionService(
        capture=_FakeCapture(), ocr=_FakeOcr(OcrResult(long_text))
    )
    result = service.read()
    assert len(result.spoken_text) < len(result.message)
    assert len(result.spoken_text) < 400


def test_service_capture_reports_saved_and_in_memory_states() -> None:
    capture = _FakeCapture()
    service = ScreenVisionService(capture=capture, ocr=_FakeOcr(OcrResult("")))
    transient = service.capture()
    saved = service.capture(save=True)
    assert transient.data["persisted"] is False
    assert transient.saved_path == ""
    assert saved.data["persisted"] is True
    assert saved.saved_path.endswith("screen.png")


def test_service_monitors_and_windows_are_concise(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.screen.service.list_monitors",
        lambda: [MonitorInfo(1, 0, 0, 1920, 1080, True)],
    )
    monkeypatch.setattr(
        "grandpa.screen.service.list_windows",
        lambda **_kwargs: [WindowInfo("Editor"), WindowInfo("Browser")],
    )
    service = ScreenVisionService(capture=_FakeCapture(), ocr=_FakeOcr(OcrResult("")))
    assert "1: 1920 x 1080" in service.monitors().message
    assert service.windows().spoken_text == "Open windows include Editor, Browser."


def test_service_active_omits_private_window_details(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.screen.service.get_active_window",
        lambda: WindowInfo(
            "Editor",
            process_name="Code.exe",
            executable_path=r"C:\Program Files\Code.exe",
            bounds=(0, 0, 1000, 700),
            monitor_index=1,
            handle=99,
        ),
    )
    service = ScreenVisionService(capture=_FakeCapture(), ocr=_FakeOcr(OcrResult("")))
    result = service.active()
    assert "Code.exe" in result.message
    assert "executable_path" not in result.data
    assert "handle" not in result.data


def test_custom_analyzer_can_be_injected_without_cloud_dependency(monkeypatch) -> None:
    analyzer = Mock()
    analyzer.describe.return_value = SimpleNamespace(
        summary="Local custom description.",
        content_type="test",
        error=SimpleNamespace(error_detected=False),
    )
    monkeypatch.setattr("grandpa.screen.service._optional_active_window", lambda: None)
    monkeypatch.setattr("grandpa.screen.service.list_windows", lambda: [])
    service = ScreenVisionService(
        capture=_FakeCapture(),
        ocr=_FakeOcr(OcrResult("visible text")),
        analyzer=analyzer,
    )
    assert service.describe().message == "Local custom description."
    analyzer.describe.assert_called_once()


def test_service_refuses_sensitive_screen_and_never_logs_raw_ocr(caplog) -> None:
    secret = "Enter password hunter2"
    service = ScreenVisionService(
        capture=_FakeCapture(), ocr=_FakeOcr(OcrResult(secret))
    )
    caplog.set_level(logging.INFO)
    with pytest.raises(SensitiveScreenDetectedError):
        service.read()
    assert secret not in caplog.text


def test_service_redacts_before_returning_text() -> None:
    service = ScreenVisionService(
        capture=_FakeCapture(),
        ocr=_FakeOcr(OcrResult("api_key=abcdefghijklmnop normal text")),
    )
    result = service.read()
    assert "abcdefghijklmnop" not in result.message
    assert "[REDACTED_TOKEN]" in result.message


@pytest.mark.parametrize(
    ("phrase", "method"),
    [
        ("Take a screenshot", "capture"),
        ("What is on my screen?", "describe"),
        ("Read the visible text", "read"),
        ("Read this error", "error"),
        ("What window is active?", "active"),
        ("List open windows", "windows"),
    ],
)
def test_shared_screen_intents_route_locally(phrase: str, method: str) -> None:
    service = Mock()
    getattr(service, method).return_value = ScreenCommandResult("handled", method)
    result = handle_screen_command(phrase, service=service)
    assert result.message == method
    getattr(service, method).assert_called_once()


def test_save_intent_requests_explicit_persistence() -> None:
    service = Mock()
    service.capture.return_value = ScreenCommandResult("handled", "saved")
    handle_screen_command("Save the current screenshot", service=service)
    service.capture.assert_called_once_with(save=True)


def test_unrelated_app_and_project_commands_do_not_initialize_screen_service() -> None:
    with patch("grandpa.screen.intents.ScreenVisionService") as service:
        assert handle_screen_command("Open Chrome").should_fallback
        assert handle_screen_command("Open Grandpa project").should_fallback
    service.assert_not_called()


def test_chat_and_voice_reuse_shared_screen_intent() -> None:
    result = ScreenCommandResult(
        "handled",
        "Active window:\nEditor\n\nProcess: Code.exe",
        "The active window is Editor.",
    )
    with patch("grandpa.screen.intents.ScreenVisionService") as service_type:
        service_type.return_value.active.return_value = result
        assert (
            _handle_natural_assistant_intent("What window is active?") == result.message
        )
        response = VoiceCommandProcessor()._handle_local_pipeline(
            "What window is active?"
        )
    assert response is not None
    assert response.text == result.spoken_text
    assert response.kind == "local"
