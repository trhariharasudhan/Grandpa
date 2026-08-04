"""Safety policy for Calendar commands and event text."""

from __future__ import annotations

import re

MAX_EVENT_TEXT_CHARS = 2000

SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[\w\-\.]{8,}"
    ),
    re.compile(r"\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
)


class CalendarSafetyPolicy:
    """Safety policy for read/write Calendar actions."""

    def sanitize_text(self, value: str, *, limit: int = MAX_EVENT_TEXT_CHARS) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        if len(text) > limit:
            return text[:limit].rstrip() + "..."
        return text

    def requires_confirmation(self, action: str, *, recurring: bool = False) -> bool:
        return action in {"create", "update", "delete"} or recurring

    def is_blocked(self, action: str, *, auto_accept: bool = False) -> bool:
        return action == "accept_invitation" or auto_accept


__all__ = ["CalendarSafetyPolicy", "MAX_EVENT_TEXT_CHARS"]
