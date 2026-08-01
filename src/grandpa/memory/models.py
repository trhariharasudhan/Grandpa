"""Data models for Grandpa Memory System V1."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

MemoryCategory = Literal["session", "project", "preference", "knowledge"]

_SENSITIVE_PATTERNS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "auth_token",
    "bearer",
    "private_key",
    "credit_card",
    "card_number",
    "cvv",
    "otp",
)


def is_sensitive_content(text: str) -> bool:
    """Return True if text appears to contain raw passwords, keys, or private auth materials."""
    tlower = text.lower()
    return any(p in tlower for p in _SENSITIVE_PATTERNS)


def redact_sensitive(text: str) -> str:
    """Redact sensitive keywords in text for CLI output and logging."""
    if not text:
        return ""
    result = text
    for word in ("password", "secret", "api_key", "token", "cvv"):
        if word in result.lower():
            result = f"[REDACTED CONTENT containing {word}]"
            break
    return result


@dataclass
class MemoryItem:
    """A single structured memory record."""

    key: str
    content: str
    category: MemoryCategory = "knowledge"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "user"
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    access_count: int = 0
    is_deleted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert MemoryItem to a dictionary representation."""
        return {
            "id": self.id,
            "key": self.key,
            "content": self.content,
            "category": self.category,
            "project_name": self.project_name,
            "metadata": self.metadata,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "access_count": self.access_count,
            "is_deleted": self.is_deleted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryItem:
        """Construct MemoryItem from dictionary data."""
        meta = data.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            key=str(data.get("key") or ""),
            content=str(data.get("content") or ""),
            category=data.get("category", "knowledge"),
            project_name=data.get("project_name"),
            metadata=meta,
            source=str(data.get("source") or "user"),
            confidence=float(data.get("confidence") or 1.0),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            expires_at=data.get("expires_at"),
            access_count=int(data.get("access_count") or 0),
            is_deleted=bool(data.get("is_deleted") or False),
        )
