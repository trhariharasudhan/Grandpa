"""In-memory session buffer (Short-Term Memory) for Grandpa."""

from __future__ import annotations

import time
import uuid
from typing import Any

from grandpa.memory.models import MemoryItem


class ShortTermMemory:
    """Session-isolated, transient short-term memory buffer."""

    def __init__(self, session_id: str | None = None, max_items: int = 50) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self.max_items = max_items
        self._buffer: list[MemoryItem] = []

    def add(
        self,
        content: str,
        key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """Add a short-term session memory entry."""
        item_key = key or f"session_{self.session_id}_{len(self._buffer) + 1}"
        item = MemoryItem(
            key=item_key,
            content=content,
            category="session",
            metadata={"session_id": self.session_id, **(metadata or {})},
            created_at=time.time(),
        )
        self._buffer.append(item)
        if len(self._buffer) > self.max_items:
            self._buffer.pop(0)
        return item

    def get_session_memories(self) -> list[MemoryItem]:
        """Return current session memories in chronological order."""
        return list(self._buffer)

    def clear(self) -> None:
        """Clear short-term session buffer."""
        self._buffer.clear()

    def promote(self, key_or_id: str, store: Any) -> MemoryItem | None:
        """Promote a short-term session memory item to long-term persistent store."""
        target = None
        for item in self._buffer:
            if item.key == key_or_id or item.id == key_or_id:
                target = item
                break
        if not target:
            return None

        promoted = MemoryItem(
            key=target.key,
            content=target.content,
            category="knowledge",
            metadata={**target.metadata, "promoted_from_session": self.session_id},
        )
        return store.insert(promoted)
