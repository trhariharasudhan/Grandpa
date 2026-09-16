"""Safety helpers for read-only browser awareness.

Secret redaction is delegated twice over: to :func:`grandpa.screen.redaction
.redact_screen_text`, the canonical routine shared with ``screen/`` and
``vision/``, and then to ``browser_control``'s ``_SECRET_VALUE_RE``, which is
the ingress boundary every browser-derived string already passes through.

The patterns used to be copied here, and the copies drifted: this one carried a
bare six-digit rule and the ingress did not, so an unlabelled one-time code was
redacted when chat read the page and not when the action layer, pc_control or
``browser_intelligence`` did. One list, held where the ingress is, is what stops
that happening again.
"""

from __future__ import annotations

import re

from grandpa.screen.redaction import redact_screen_text

MAX_CAPTURED_TEXT_CHARS = 8000


def _secret_patterns() -> tuple[re.Pattern[str], ...]:
    """The ingress boundary's own list, compiled.

    Imported lazily: ``browser_control`` is heavy and imports back into this
    package's capture, so taking it at module import would be a cycle.
    """
    from grandpa.browser_control import _SECRET_VALUE_RE

    return tuple(re.compile(pattern) for pattern in _SECRET_VALUE_RE)


def sanitize_visible_text(text: str, *, limit: int = MAX_CAPTURED_TEXT_CHARS) -> str:
    value = redact_screen_text(str(text or "")).text
    for pattern in _secret_patterns():
        value = pattern.sub("[redacted]", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        return value[:limit].rstrip() + "..."
    return value


def sanitize_link_text(value: str, *, limit: int = 120) -> str:
    cleaned = sanitize_visible_text(value, limit=limit)
    return cleaned or "Untitled link"


__all__ = ["MAX_CAPTURED_TEXT_CHARS", "sanitize_link_text", "sanitize_visible_text"]
