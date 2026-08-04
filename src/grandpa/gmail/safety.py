"""Safety and prompt-injection defenses for Gmail content."""

from __future__ import annotations

import html
import re

MAX_EMAIL_BODY_CHARS = 6000
MAX_SUMMARY_CHARS = 1200

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all )?(?:previous|prior) instructions", re.I),
    re.compile(r"reveal (?:your )?(?:system|developer) prompt", re.I),
    re.compile(r"send (?:me )?(?:your )?(?:password|token|api key|otp)", re.I),
    re.compile(r"urgent.*(?:payment|wire|gift card|password|otp)", re.I),
)

SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[\w\-\.]{8,}"
    ),
    re.compile(r"\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b\d{6}\b"),
)

EXECUTABLE_ATTACHMENT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".js",
    ".msi",
    ".ps1",
    ".scr",
    ".vbs",
}


class GmailSafetyPolicy:
    """Safety policy for Gmail read/write actions."""

    def sanitize_text(self, value: str, *, limit: int = MAX_EMAIL_BODY_CHARS) -> str:
        text = _strip_html(value)
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > limit:
            return text[:limit].rstrip() + "..."
        return text

    def suspicious_markers(self, value: str) -> tuple[str, ...]:
        found = []
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(value):
                found.append(pattern.pattern)
        return tuple(found)

    def summarize_body(self, value: str) -> str:
        text = self.sanitize_text(value, limit=MAX_SUMMARY_CHARS)
        if self.suspicious_markers(value):
            return (
                "Suspicious email content detected. Summary is sanitized and instructions inside the email were ignored. "
                + text
            )
        return text

    def attachment_is_blocked(self, filename: str) -> bool:
        lowered = filename.lower()
        return any(lowered.endswith(ext) for ext in EXECUTABLE_ATTACHMENT_EXTENSIONS)

    def requires_confirmation(self, action: str, *, bulk: bool = False) -> bool:
        return action in {"send", "reply", "forward", "archive", "label", "trash"}


def _strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text)


__all__ = ["GmailSafetyPolicy", "MAX_EMAIL_BODY_CHARS", "MAX_SUMMARY_CHARS"]
