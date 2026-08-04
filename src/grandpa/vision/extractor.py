"""Capture and extract a reusable hybrid screen element graph."""

from __future__ import annotations

from dataclasses import replace

from grandpa.screen.capture import ScreenCapture
from grandpa.screen.errors import OcrUnavailableError
from grandpa.screen.models import OcrResult, ScreenshotResult, WindowInfo
from grandpa.screen.ocr import TesseractOcrEngine
from grandpa.screen.windows import get_active_window
from grandpa.vision.graph import ElementGraphBuilder
from grandpa.vision.models import ElementGraph, VisionCaptureMetadata
from grandpa.vision.uia import UiAutomationExtractor


class VisionExtractor:
    """Compose existing capture, OCR, and UIA services."""

    def __init__(
        self,
        *,
        capture: ScreenCapture | None = None,
        ocr: TesseractOcrEngine | None = None,
        uia: UiAutomationExtractor | None = None,
        graph_builder: ElementGraphBuilder | None = None,
    ) -> None:
        self.capture = capture or ScreenCapture()
        self.ocr = ocr or TesseractOcrEngine()
        self.uia = uia or UiAutomationExtractor()
        self.graph_builder = graph_builder or ElementGraphBuilder()

    def inspect(
        self,
        *,
        active_window: bool = True,
        monitor: int | None = None,
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[ElementGraph, ScreenshotResult]:
        screenshot = self.capture.capture(
            active_window=active_window,
            monitor=monitor,
            region=region,
        )
        active = _active_window()
        warnings: list[str] = []
        try:
            ocr = self.ocr.extract_text(screenshot.image)
        except OcrUnavailableError as exc:
            ocr = OcrResult("", available=False, provider="none", message=str(exc))
            warnings.append(str(exc))
        except Exception as exc:
            ocr = OcrResult(
                "",
                available=False,
                provider="none",
                message="OCR processing failed.",
            )
            warnings.append(f"OCR unavailable: {type(exc).__name__}")
        uia_nodes = self.uia.extract(active)
        if active_window:
            uia_nodes = _align_uia_to_capture(uia_nodes, screenshot)
        if not uia_nodes and self.uia.last_error:
            warnings.append(f"UI Automation unavailable: {self.uia.last_error}")
        metadata = _metadata(screenshot, active)
        graph = self.graph_builder.build(
            capture=metadata,
            ocr=ocr,
            uia_nodes=uia_nodes,
            warnings=tuple(warnings),
        )
        return graph, screenshot


def _active_window() -> WindowInfo | None:
    try:
        return get_active_window()
    except Exception:
        return None


def _metadata(
    screenshot: ScreenshotResult, active: WindowInfo | None
) -> VisionCaptureMetadata:
    return VisionCaptureMetadata(
        width=screenshot.width,
        height=screenshot.height,
        monitor=screenshot.monitor_index,
        window_title=(
            screenshot.active_window_title or (active.title if active else "")
        ),
        window_handle=screenshot.window_handle or (active.handle if active else 0),
        process_id=screenshot.process_id or (active.pid if active else 0),
        timestamp=screenshot.captured_at,
        source=screenshot.capture_source,
        backend=screenshot.backend,
        region=screenshot.capture_region,
    )


def _align_uia_to_capture(
    nodes,
    screenshot: ScreenshotResult,
):
    root = next(
        (
            item
            for item in nodes
            if item.type == "window"
            and item.bounds.width > 0
            and item.bounds.height > 0
        ),
        None,
    )
    if root is None:
        return nodes
    scale_x = screenshot.width / root.bounds.width
    scale_y = screenshot.height / root.bounds.height
    if abs(scale_x - 1.0) < 0.03 and abs(scale_y - 1.0) < 0.03:
        return nodes
    capture_left, capture_top = screenshot.capture_region[:2]
    return tuple(
        replace(
            item,
            bounds=type(item.bounds)(
                round(capture_left + (item.bounds.left - root.bounds.left) * scale_x),
                round(capture_top + (item.bounds.top - root.bounds.top) * scale_y),
                round(item.bounds.width * scale_x),
                round(item.bounds.height * scale_y),
            ),
        )
        for item in nodes
    )


__all__ = ["VisionExtractor"]
