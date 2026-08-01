"""User Preference Memory management for Grandpa."""

from __future__ import annotations

from typing import Any

from grandpa.memory.models import MemoryItem
from grandpa.memory.store import MemoryStore


class PreferenceMemory:
    """User preference manager backed by MemoryStore."""

    DEFAULT_PREFERENCES = {
        "preferred_shell": "pwsh",
        "response_language": "English",
        "default_browser": "Chrome",
        "preferred_microphone": "default",
    }

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def get_preference(self, key: str, default: str | None = None) -> str | None:
        """Get a preference value by key."""
        pref_key = f"pref_{key.lower()}" if not key.startswith("pref_") else key.lower()
        item = self.store.get_by_key(pref_key)
        if item:
            return item.content
        raw_key = key.replace("pref_", "").lower()
        return self.DEFAULT_PREFERENCES.get(raw_key, default)

    def set_preference(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> MemoryItem:
        """Set or update a user preference."""
        raw_key = key.replace("pref_", "").lower()
        pref_key = f"pref_{raw_key}"
        item = MemoryItem(
            key=pref_key,
            content=value,
            category="preference",
            metadata={"pref_name": raw_key, **(metadata or {})},
        )
        return self.store.insert(item)

    def list_all_preferences(self) -> dict[str, str]:
        """List all current preferences merging defaults with stored preferences."""
        prefs = dict(self.DEFAULT_PREFERENCES)
        stored = self.store.list_all(category="preference", limit=100)
        for item in stored:
            name = item.metadata.get("pref_name") or item.key.replace("pref_", "")
            prefs[name] = item.content
        return prefs

    def delete_preference(self, key: str) -> bool:
        """Delete a custom preference entry."""
        pref_key = f"pref_{key.lower()}" if not key.startswith("pref_") else key.lower()
        return self.store.delete(pref_key)
