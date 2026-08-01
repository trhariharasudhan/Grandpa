"""Unified Memory Service facade for Grandpa Memory System V1."""

from __future__ import annotations

import re
from typing import Any

from grandpa.memory.intent import MemoryIntentResult, MemoryIntentRouter
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
        self.intent_router = MemoryIntentRouter()
        self._session_enabled_flags: dict[str, bool] = {}

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

    def session_memory_enabled(self, session_id: str | None = None) -> bool:
        """Return whether memory retrieval is enabled for the specified session (default True)."""
        sid = session_id or "default"
        if sid in self._session_enabled_flags:
            return self._session_enabled_flags[sid]
        pref_key = f"session_memory_enabled_{sid}"
        try:
            val = self.preferences.get_preference(pref_key)
            if val is not None:
                enabled = val.lower() == "true"
                self._session_enabled_flags[sid] = enabled
                return enabled
        except Exception:
            pass
        return True

    def set_session_memory_enabled(self, enabled: bool, session_id: str | None = None) -> None:
        """Enable or disable memory retrieval for a specific session."""
        sid = session_id or "default"
        self._session_enabled_flags[sid] = enabled
        pref_key = f"session_memory_enabled_{sid}"
        try:
            self.preferences.set_preference(pref_key, "true" if enabled else "false")
        except Exception:
            pass

    def parse_and_route_intent(
        self,
        user_text: str,
        project_name: str | None = None,
        session_id: str | None = None,
    ) -> MemoryIntentResult | None:
        """Parse user input deterministically and resolve memory intent."""
        return self.intent_router.parse(user_text, current_project=project_name)

    def retrieve_relevant(
        self,
        query: str = "",
        project_name: str | None = None,
        session_id: str | None = None,
        category: str | None = None,
        limit: int = 5,
        max_chars: int = 1500,
    ) -> list[MemoryItem]:
        """Retrieve bounded, relevance-ranked memory items if session memory is enabled."""
        if not self.session_memory_enabled(session_id):
            return []
        return self.retrieval.retrieve_relevant(
            query=query,
            project_name=project_name,
            category=category,
            limit=limit,
            max_chars=max_chars,
        )

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

    def remember_explicit(
        self,
        text: str,
        category: MemoryCategory = "knowledge",
        key: str | None = None,
        project_name: str | None = None,
    ) -> MemoryItem:
        """Store explicit user memory instruction."""
        return self.remember(content=text, category=category, key=key, project_name=project_name)

    def remember_preference(self, key: str, value: str) -> MemoryItem:
        """Store user preference."""
        return self.preferences.set_preference(key, value)

    def remember_project_result(
        self,
        project_name: str,
        goal: str,
        status: str,
        latest_feature: str | None = None,
        latest_commit: str | None = None,
        next_task: str | None = None,
        last_failed_plan: str | None = None,
        project_path: str | None = None,
    ) -> MemoryItem:
        """Store verified structured outcome for a project."""
        content = f"Project {project_name}: Goal '{goal}' status={status}."
        if latest_feature:
            content += f" Latest feature: {latest_feature}."
        if latest_commit:
            content += f" Latest commit: {latest_commit}."
        if next_task:
            content += f" Next task: {next_task}."
        if last_failed_plan:
            content += f" Last failed plan: {last_failed_plan}."

        meta = {
            "project_name": project_name,
            "goal": goal,
            "status": status,
            "latest_feature": latest_feature,
            "latest_commit": latest_commit,
            "next_task": next_task,
            "last_failed_plan": last_failed_plan,
            "project_path": project_path or "D:\\Grandpa",
        }

        # Key for project summary
        key = f"proj_{project_name.lower()}_summary"
        return self.remember(
            content=content,
            category="project",
            key=key,
            project_name=project_name,
            metadata=meta,
        )

    def recall(self, key_or_id: str) -> MemoryItem | None:
        """Recall a memory item by key or ID."""
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

    def forget(self, key_or_id: str) -> bool:
        """Forget (delete) a memory item by key or ID."""
        return self.delete(key_or_id, soft=True)

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



    def get_context_summary(
        self,
        query: str = "",
        category: str | None = None,
        project_name: str | None = None,
        max_words: int = 300,
        session_id: str | None = None,
    ) -> str:
        """Format relevant memory items into a clean, bounded text snippet for context injection."""
        if not self.session_memory_enabled(session_id):
            return ""
        return self.retrieval.get_context_summary(
            query=query,
            category=category,
            project_name=project_name,
            max_words=max_words,
        )

    def clear(self, category: str | None = None, confirm: bool = False) -> int:
        """Clear memory items (requires confirm=True)."""
        if not confirm:
            raise PermissionError("Confirmation (confirm=True) is required to clear memories.")
        if category == "session" or category is None:
            self.short_term.clear()
        return self.store.clear(category=category)

    def explain_retrieval(self, query: str, project_name: str | None = None) -> dict[str, Any]:
        """Return diagnostic explanation of memory matching for a query."""
        return self.retrieval.explain_retrieval(query, project_name=project_name)
