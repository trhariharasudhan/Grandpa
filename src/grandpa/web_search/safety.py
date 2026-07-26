"""Safety helpers for untrusted web search content."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

MAX_SNIPPET_CHARS = 800
MAX_QUERY_CHARS = 300

DANGEROUS_SCHEMES = {"file", "ftp", "javascript", "mailto", "powershell", "cmd", "data"}
LOW_QUALITY_MARKERS = {"content-farm", "coupon", "free-download", "cracked", "warez"}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[\w\-\.]{8,}"),
    re.compile(r"\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
)


class WebSearchSafetyPolicy:
    """Treat web content as untrusted and keep queries/results safe."""

    def sanitize_query(self, query: str) -> str:
        text = re.sub(r"\s+", " ", str(query or "")).strip()
        return text[:MAX_QUERY_CHARS]

    def sanitize_text(self, value: str, *, limit: int = MAX_SNIPPET_CHARS) -> str:
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        text = re.sub(r"(?i)ignore (?:all )?(?:previous|prior) instructions", "[ignored web instruction]", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > limit:
            return text[:limit].rstrip() + "..."
        return text

    def safe_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def domain(self, url: str) -> str:
        return urlparse(url).netloc.lower().removeprefix("www.")

    def is_low_quality(self, url: str) -> bool:
        domain = self.domain(url)
        return any(marker in domain for marker in LOW_QUALITY_MARKERS)


class WebSearchSafetyError(RuntimeError):
    """Raised when web search content or URLs violate safety rules."""


__all__ = ["WebSearchSafetyError", "WebSearchSafetyPolicy"]
