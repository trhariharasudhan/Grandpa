"""Safety helpers for read-only browser awareness."""

from __future__ import annotations

import re

MAX_CAPTURED_TEXT_CHARS = 8000

SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[\w\-\.]{8,}"
    ),
    re.compile(r"\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b\d{6}\b"),
)


def sanitize_visible_text(text: str, *, limit: int = MAX_CAPTURED_TEXT_CHARS) -> str:
    value = str(text or "")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[redacted]", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        return value[:limit].rstrip() + "..."
    return value


def sanitize_link_text(value: str, *, limit: int = 120) -> str:
    cleaned = sanitize_visible_text(value, limit=limit)
    return cleaned or "Untitled link"


__all__ = ["MAX_CAPTURED_TEXT_CHARS", "sanitize_link_text", "sanitize_visible_text"]
