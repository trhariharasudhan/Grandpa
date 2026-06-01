from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import grandpa.screen_awareness as screen_awareness
from grandpa.server.routes import router


def test_active_window_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(screen_awareness.sys, "platform", "linux")

    result = screen_awareness.get_active_window_info()

    assert not result.supported
    assert "not supported" in result.message


def test_screenshot_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(screen_awareness.sys, "platform", "linux")

    result = screen_awareness.capture_screenshot()

    assert not result.supported
    assert "not supported" in result.message


def test_ocr_gracefully_handles_missing_backend(tmp_path):
    missing = tmp_path / "missing.png"

    assert screen_awareness.extract_text_from_image(str(missing)) == ""


def test_popup_error_classification():
    result = screen_awareness.classify_popup_or_error(
        "Application Error\nSomething failed. Retry Cancel",
        window_title="Error",
    )

    assert result.detected
    assert result.category == "application_error"
    assert result.severity == "error"
    assert "failed" in result.evidence


def test_security_popup_classification():
    result = screen_awareness.classify_popup_or_error("Password required\nAllow Deny")

    assert result.detected
    assert result.category == "permission"
    assert result.severity == "warning"


def test_detect_ui_elements_from_ocr_text():
    elements = screen_awareness.detect_ui_elements(
        "Search\nUsername:\nContinue\nCancel\nWelcome to the app"
    )

    roles = {element.role for element in elements}
    assert "button" in roles
    assert "field" in roles
    assert any(element.text == "Continue" for element in elements)


def test_navigation_suggestions_include_popup_and_buttons():
    popup = screen_awareness.classify_popup_or_error("Error failed Retry Cancel")
    elements = screen_awareness.detect_ui_elements("Retry\nCancel")

    suggestions = screen_awareness.build_navigation_suggestions(elements, popup, "Chrome")

    assert any("error" in suggestion.lower() for suggestion in suggestions)
    assert any("Retry" in suggestion for suggestion in suggestions)


def test_screen_diagnostics_is_read_only_off_windows(monkeypatch):
    monkeypatch.setattr(screen_awareness.sys, "platform", "linux")

    result = screen_awareness.screen_diagnostics()

    assert result["platform"] == "linux"
    assert not result["supported"]
    assert result["local_only"]


def test_describe_screen_builds_structured_context(monkeypatch, tmp_path):
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"not really an image")
    monkeypatch.setattr(
        screen_awareness,
        "get_active_window_info",
        lambda: screen_awareness.ScreenContext(
            supported=True,
            window_title="Example Error - Chrome",
            app_name="Chrome",
        ),
    )
    monkeypatch.setattr(
        screen_awareness,
        "capture_screenshot",
        lambda: screen_awareness.ScreenContext(
            supported=True,
            screenshot_path=str(screenshot_path),
            message="Screenshot saved.",
        ),
    )
    monkeypatch.setattr(
        screen_awareness,
        "extract_ocr_result",
        lambda path: screen_awareness.OcrResult(
            text="Application Error\nRetry\nCancel\nSearch",
            confidence=0.82,
            backend="mock",
            lines=("Application Error", "Retry", "Cancel", "Search"),
        ),
    )
    monkeypatch.setattr(screen_awareness, "get_visible_windows", lambda: [{"title": "Example Error - Chrome"}])
    monkeypatch.setattr(screen_awareness, "_record_visual_context", lambda context: None)

    context = screen_awareness.describe_screen()

    assert context.supported
    assert context.popup and context.popup.detected
    assert context.ocr_confidence == 0.82
    assert any(element.role == "button" for element in context.elements)
    assert "Visible UI" in context.message


def test_screen_diagnostics_route(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(
        screen_awareness,
        "screen_diagnostics",
        lambda: {
            "platform": "win32",
            "supported": True,
            "active_window": {"supported": True, "title": "Demo", "app_name": "Chrome", "message": ""},
            "screenshot": {"supported": True, "backends": ["Pillow ImageGrab"], "last_path": ""},
            "ocr": {"available": False, "backend": "unavailable", "text": "", "confidence": 0, "lines": [], "message": ""},
            "visible_window_count": 1,
            "local_only": True,
        },
    )

    response = TestClient(app).get("/v1/screen/diagnostics")

    assert response.status_code == 200
    assert response.json()["supported"] is True
