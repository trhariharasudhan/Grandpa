from __future__ import annotations

import grandpa.screen_awareness as screen_awareness


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
