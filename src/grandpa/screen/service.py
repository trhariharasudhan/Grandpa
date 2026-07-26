"""High-level read-only Screen Vision service."""

from __future__ import annotations

import logging
import platform
import re
import sys
from pathlib import Path
from typing import Any

from grandpa.screen.analyzer import DeterministicScreenAnalyzer, detect_visible_error
from grandpa.screen.capture import ScreenCapture, available_capture_backend
from grandpa.screen.config import ScreenConfig
from grandpa.screen.errors import OcrUnavailableError, SensitiveScreenDetectedError
from grandpa.screen.models import OcrResult, ScreenCommandResult, ScreenDiagnosticResult
from grandpa.screen.ocr import TesseractOcrEngine
from grandpa.screen.redaction import is_sensitive_screen, redact_screen_text
from grandpa.screen.windows import (
    get_active_window,
    list_monitors,
    list_windows,
    virtual_desktop_bounds,
)

logger = logging.getLogger(__name__)
SENSITIVE_MESSAGE = "This screen may contain sensitive information. Screen text was not displayed or stored."


class ScreenVisionService:
    def __init__(
        self,
        *,
        config: ScreenConfig | None = None,
        capture: ScreenCapture | None = None,
        ocr: TesseractOcrEngine | None = None,
        analyzer: Any | None = None,
    ) -> None:
        self.config = config or ScreenConfig.load()
        self.capture_backend = capture or ScreenCapture(self.config)
        self.ocr_engine = ocr or TesseractOcrEngine(self.config)
        self.analyzer = analyzer or DeterministicScreenAnalyzer()

    def capture(
        self,
        *,
        monitor: int | None = None,
        active_window: bool = False,
        save: bool = False,
        output: str | Path | None = None,
        overwrite: bool = False,
    ) -> ScreenCommandResult:
        screenshot = self.capture_backend.capture(
            monitor=monitor, active_window=active_window
        )
        if save or output is not None:
            screenshot = self.capture_backend.save(
                screenshot, output=output, overwrite=overwrite
            )
        message = f"Screenshot captured in memory ({screenshot.width} x {screenshot.height}) using {screenshot.backend}."
        if screenshot.saved_path:
            message = f"Screenshot saved: {screenshot.saved_path}"
        return ScreenCommandResult(
            "handled",
            message,
            "Screenshot saved." if screenshot.saved_path else "Screenshot captured.",
            "capture",
            screenshot.saved_path,
            {
                "width": screenshot.width,
                "height": screenshot.height,
                "monitor_index": screenshot.monitor_index,
                "capture_region": screenshot.capture_region,
                "backend": screenshot.backend,
                "persisted": bool(screenshot.saved_path),
            },
        )

    def read(
        self,
        *,
        monitor: int | None = None,
        active_window: bool = False,
        language: str | None = None,
    ) -> ScreenCommandResult:
        screenshot = self.capture_backend.capture(
            monitor=monitor, active_window=active_window
        )
        ocr = self._safe_ocr(screenshot.image, language=language)
        title = screenshot.active_window_title
        if is_sensitive_screen(title=title, text=ocr.text):
            logger.warning("Sensitive screen context detected; OCR output suppressed")
            raise SensitiveScreenDetectedError(SENSITIVE_MESSAGE)
        redacted = redact_screen_text(ocr.text)
        logger.info("Screen OCR redaction completed replacements=%s", redacted.count)
        if not ocr.available:
            return ScreenCommandResult("unsupported", ocr.message, ocr.message, "read")
        if not redacted.text:
            return ScreenCommandResult(
                "handled",
                "OCR ran, but no readable text was detected.",
                "No readable text was detected.",
                "read",
            )
        spoken = _spoken_excerpt(redacted.text)
        return ScreenCommandResult(
            "handled",
            f"Visible text:\n{redacted.text}",
            f"I found visible text. {spoken}",
            "read",
            data={
                "character_count": len(redacted.text),
                "word_count": ocr.word_count,
                "confidence": ocr.confidence,
            },
        )

    def describe(
        self, *, monitor: int | None = None, active_window: bool = False
    ) -> ScreenCommandResult:
        screenshot = self.capture_backend.capture(
            monitor=monitor, active_window=active_window
        )
        active = _optional_active_window()
        windows = list_windows()[:10]
        ocr = self._safe_ocr(screenshot.image)
        title = active.title if active else screenshot.active_window_title
        if is_sensitive_screen(title=title, text=ocr.text):
            raise SensitiveScreenDetectedError(SENSITIVE_MESSAGE)
        redacted = redact_screen_text(ocr.text)
        safe_ocr = OcrResult(
            text=redacted.text,
            confidence=ocr.confidence,
            word_count=len(redacted.text.split()),
            language=ocr.language,
            duration_ms=ocr.duration_ms,
            blocks=(),
            provider=ocr.provider,
            available=ocr.available,
            message=ocr.message,
        )
        description = self.analyzer.describe(
            screenshot, safe_ocr, active_window=active, windows=windows
        )
        return ScreenCommandResult(
            "handled",
            description.summary,
            _spoken_excerpt(description.summary, limit=420),
            "describe",
            data={
                "content_type": description.content_type,
                "error_detected": description.error.error_detected,
            },
        )

    def error(
        self, *, monitor: int | None = None, active_window: bool = False
    ) -> ScreenCommandResult:
        screenshot = self.capture_backend.capture(
            monitor=monitor, active_window=active_window
        )
        ocr = self._safe_ocr(screenshot.image)
        title = screenshot.active_window_title
        if is_sensitive_screen(title=title, text=ocr.text):
            raise SensitiveScreenDetectedError(SENSITIVE_MESSAGE)
        redacted = redact_screen_text(ocr.text)
        if not ocr.available:
            return ScreenCommandResult("unsupported", ocr.message, ocr.message, "error")
        result = detect_visible_error(redacted.text)
        if not result.error_detected:
            return ScreenCommandResult(
                "handled",
                "No clear error message was detected in the visible text.",
                "I could not find a clear visible error.",
                "error",
            )
        lines = "\n".join(result.relevant_lines)
        message = (
            f"Detected text:\n{lines}\n\n"
            f"Likely interpretation: {result.error_type.replace('_', ' ')}."
        )
        if result.possible_component:
            message += f"\nSuggested next check: inspect the {result.possible_component} output or configuration."
        return ScreenCommandResult(
            "handled",
            message,
            f"A likely {result.error_type.replace('_', ' ')} is visible. {result.headline}",
            "error",
            data={"error_type": result.error_type, "confidence": result.confidence},
        )

    def active(self) -> ScreenCommandResult:
        window = get_active_window()
        if is_sensitive_screen(title=window.title):
            raise SensitiveScreenDetectedError(SENSITIVE_MESSAGE)
        message = (
            f"Active window:\n{window.title}\n\n"
            f"Process: {window.process_name or 'Unknown'}\n"
            f"Monitor: {window.monitor_index or 'Unknown'}\n"
            f"Size: {window.width} x {window.height}"
        )
        return ScreenCommandResult(
            "handled",
            message,
            f"The active window is {window.title}.",
            "active",
            data=window.to_dict(),
        )

    def windows(
        self, *, visible_only: bool = True, include_all: bool = False
    ) -> ScreenCommandResult:
        records = list_windows(visible_only=visible_only, include_all=include_all)
        if not records:
            return ScreenCommandResult(
                "handled",
                "No visible user-facing windows were found.",
                "No visible windows were found.",
                "windows",
                data={"windows": []},
            )
        names = [record.title for record in records]
        message = "Open windows:\n" + "\n".join(f"- {name}" for name in names)
        spoken = "Open windows include " + ", ".join(names[:10]) + "."
        return ScreenCommandResult(
            "handled",
            message,
            spoken,
            "windows",
            data={"windows": [item.to_dict() for item in records]},
        )

    def monitors(self) -> ScreenCommandResult:
        records = list_monitors()
        if not records:
            return ScreenCommandResult(
                "unsupported",
                "No monitors could be inspected.",
                "Monitor inspection is unavailable.",
                "monitors",
            )
        lines = ["Monitors:"]
        for item in records:
            primary = " (primary)" if item.is_primary else ""
            lines.append(
                f"- {item.index}: {item.width} x {item.height} at ({item.left}, {item.top}){primary}"
            )
        return ScreenCommandResult(
            "handled",
            "\n".join(lines),
            f"I found {len(records)} monitors.",
            "monitors",
            data={"monitors": [item.to_dict() for item in records]},
        )

    def diagnose(self) -> ScreenDiagnosticResult:
        monitors = list_monitors()
        ocr = self.ocr_engine.status()
        bounds = virtual_desktop_bounds(monitors)
        return ScreenDiagnosticResult(
            platform=platform.platform(),
            python_executable=sys.executable,
            capture_backend=available_capture_backend(),
            monitor_count=len(monitors),
            primary_monitor=next(
                (item.index for item in monitors if item.is_primary), None
            ),
            virtual_desktop_bounds=bounds,
            active_window_api="ready" if _active_window_ready() else "unavailable",
            ocr_provider=str(ocr["provider"]),
            tesseract_executable=str(ocr["executable"]),
            ocr_language=str(ocr["language"]),
            temporary_directory=str(self.config.temp_dir),
        )

    def _safe_ocr(self, image: Any, *, language: str | None = None) -> OcrResult:
        try:
            return self.ocr_engine.extract_text(image, language=language)
        except OcrUnavailableError as exc:
            logger.info("Screen OCR unavailable: %s", exc)
            return OcrResult("", available=False, provider="none", message=str(exc))


def _optional_active_window():
    try:
        return get_active_window()
    except Exception:
        return None


def _active_window_ready() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32gui  # type: ignore

        return callable(win32gui.GetForegroundWindow)
    except Exception:
        return False


def _spoken_excerpt(text: str, *, limit: int = 320) -> str:
    compact = " ".join(text.split())
    compact = re.sub(r"https?://\S+", "a web address", compact)
    return compact[:limit].rstrip() + ("..." if len(compact) > limit else "")


__all__ = ["SENSITIVE_MESSAGE", "ScreenVisionService"]
