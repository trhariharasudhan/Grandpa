"""Deterministic, local-only screen and visible-error analysis."""

from __future__ import annotations

import re
from typing import Protocol

from grandpa.screen.models import (
    OcrResult,
    ScreenDescription,
    ScreenErrorResult,
    ScreenshotResult,
    WindowInfo,
)


class ScreenAnalyzer(Protocol):
    def describe(
        self,
        screenshot: ScreenshotResult,
        ocr: OcrResult,
        *,
        active_window: WindowInfo | None = None,
        windows: list[WindowInfo] | None = None,
    ) -> ScreenDescription: ...


_ERROR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "python_traceback",
        re.compile(
            r"(?i)(traceback \(most recent call last\)|\b[A-Za-z]+Error:|ModuleNotFoundError)"
        ),
    ),
    ("permission", re.compile(r"(?i)(access denied|permission denied|winerror\s*5)")),
    (
        "connection",
        re.compile(r"(?i)(connection refused|connection failed|timed?\s*out|timeout)"),
    ),
    ("http", re.compile(r"(?i)\b(?:HTTP\s*)?[45]\d{2}\b")),
    ("test_failure", re.compile(r"(?i)(tests? failed|\bfailed\b|assertionerror)")),
    (
        "compiler",
        re.compile(r"(?i)(syntax error|syntaxerror|compiler error|build failed)"),
    ),
    ("generic", re.compile(r"(?i)\b(error|exception|failure|not found)\b")),
)


def detect_visible_error(text: str) -> ScreenErrorResult:
    if not text.strip():
        return ScreenErrorResult(False)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for error_type, pattern in _ERROR_PATTERNS:
        matching = [line for line in lines if pattern.search(line)]
        if not matching:
            continue
        headline = matching[-1][:300]
        component = _possible_component(error_type, text)
        confidence = 0.92 if error_type != "generic" else 0.65
        return ScreenErrorResult(
            True, error_type, headline, tuple(matching[-6:]), component, confidence
        )
    return ScreenErrorResult(False)


class DeterministicScreenAnalyzer:
    def describe(
        self,
        screenshot: ScreenshotResult,
        ocr: OcrResult,
        *,
        active_window: WindowInfo | None = None,
        windows: list[WindowInfo] | None = None,
    ) -> ScreenDescription:
        windows = windows or []
        title = active_window.title if active_window else screenshot.active_window_title
        error = detect_visible_error(ocr.text)
        content_type = _content_type(title, ocr.text)
        names = tuple(item.title for item in windows[:10])
        parts = [
            f"The active window is {title}."
            if title
            else "The active window could not be identified."
        ]
        parts.append(
            f"The screen is {screenshot.width} by {screenshot.height} pixels and appears to show {content_type}."
        )
        if error.error_detected:
            parts.append(
                f"A likely {error.error_type.replace('_', ' ')} is visible: {error.headline}"
            )
        elif ocr.text:
            excerpt = " ".join(ocr.text.split())[:500]
            parts.append(f"Visible text includes: {excerpt}")
        else:
            parts.append("No readable text was detected.")
        if names:
            parts.append("Other visible windows include " + ", ".join(names[:4]) + ".")
        return ScreenDescription(
            summary="\n\n".join(parts),
            content_type=content_type,
            active_window_title=title,
            visible_windows=names,
            dimensions=(screenshot.width, screenshot.height),
            text_excerpt=ocr.text[:1000],
            error=error,
        )


def _content_type(title: str, text: str) -> str:
    combined = f"{title}\n{text}".casefold()
    if any(
        token in combined
        for token in ("visual studio code", ".py", "pytest", "terminal", "traceback")
    ):
        return "a development workspace or terminal"
    if any(
        token in combined
        for token in ("chrome", "edge", "firefox", "http://", "https://")
    ):
        return "a web browser"
    if any(token in combined for token in ("document", "word", "notepad")):
        return "a document or text editor"
    return "a desktop application"


def _possible_component(error_type: str, text: str) -> str:
    lowered = text.casefold()
    if error_type == "python_traceback" or "python" in lowered:
        return "Python"
    if error_type == "http":
        return "HTTP service"
    if error_type == "test_failure":
        return "Test runner"
    if "windows" in lowered or "winerror" in lowered:
        return "Windows"
    return ""


__all__ = ["DeterministicScreenAnalyzer", "ScreenAnalyzer", "detect_visible_error"]
