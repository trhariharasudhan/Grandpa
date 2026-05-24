"""Local screen awareness helpers for Grandpa.

All capture/OCR work stays on the local machine. Optional dependencies are
used only when installed; missing screen/OCR backends degrade to a clear text
response instead of blocking normal chat.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenContext:
    supported: bool
    window_title: str = ""
    app_name: str = ""
    screenshot_path: str = ""
    ocr_text: str = ""
    message: str = ""


def get_active_window_info() -> ScreenContext:
    """Return foreground window title/app details when supported."""
    if sys.platform != "win32":
        return ScreenContext(
            supported=False,
            message="Screen awareness is not supported in this environment.",
        )

    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        return ScreenContext(
            supported=True,
            window_title=title or "Unknown window",
            app_name=_app_name_from_title(title),
        )
    except Exception as exc:  # pragma: no cover - platform/permission edge
        logger.debug("Active window detection failed: %s", exc)
        return ScreenContext(
            supported=False,
            message="I could not detect the active window.",
        )


def capture_screenshot() -> ScreenContext:
    """Capture the current screen to ~/.grandpa/screenshots if possible."""
    if sys.platform != "win32":
        return ScreenContext(
            supported=False,
            message="Screenshot capture is not supported in this environment.",
        )

    target_dir = Path.home() / ".grandpa" / "screenshots"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"screen-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"

    try:
        from PIL import ImageGrab  # type: ignore

        image = ImageGrab.grab()
        image.save(path)
        return ScreenContext(
            supported=True,
            screenshot_path=str(path),
            message=f"Screenshot saved to {path}.",
        )
    except Exception as pil_exc:
        logger.debug("Pillow screenshot capture unavailable: %s", pil_exc)

    try:
        import pyautogui  # type: ignore

        image = pyautogui.screenshot()
        image.save(path)
        return ScreenContext(
            supported=True,
            screenshot_path=str(path),
            message=f"Screenshot saved to {path}.",
        )
    except Exception as auto_exc:
        logger.debug("pyautogui screenshot capture unavailable: %s", auto_exc)
        return ScreenContext(
            supported=False,
            message=(
                "Screenshot capture needs Pillow or pyautogui installed on "
                "this Windows machine."
            ),
        )


def describe_screen(*, include_ocr: bool = True) -> ScreenContext:
    """Capture available screen context and extract local OCR text if possible."""
    window = get_active_window_info()
    screenshot = capture_screenshot()

    ocr_text = ""
    if include_ocr and screenshot.screenshot_path:
        ocr_text = extract_text_from_image(screenshot.screenshot_path)

    parts: list[str] = []
    if window.supported:
        parts.append(f"Active window: {window.window_title}")
        if window.app_name:
            parts.append(f"App/browser: {window.app_name}")
    elif window.message:
        parts.append(window.message)

    if screenshot.screenshot_path:
        parts.append(f"Screenshot: {screenshot.screenshot_path}")
    elif screenshot.message:
        parts.append(screenshot.message)

    if ocr_text:
        excerpt = ocr_text.strip()
        if len(excerpt) > 1200:
            excerpt = excerpt[:1200].rstrip() + "..."
        parts.append("Visible text:\n" + excerpt)
    elif include_ocr:
        parts.append(
            "OCR text is not available. Install/configure Tesseract to read "
            "screen text."
        )

    return ScreenContext(
        supported=window.supported or screenshot.supported,
        window_title=window.window_title,
        app_name=window.app_name,
        screenshot_path=screenshot.screenshot_path,
        ocr_text=ocr_text,
        message="\n".join(parts),
    )


def extract_text_from_image(path: str) -> str:
    """Run local OCR if pytesseract and Tesseract are available."""
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        text = pytesseract.image_to_string(Image.open(path))
        return text.strip()
    except Exception as exc:
        logger.debug("OCR unavailable for %s: %s", path, exc)
        return ""


def _app_name_from_title(title: str) -> str:
    lowered = title.lower()
    if "chrome" in lowered:
        return "Chrome"
    if "edge" in lowered:
        return "Microsoft Edge"
    if "firefox" in lowered:
        return "Firefox"
    if "visual studio code" in lowered or "vs code" in lowered:
        return "VS Code"
    if "notepad" in lowered:
        return "Notepad"
    return ""


__all__ = [
    "ScreenContext",
    "capture_screenshot",
    "describe_screen",
    "extract_text_from_image",
    "get_active_window_info",
]
