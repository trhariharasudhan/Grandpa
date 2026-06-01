"""Local screen awareness helpers for Grandpa.

All capture/OCR work stays on the local machine. Optional dependencies are
used only when installed; missing screen/OCR backends degrade to a clear text
response instead of blocking normal chat.
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenElement:
    role: str
    text: str
    confidence: float = 0.0
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "hint": self.hint,
        }


@dataclass(frozen=True)
class PopupInsight:
    detected: bool
    category: str = "none"
    severity: str = "info"
    title: str = ""
    evidence: tuple[str, ...] = ()
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "evidence": list(self.evidence),
            "recommended_action": self.recommended_action,
        }


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float = 0.0
    backend: str = "unavailable"
    lines: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": bool(self.text),
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "backend": self.backend,
            "lines": list(self.lines),
            "message": self.message,
        }


@dataclass(frozen=True)
class ScreenContext:
    supported: bool
    window_title: str = ""
    app_name: str = ""
    screenshot_path: str = ""
    ocr_text: str = ""
    message: str = ""
    ocr_confidence: float = 0.0
    popup: PopupInsight | None = None
    elements: tuple[ScreenElement, ...] = ()
    suggestions: tuple[str, ...] = ()
    windows: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "window_title": self.window_title,
            "app_name": self.app_name,
            "screenshot_path": self.screenshot_path,
            "ocr_text": self.ocr_text,
            "ocr_confidence": round(self.ocr_confidence, 3),
            "popup": (self.popup or PopupInsight(False)).to_dict(),
            "elements": [element.to_dict() for element in self.elements],
            "suggestions": list(self.suggestions),
            "windows": list(self.windows),
            "diagnostics": self.diagnostics or {},
            "message": self.message,
            "local_only": True,
        }


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

    ocr = OcrResult("")
    if include_ocr and screenshot.screenshot_path:
        ocr = extract_ocr_result(screenshot.screenshot_path)

    elements = detect_ui_elements(ocr.text)
    popup = classify_popup_or_error(ocr.text, window_title=window.window_title)
    suggestions = build_navigation_suggestions(elements, popup, window.app_name)
    windows = get_visible_windows()

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

    if popup.detected:
        parts.append(
            f"{popup.severity.title()} {popup.category}: "
            f"{popup.recommended_action or 'Review the visible message before acting.'}"
        )

    if elements:
        button_count = sum(1 for item in elements if item.role == "button")
        field_count = sum(1 for item in elements if item.role == "field")
        label_count = sum(1 for item in elements if item.role == "label")
        parts.append(
            f"Visible UI: {button_count} buttons, {field_count} fields, "
            f"{label_count} labels detected."
        )

    if suggestions:
        parts.append("Safe suggestions:\n" + "\n".join(f"- {item}" for item in suggestions[:4]))

    if ocr.text:
        excerpt = ocr.text.strip()
        if len(excerpt) > 1200:
            excerpt = excerpt[:1200].rstrip() + "..."
        confidence = f" ({ocr.confidence:.0%} OCR confidence)" if ocr.confidence else ""
        parts.append("Visible text" + confidence + ":\n" + excerpt)
    elif include_ocr:
        parts.append(
            ocr.message
            or "OCR text is not available. Install/configure Tesseract to read screen text."
        )

    context = ScreenContext(
        supported=window.supported or screenshot.supported,
        window_title=window.window_title,
        app_name=window.app_name,
        screenshot_path=screenshot.screenshot_path,
        ocr_text=ocr.text,
        ocr_confidence=ocr.confidence,
        popup=popup,
        elements=tuple(elements),
        suggestions=tuple(suggestions),
        windows=tuple(windows),
        diagnostics=screen_diagnostics(window=window, screenshot=screenshot, ocr=ocr),
        message="\n".join(parts),
    )
    _record_visual_context(context)
    return context


def extract_text_from_image(path: str) -> str:
    """Run local OCR if pytesseract and Tesseract are available."""
    return extract_ocr_result(path).text


def extract_ocr_result(path: str) -> OcrResult:
    """Run local OCR with lightweight preprocessing and confidence metadata."""
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        image = Image.open(path)
        variants = [image]
        try:
            grayscale = image.convert("L")
            variants.append(grayscale)
            variants.append(grayscale.point(lambda p: 255 if p > 165 else 0))
        except Exception:
            pass

        best_text = ""
        best_confidence = 0.0
        best_lines: tuple[str, ...] = ()
        configs = ("--psm 6", "--psm 11", "")
        for variant in variants:
            for config in configs:
                try:
                    text = pytesseract.image_to_string(variant, config=config).strip()
                    confidence = _ocr_confidence(pytesseract, variant, config)
                    if _ocr_score(text, confidence) > _ocr_score(best_text, best_confidence):
                        best_text = text
                        best_confidence = confidence
                        best_lines = tuple(_clean_ocr_lines(text))
                except Exception:
                    continue
        return OcrResult(
            text=best_text,
            confidence=best_confidence,
            backend="pytesseract",
            lines=best_lines,
            message="OCR completed locally." if best_text else "OCR ran but no readable text was detected.",
        )
    except Exception as exc:
        logger.debug("OCR unavailable for %s: %s", path, exc)
        return OcrResult(
            text="",
            backend="unavailable",
            message=(
                "OCR text is not available. Install Pillow, pytesseract, and "
                "the Tesseract executable to read screen text."
            ),
        )


def classify_popup_or_error(text: str, *, window_title: str = "") -> PopupInsight:
    """Classify likely popups/errors from local OCR text and window title."""
    combined = f"{window_title}\n{text}".strip()
    lowered = combined.lower()
    if not combined:
        return PopupInsight(False)

    patterns: list[tuple[str, str, str, tuple[str, ...], str]] = [
        (
            "permission",
            "warning",
            "Permission prompt",
            ("allow", "deny", "permission", "access"),
            "Confirm the request is expected before choosing Allow.",
        ),
        (
            "network_error",
            "warning",
            "Network or connection error",
            ("network error", "connection failed", "can't reach", "offline", "timed out"),
            "Check the connection or retry after the service is reachable.",
        ),
        (
            "application_error",
            "error",
            "Application error",
            ("error", "exception", "failed", "crash", "traceback", "not responding"),
            "Read the error details and avoid destructive actions until it is understood.",
        ),
        (
            "confirmation",
            "warning",
            "Confirmation dialog",
            ("are you sure", "confirm", "save changes", "discard", "unsaved"),
            "Review the dialog; use the safest non-destructive option if unsure.",
        ),
        (
            "security",
            "critical",
            "Security warning",
            ("password", "credential", "security warning", "certificate", "malware"),
            "Do not share secrets; handle this manually unless you explicitly approve.",
        ),
    ]
    for category, severity, title, keywords, action in patterns:
        evidence = tuple(keyword for keyword in keywords if _contains_phrase(lowered, keyword))
        if category == "permission" and not (
            "permission" in evidence
            or "access" in evidence
            or ("allow" in evidence and "deny" in evidence)
        ):
            evidence = ()
        if evidence:
            return PopupInsight(True, category, severity, title, evidence, action)
    return PopupInsight(False)


def detect_ui_elements(text: str) -> list[ScreenElement]:
    """Infer visible buttons, labels, and input fields from OCR text."""
    elements: list[ScreenElement] = []
    seen: set[tuple[str, str]] = set()
    button_words = {
        "ok",
        "cancel",
        "yes",
        "no",
        "allow",
        "deny",
        "save",
        "discard",
        "close",
        "retry",
        "continue",
        "next",
        "back",
        "submit",
        "sign in",
        "search",
        "download",
    }
    field_words = ("search", "email", "username", "name", "message", "comment", "filter")
    for raw in _clean_ocr_lines(text):
        lowered = raw.lower().strip(" :")
        if not lowered:
            continue
        role = "label"
        hint = "Visible text label."
        confidence = 0.45
        if lowered in button_words or lowered.startswith(tuple(f"{word} " for word in ("ok", "save", "retry", "continue"))):
            role = "button"
            hint = "Likely clickable button."
            confidence = 0.72
        elif any(word in lowered for word in field_words) and len(lowered) <= 80:
            role = "field"
            hint = "Likely editable field or nearby field label."
            confidence = 0.62
        elif lowered.endswith(":") or raw.endswith(":"):
            role = "field"
            hint = "Likely field label."
            confidence = 0.55
        key = (role, lowered)
        if key in seen:
            continue
        seen.add(key)
        elements.append(ScreenElement(role=role, text=raw[:120], confidence=confidence, hint=hint))
        if len(elements) >= 30:
            break
    return elements


def build_navigation_suggestions(
    elements: list[ScreenElement],
    popup: PopupInsight,
    app_name: str,
) -> list[str]:
    suggestions: list[str] = []
    if popup.detected:
        if popup.category == "security":
            suggestions.append("Handle the security prompt manually unless you explicitly approve an action.")
        elif popup.category == "confirmation":
            suggestions.append("Ask Grandpa to read the dialog before choosing a confirmation button.")
        else:
            suggestions.append("Ask Grandpa to read the visible error before trying another action.")
    buttons = [item.text for item in elements if item.role == "button"]
    if buttons:
        suggestions.append("Visible buttons: " + ", ".join(buttons[:6]) + ".")
    fields = [item.text for item in elements if item.role == "field"]
    if fields:
        suggestions.append("Visible fields may be targetable after confirmation: " + ", ".join(fields[:4]) + ".")
    if app_name:
        suggestions.append(f"Current app context appears to be {app_name}.")
    if not suggestions:
        suggestions.append("Use a specific visible label, button name, or app name for safer navigation.")
    return suggestions[:6]


def get_visible_windows(limit: int = 12) -> list[dict[str, Any]]:
    """Return visible top-level windows when Windows APIs are available."""
    if sys.platform != "win32":
        return []
    try:
        from grandpa.windows_window_control import list_open_windows

        result = list_open_windows()
        windows = getattr(result, "windows", []) or []
        items: list[dict[str, Any]] = []
        for item in windows[:limit]:
            title = getattr(item, "title", "") or ""
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "app_name": getattr(item, "app_name", "") or getattr(item, "app_id", "") or _app_name_from_title(title),
                    "process_name": getattr(item, "process_name", "") or getattr(item, "app_id", ""),
                }
            )
        return items
    except Exception as exc:
        logger.debug("Visible window enumeration failed: %s", exc)
        return []


def screen_diagnostics(
    *,
    window: ScreenContext | None = None,
    screenshot: ScreenContext | None = None,
    ocr: OcrResult | None = None,
) -> dict[str, Any]:
    """Return fast, read-only screen-awareness readiness diagnostics."""
    window = window or get_active_window_info()
    screenshot_backend = _available_screenshot_backends()
    ocr_status = ocr or OcrResult("")
    return {
        "platform": sys.platform,
        "supported": sys.platform == "win32",
        "active_window": {
            "supported": window.supported,
            "title": window.window_title,
            "app_name": window.app_name,
            "message": window.message,
        },
        "screenshot": {
            "supported": bool(screenshot_backend),
            "backends": screenshot_backend,
            "last_path": screenshot.screenshot_path if screenshot else "",
        },
        "ocr": ocr_status.to_dict(),
        "visible_window_count": len(get_visible_windows()),
        "local_only": True,
    }


def _ocr_confidence(pytesseract: Any, image: Any, config: str) -> float:
    try:
        data = pytesseract.image_to_data(
            image,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
        values = []
        for raw in data.get("conf", []):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                values.append(value)
        if not values:
            return 0.0
        return max(0.0, min(1.0, sum(values) / len(values) / 100.0))
    except Exception:
        return 0.0


def _ocr_score(text: str, confidence: float) -> float:
    clean = text.strip()
    if not clean:
        return 0.0
    return len(clean) * (0.65 + confidence)


def _clean_ocr_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 2:
            continue
        if not re.search(r"[A-Za-z0-9]", line):
            continue
        lines.append(line)
    return lines


def _contains_phrase(text: str, phrase: str) -> bool:
    words = re.escape(phrase).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<![A-Za-z0-9]){words}(?![A-Za-z0-9])", text, re.I))


def _available_screenshot_backends() -> list[str]:
    backends: list[str] = []
    try:
        from PIL import ImageGrab  # noqa: F401

        backends.append("Pillow ImageGrab")
    except Exception:
        pass
    try:
        import pyautogui  # noqa: F401

        backends.append("pyautogui")
    except Exception:
        pass
    return backends


def _record_visual_context(context: ScreenContext) -> None:
    if not context.supported:
        return
    detail = {
        "window_title": context.window_title,
        "app_name": context.app_name,
        "popup": context.popup.to_dict() if context.popup else {},
        "element_counts": dict(Counter(item.role for item in context.elements)),
        "ocr_confidence": round(context.ocr_confidence, 3),
    }
    try:
        from grandpa.memory_context import record_activity

        record_activity(
            "screen",
            "visual_context",
            context.app_name or context.window_title or "screen",
            str(detail),
            "handled",
        )
    except Exception:
        return


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
    "ScreenElement",
    "PopupInsight",
    "OcrResult",
    "capture_screenshot",
    "classify_popup_or_error",
    "detect_ui_elements",
    "describe_screen",
    "extract_ocr_result",
    "extract_text_from_image",
    "get_active_window_info",
    "get_visible_windows",
    "screen_diagnostics",
]
