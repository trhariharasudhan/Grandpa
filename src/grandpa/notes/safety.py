"""Safety helpers for local note storage."""

from __future__ import annotations

import re
from pathlib import Path

SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[\w\-\.]{8,}"
    ),
    re.compile(r"\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
)


class NotesSafetyPolicy:
    """Guard notes against path traversal, secret capture, and unsafe writes."""

    def sanitize_title(self, title: str) -> str:
        value = re.sub(r"\s+", " ", str(title or "")).strip()
        value = value.strip(".\\/ ")
        return value[:120] or "Untitled Note"

    def slugify(self, title: str) -> str:
        value = self.sanitize_title(title).casefold()
        value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
        return value or "untitled-note"

    def contains_secret(self, text: str) -> bool:
        return any(pattern.search(text or "") for pattern in SECRET_PATTERNS)

    def ensure_inside_root(self, root: Path, path: Path) -> Path:
        root_resolved = root.resolve()
        path_resolved = path.resolve()
        if (
            root_resolved != path_resolved
            and root_resolved not in path_resolved.parents
        ):
            raise NotesSafetyError(
                "Blocked unsafe note path outside the notes directory."
            )
        return path_resolved

    def requires_confirmation(self, action: str) -> bool:
        return action == "delete"


class NotesSafetyError(RuntimeError):
    """Raised when a note operation violates local safety rules."""


__all__ = ["NotesSafetyError", "NotesSafetyPolicy"]
