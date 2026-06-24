"""Safe Vision Mode foundation without live capture or model calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grandpa.vision.analyzer import VisionAnalyzer


@dataclass
class VisionSession:
    """Track opt-in image analysis state for user-submitted images only."""

    enabled: bool = False
    last_image_name: str | None = None
    last_image_size: dict[str, int] | None = None
    last_analysis: str | None = None
    last_error: str | None = None
    _analyzer: VisionAnalyzer = field(default_factory=VisionAnalyzer, repr=False)
    _last_format: str | None = field(default=None, init=False, repr=False)

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
            "last_image_name": self.last_image_name,
            "last_image_size": self.last_image_size,
            "last_format": self._last_format,
            "last_analysis": self.last_analysis,
            "last_error": self.last_error,
            "live_capture": False,
            "screen_capture_enabled": False,
            "webcam_enabled": False,
        }

    def analyze_image_bytes(self, data: bytes, filename: str | None, mime_type: str | None) -> dict[str, Any]:
        result = self._analyzer.analyze(data, filename, mime_type)
        if result.success:
            self.last_image_name = result.filename
            self.last_image_size = {
                "bytes": len(data),
                "width": int(result.width or 0),
                "height": int(result.height or 0),
            }
            self._last_format = result.format
            self.last_analysis = result.analysis
            self.last_error = None
        else:
            self.last_error = result.error
        return result.to_dict()
