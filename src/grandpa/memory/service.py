"""Unified Memory Service facade for Grandpa Memory System V1."""

from __future__ import annotations

import re
from typing import Any

from grandpa.memory.long_term import LongTermMemory
from grandpa.memory.models import MemoryCategory, MemoryItem
from grandpa.memory.preferences import PreferenceMemory
from grandpa.memory.project_memory import ProjectMemory
from grandpa.memory.retrieval import MemoryRetrievalEngine
from grandpa.memory.short_term import ShortTermMemory
from grandpa.memory.store import MemoryStore

_instance: MemoryService | None = None


class MemoryService:
    """High-level service facade providing unified access to Grandpa Memory System V1."""

    def __init__(self, db_path: str | None = None) -> None:
        self.store = MemoryStore(db_path=db_path)
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory(store=self.store)
        self.preferences = PreferenceMemory(store=self.store)
        self.projects = ProjectMemory(store=self.store)
        self.retrieval = MemoryRetrievalEngine(store=self.store)

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> MemoryService:
        """Return singleton instance of MemoryService."""
        global _instance
        if _instance is None or db_path is not None:
            _instance = cls(db_path=db_path)
        return _instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (used in tests)."""
        global _instance
        _instance = None

    def remember(
        self,
        content: str,
        category: MemoryCategory = "knowledge",
        key: str | None = None,
        project_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        confidence: float = 1.0,
        expires_at: float | None = None,
    ) -> MemoryItem:
        """Store a new memory item."""
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty.")

        # Auto-generate key if not provided
        if not key:
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", content.strip().lower()[:40]).strip("_")
            key = slug or f"mem_{int(confidence * 1000)}"

        if category == "session":
            return self.short_term.add(content, key=key, metadata=metadata)

        item = MemoryItem(
            key=key,
            content=content,
            category=category,
            project_name=project_name,
            metadata=metadata or {},
            confidence=confidence,
            expires_at=expires_at,
        )
        return self.store.insert(item)

    def recall(self, key_or_id: str) -> MemoryItem | None:
        """Recall a memory item by key or ID."""
        # Check short term first
        for s_item in self.short_term.get_session_memories():
            if s_item.key == key_or_id or s_item.id == key_or_id:
                return s_item

        return self.store.get_by_key(key_or_id) or self.store.get_by_id(key_or_id)

    def search(
        self,
        query: str,
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search memories by query string."""
        return self.retrieval.retrieve(
            query=query,
            category=category,
            project_name=project_name,
            limit=limit,
        )

    def update(
        self,
        key_or_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> MemoryItem | None:
        """Update an existing memory item."""
        return self.store.update(
            item_id_or_key=key_or_id,
            content=content,
            metadata=metadata,
            category=category,
        )

    def delete(self, key_or_id: str, soft: bool = True) -> bool:
        """Delete a memory item."""
        return self.store.delete(item_id_or_key=key_or_id, soft=soft)

    def list_memories(
        self,
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """List memory items."""
        return self.store.list_all(category=category, project_name=project_name, limit=limit)

    def clear(self, category: str | None = None, confirm: bool = False) -> int:
        """Clear memory items (requires confirm=True)."""
        if not confirm:
            raise PermissionError("Confirmation (confirm=True) is required to clear memories.")
        if category == "session" or category is None:
            self.short_term.clear()
        return self.store.clear(category=category)
