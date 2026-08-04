"""In-memory multi-monitor and active-window screenshot capture."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from datetime import datetime
from importlib import util as importlib_util
from pathlib import Path

from PIL import Image

from grandpa.screen.config import ScreenConfig
from grandpa.screen.errors import (
    ActiveWindowUnavailableError,
    InvalidScreenshotPathError,
    MonitorNotFoundError,
    ScreenCaptureError,
)
from grandpa.screen.models import ScreenshotResult
from grandpa.screen.windows import (
    get_active_window,
    list_monitors,
    virtual_desktop_bounds,
)

logger = logging.getLogger(__name__)


def available_capture_backend() -> str:
    return "mss" if importlib_util.find_spec("mss") is not None else "Pillow ImageGrab"


class ScreenCapture:
    def __init__(self, config: ScreenConfig | None = None) -> None:
        self.config = config or ScreenConfig.load()

    def capture(
        self,
        *,
        monitor: int | None = None,
        active_window: bool = False,
        region: tuple[int, int, int, int] | None = None,
    ) -> ScreenshotResult:
        selected_sources = sum((monitor is not None, active_window, region is not None))
        if selected_sources > 1:
            raise ScreenCaptureError(
                "Choose one capture source: monitor, active window, or region."
            )
        monitors = list_monitors()
        title = ""
        window_handle = 0
        process_id = 0
        selected_monitor: int | None = monitor
        if active_window:
            window = get_active_window()
            if window.width <= 0 or window.height <= 0 or window.is_minimized:
                raise ActiveWindowUnavailableError(
                    "The active window could not be captured. Try the full monitor instead."
                )
            region = window.bounds
            title = window.title
            window_handle = window.handle
            process_id = window.pid
            selected_monitor = window.monitor_index or None
            capture_source = "active_window"
        elif monitor is not None:
            selected = next((item for item in monitors if item.index == monitor), None)
            if selected is None:
                raise MonitorNotFoundError(
                    f"Monitor {monitor} was not found. Use `grandpa screen monitors` to list available monitors."
                )
            region = selected.bounds
            capture_source = "monitor"
        elif region is not None:
            region = tuple(int(value) for value in region)
            capture_source = "region"
        else:
            region = virtual_desktop_bounds(monitors)
            capture_source = "full_desktop"
        if region[2] <= region[0] or region[3] <= region[1]:
            raise ScreenCaptureError("No capturable desktop region was detected.")

        logger.info(
            "Screen capture started backend=%s monitor=%s",
            available_capture_backend(),
            selected_monitor,
        )
        image, backend = self._capture_region(region)
        if _is_black_image(image):
            raise ScreenCaptureError(
                "The captured screen is blank. Windows may be protecting a secure desktop or sign-in screen."
            )
        result = ScreenshotResult(
            image=image,
            width=image.width,
            height=image.height,
            monitor_index=selected_monitor,
            capture_region=region,
            active_window_title=title,
            captured_at=datetime.now(),
            backend=backend,
            capture_source=capture_source,
            window_handle=window_handle,
            process_id=process_id,
        )
        logger.info(
            "Screen capture completed backend=%s monitor=%s dimensions=%sx%s",
            backend,
            selected_monitor,
            image.width,
            image.height,
        )
        return result

    def save(
        self,
        screenshot: ScreenshotResult,
        *,
        output: str | Path | None = None,
        overwrite: bool = False,
    ) -> ScreenshotResult:
        path = self._safe_output_path(output)
        if path.exists() and not overwrite:
            raise InvalidScreenshotPathError(
                f"Screenshot already exists: {path}. Choose another path or allow overwrite explicitly."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        screenshot.image.save(path)
        logger.info(
            "Screenshot saved path=%s dimensions=%sx%s",
            path,
            screenshot.width,
            screenshot.height,
        )
        return replace(screenshot, saved_path=str(path))

    def _capture_region(
        self, region: tuple[int, int, int, int]
    ) -> tuple[Image.Image, str]:
        if importlib_util.find_spec("mss") is not None:
            try:
                import mss

                box = {
                    "left": region[0],
                    "top": region[1],
                    "width": region[2] - region[0],
                    "height": region[3] - region[1],
                }
                with mss.mss() as grabber:
                    shot = grabber.grab(box)
                return Image.frombytes(
                    "RGB", shot.size, shot.bgra, "raw", "BGRX"
                ), "mss"
            except Exception as exc:
                logger.debug("mss capture failed; falling back to Pillow: %s", exc)
        try:
            from PIL import ImageGrab

            return ImageGrab.grab(bbox=region, all_screens=True), "Pillow ImageGrab"
        except Exception as exc:
            raise ScreenCaptureError(
                "Screen capture is unavailable. Install screen support with: uv sync --extra screen"
            ) from exc

    def _safe_output_path(self, output: str | Path | None) -> Path:
        if output is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            return (self.config.screenshots_dir / f"screen-{stamp}.png").resolve(
                strict=False
            )
        raw = str(output)
        if "\x00" in raw or any(part == ".." for part in re.split(r"[\\/]", raw)):
            raise InvalidScreenshotPathError("The screenshot output path is invalid.")
        expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
        path = expanded.resolve(strict=False)
        if path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise InvalidScreenshotPathError(
                "Screenshots must use PNG, JPG, JPEG, or WEBP format."
            )
        return path


def _is_black_image(image: Image.Image) -> bool:
    sample = image.convert("RGB").resize((8, 8))
    extrema = sample.getextrema()
    return all(high <= 2 for _low, high in extrema)


__all__ = ["ScreenCapture", "available_capture_backend"]
