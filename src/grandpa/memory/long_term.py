"""Durable Knowledge (Long-Term Memory) for Grandpa."""

from __future__ import annotations

from typing import Any

from grandpa.memory.models import MemoryItem
from grandpa.memory.store import MemoryStore


class LongTermMemory:
    """Long-term durable knowledge manager backed by MemoryStore."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def remember_fact(
        self,
        key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> MemoryItem:
        """Store a durable long-term knowledge item."""
        item = MemoryItem(
            key=key,
            content=content,
            category="knowledge",
            metadata=metadata or {},
            confidence=confidence,
        )
        return self.store.insert(item)

    def recall_fact(self, key_or_id: str) -> MemoryItem | None:
        """Recall a durable long-term knowledge item by key or ID."""
        return self.store.get_by_key(key_or_id) or self.store.get_by_id(key_or_id)

    def search_knowledge(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Search durable long-term knowledge items."""
        return self.store.search(query, category="knowledge", limit=limit)

    def list_knowledge(self, limit: int = 50) -> list[MemoryItem]:
        """List durable long-term knowledge items."""
        return self.store.list_all(category="knowledge", limit=limit)
