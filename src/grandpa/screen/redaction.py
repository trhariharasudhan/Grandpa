"""Screen-text redaction and sensitive-context detection."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(?:authorization|bearer)\s*[:=]?\s+[A-Za-z0-9._~+/=-]{8,}"),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|session[_ -]?id|cookie)\s*[:=]\s*['\"]?[^\s'\",;]{6,}"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"(?i)\b(?:password|passwd|pwd|cvv)\s*[:=]\s*['\"]?[^\s'\",;]{3,}"),
        "[REDACTED_PASSWORD]",
    ),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "[REDACTED_SECRET]",
    ),
    (
        re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s]+"),
        "[REDACTED_SECRET]",
    ),
    (
        re.compile(
            r"(?i)(\b(?:otp|verification code|one[- ]time code|recovery code)\s*[:=]?\s*)\d{4,12}\b"
        ),
        r"\1[REDACTED_SECRET]",
    ),
    (re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "[REDACTED_CARD]"),
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[REDACTED_SECRET]"),
    (
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[oprsu]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"(?im)^\s*[A-Z][A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY)[A-Z0-9_]*\s*=\s*.+$"
        ),
        "[REDACTED_SECRET]",
    ),
    # Slack-style workspace tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-).
    (
        re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
        "[REDACTED_TOKEN]",
    ),
    # JSON Web Tokens: three base64url segments. Anchored on the standard
    # ``eyJ`` header prefix so ordinary dotted identifiers are not matched.
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        "[REDACTED_TOKEN]",
    ),
    # One-time codes introduced in prose rather than as a key/value pair,
    # e.g. "Your verification code is 894213". The keyed form is handled by
    # the OTP pattern above; this covers the phrasing sites actually use.
    (
        re.compile(
            r"(?i)\b((?:verification|security|authentication|login|access|one[- ]time|recovery)\s+code\s+(?:is\s+)?)\d{4,12}\b"
        ),
        r"\1[REDACTED_SECRET]",
    ),
)

_SENSITIVE_CONTEXT = re.compile(
    r"(?i)\b(password manager|enter password|confirm password|windows security|user account control|sign[- ]in options|payment details|card verification|online banking|recovery codes?)\b"
)


def redact_screen_text(text: str) -> RedactionResult:
    redacted = text
    count = 0
    for pattern, replacement in _PATTERNS:
        redacted, replacements = pattern.subn(replacement, redacted)
        count += replacements
    return RedactionResult(redacted, count)


def is_sensitive_screen(*, title: str = "", text: str = "") -> bool:
    return bool(_SENSITIVE_CONTEXT.search(f"{title}\n{text}"))


__all__ = ["RedactionResult", "is_sensitive_screen", "redact_screen_text"]
