"""Typed models for read-only Screen Vision."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MonitorInfo:
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False
    name: str = ""

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WindowInfo:
    title: str
    process_name: str = ""
    pid: int = 0
    executable_path: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    is_visible: bool = True
    is_minimized: bool = False
    monitor_index: int = 0
    handle: int = 0

    @property
    def width(self) -> int:
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self) -> int:
        return max(0, self.bounds[3] - self.bounds[1])

    def to_dict(self, *, include_private: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_private:
            data.pop("executable_path", None)
            data.pop("handle", None)
        return data


@dataclass(frozen=True)
class ScreenshotResult:
    image: Any
    width: int
    height: int
    monitor_index: int | None
    capture_region: tuple[int, int, int, int]
    active_window_title: str = ""
    captured_at: datetime = field(default_factory=datetime.now)
    temporary_path: str = ""
    backend: str = ""
    saved_path: str = ""


@dataclass(frozen=True)
class OcrBlock:
    text: str
    confidence: float
    bounds: tuple[int, int, int, int]


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float = 0.0
    word_count: int = 0
    language: str = "eng"
    duration_ms: float = 0.0
    blocks: tuple[OcrBlock, ...] = ()
    provider: str = "pytesseract"
    available: bool = True
    message: str = ""


@dataclass(frozen=True)
class ScreenErrorResult:
    error_detected: bool
    error_type: str = "none"
    headline: str = ""
    relevant_lines: tuple[str, ...] = ()
    possible_component: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class ScreenDescription:
    summary: str
    content_type: str
    active_window_title: str
    visible_windows: tuple[str, ...]
    dimensions: tuple[int, int]
    text_excerpt: str = ""
    error: ScreenErrorResult = field(default_factory=lambda: ScreenErrorResult(False))
    provider: str = "deterministic"


@dataclass(frozen=True)
class ScreenCommandResult:
    status: str
    message: str
    spoken_text: str = ""
    action: str = ""
    saved_path: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


@dataclass(frozen=True)
class ScreenDiagnosticResult:
    platform: str
    python_executable: str
    capture_backend: str
    monitor_count: int
    primary_monitor: int | None
    virtual_desktop_bounds: tuple[int, int, int, int]
    active_window_api: str
    ocr_provider: str
    tesseract_executable: str
    ocr_language: str
    temporary_directory: str
    local_vision_provider: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "MonitorInfo",
    "OcrBlock",
    "OcrResult",
    "ScreenCommandResult",
    "ScreenDescription",
    "ScreenDiagnosticResult",
    "ScreenErrorResult",
    "ScreenshotResult",
    "WindowInfo",
]
