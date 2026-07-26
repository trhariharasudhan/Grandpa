"""Visible UI element location and non-interactive highlighting."""

from __future__ import annotations

import logging
import re
import threading
from difflib import SequenceMatcher
from typing import Any, Callable

from grandpa.automation.models import BoundingBox, LocatedElement
from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.redaction import is_sensitive_screen

logger = logging.getLogger(__name__)


class ScreenElementLocator:
    """Locate visible text-backed controls using Screen Vision OCR blocks."""

    def __init__(self, *, screen_service: Any | None = None) -> None:
        self._screen_service = screen_service

    def locate(self, query: str, *, limit: int = 5) -> tuple[LocatedElement, ...]:
        service = self._screen_service or _default_screen_service()
        screenshot = service.capture_backend.capture(active_window=False)
        ocr = service.ocr_engine.extract_text(screenshot.image)
        if is_sensitive_screen(title=screenshot.active_window_title, text=ocr.text):
            raise SensitiveScreenDetectedError(
                "I will not locate controls on a screen that may contain sensitive information."
            )
        query_text = _normalize(query)
        if not query_text:
            return ()
        offset_x, offset_y = screenshot.capture_region[:2]
        matches: list[LocatedElement] = []
        for block in ocr.blocks:
            candidate = _normalize(block.text)
            confidence = _match_confidence(query_text, candidate, block.confidence)
            if confidence < 0.45:
                continue
            left, top, width, height = block.bounds
            matches.append(
                LocatedElement(
                    text=block.text.strip(),
                    role=_infer_role(query, block.text),
                    confidence=confidence,
                    bounds=BoundingBox(left + offset_x, top + offset_y, width, height),
                    source="screen_vision_ocr",
                    window_title=screenshot.active_window_title,
                )
            )
        try:
            from grandpa.screen.windows import list_windows

            for window in list_windows():
                title = _normalize(window.title)
                confidence = _match_confidence(query_text, title, 1.0)
                if confidence < 0.55:
                    continue
                left, top, right, bottom = window.bounds
                matches.append(
                    LocatedElement(
                        text=window.title,
                        role="window title",
                        confidence=confidence,
                        bounds=BoundingBox(left, top, right - left, bottom - top),
                        source="window_metadata",
                        window_title=window.title,
                    )
                )
        except Exception:
            logger.debug("Window metadata was unavailable during element lookup")
        matches.sort(key=lambda item: (-item.confidence, item.bounds.top, item.bounds.left))
        return tuple(matches[: max(1, limit)])


class HighlightOverlay:
    """Draw a short-lived, click-through-free visual rectangle without clicking."""

    def __init__(self, renderer: Callable[[LocatedElement, float], None] | None = None) -> None:
        self._renderer = renderer or _render_tk_overlay

    def show(self, element: LocatedElement, *, duration_seconds: float = 1.5) -> None:
        self._renderer(element, duration_seconds)


def _default_screen_service():
    from grandpa.screen.service import ScreenVisionService

    return ScreenVisionService()


def _match_confidence(query: str, candidate: str, ocr_confidence: float) -> float:
    if not candidate:
        return 0.0
    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    token_score = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))
    phrase_score = 1.0 if query in candidate or (len(candidate) >= 4 and candidate in query) else 0.0
    fuzzy_score = SequenceMatcher(None, query, candidate).ratio()
    text_score = max(phrase_score, token_score, fuzzy_score)
    return round(text_score * 0.8 + max(0.0, min(1.0, ocr_confidence)) * 0.2, 3)


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def _infer_role(query: str, text: str) -> str:
    haystack = f"{query} {text}".casefold()
    for role in ("button", "icon", "label", "input field", "search box", "window title"):
        if role in haystack:
            return role
    return "text"


def _render_tk_overlay(element: LocatedElement, duration_seconds: float) -> None:
    def draw() -> None:
        try:
            import tkinter as tk

            box = element.bounds
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.geometry(f"{max(1, box.width)}x{max(1, box.height)}+{box.left}+{box.top}")
            transparent = "#010101"
            root.configure(bg=transparent)
            try:
                root.wm_attributes("-transparentcolor", transparent)
            except Exception:
                pass
            canvas = tk.Canvas(
                root,
                bg=transparent,
                highlightbackground="#ffc448",
                highlightthickness=3,
            )
            canvas.pack(fill="both", expand=True)
            canvas.create_text(
                6,
                6,
                anchor="nw",
                text=f"{element.confidence:.0%}",
                fill="#ffc448",
            )
            root.after(max(100, int(duration_seconds * 1000)), root.destroy)
            root.mainloop()
        except Exception as exc:
            logger.debug("Automation highlight overlay unavailable: %s", exc)

    threading.Thread(target=draw, name="grandpa-highlight", daemon=True).start()


__all__ = ["HighlightOverlay", "ScreenElementLocator"]
