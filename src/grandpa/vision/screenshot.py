"""User-initiated screenshot ingestion for Vision Mode.

This module treats screenshots as uploaded image bytes only. It does not capture
the desktop, watch the screen, or start any background work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from grandpa.vision.analyzer import VisionAnalyzer
from grandpa.vision.local_model import (
    DEFAULT_VISION_PROMPT,
    analyze_image_with_local_model,
    local_model_status,
)
from grandpa.vision.ocr import extract_text_from_image_bytes, ocr_status


@dataclass
class ScreenshotSession:
    """Track safe manual screenshot uploads without direct desktop capture."""

    enabled: bool = False
    last_capture_name: str | None = None
    last_capture_size: dict[str, int] | None = None
    last_capture_at: str | None = None
    last_error: str | None = None
    _analyzer: VisionAnalyzer = field(default_factory=VisionAnalyzer, repr=False)

    def enable(self) -> dict[str, Any]:
        self.enabled = True
        self.last_error = None
        return self.status()

    def disable(self) -> dict[str, Any]:
        self.enabled = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "last_capture_name": self.last_capture_name,
            "last_capture_size": self.last_capture_size,
            "last_capture_at": self.last_capture_at,
            "last_error": self.last_error,
            "ocr": ocr_status(),
            "local_model": local_model_status(),
            "desktop_capture": False,
            "live_capture": False,
        }

    def ingest_screenshot_bytes(
        self,
        data: bytes,
        filename: str | None,
        mime_type: str | None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        analysis = self._analyzer.analyze(data, filename, mime_type)
        normalized_mime = (mime_type or "").split(";")[0].strip().lower()
        if not analysis.success:
            self.last_error = analysis.error
            return {
                "ok": False,
                "filename": analysis.filename,
                "mime_type": normalized_mime or None,
                "width": analysis.width,
                "height": analysis.height,
                "analysis": analysis.analysis,
                "error": analysis.error,
                "ocr": {
                    "available": False,
                    "text": "",
                    "engine": "none",
                    "error": analysis.error,
                },
                "model_analysis": {
                    "available": False,
                    "model": None,
                    "analysis": "",
                    "error": analysis.error,
                },
            }

        self.last_capture_name = analysis.filename
        self.last_capture_size = {
            "bytes": len(data),
            "width": int(analysis.width or 0),
            "height": int(analysis.height or 0),
        }
        self.last_capture_at = datetime.now(UTC).isoformat()
        self.last_error = None
        model_prompt = (prompt or DEFAULT_VISION_PROMPT).strip() or DEFAULT_VISION_PROMPT
        return {
            "ok": True,
            "filename": analysis.filename,
            "mime_type": normalized_mime or None,
            "width": analysis.width,
            "height": analysis.height,
            "analysis": analysis.analysis,
            "error": None,
            "ocr": extract_text_from_image_bytes(data, normalized_mime),
            "model_analysis": analyze_image_with_local_model(data, filename, mime_type, model_prompt),
        }
