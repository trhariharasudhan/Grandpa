"""Safety helpers for read-only browser awareness.

Secret redaction is delegated to :func:`grandpa.screen.redaction
.redact_screen_text`, the canonical routine shared with ``screen/``,
``vision/``, ``browser_control`` and ``browser_intelligence``. The local
patterns below run afterwards and cover shapes the canonical set does not,
so neither loses coverage; adding a pattern to the canonical set improves
every ingress path at once.
"""

from __future__ import annotations

import re

from grandpa.screen.redaction import redact_screen_text

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
    value = redact_screen_text(str(text or "")).text
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
