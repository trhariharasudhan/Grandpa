"""Memory Retrieval and Relevance Engine for Grandpa Memory System V1."""

from __future__ import annotations

import time

from grandpa.memory.models import MemoryItem, redact_sensitive
from grandpa.memory.store import MemoryStore


class MemoryRetrievalEngine:
    """Engine for querying, filtering, ranking, and formatting memory context."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def retrieve(
        self,
        query: str = "",
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Retrieve memory items matching query and optional category/project filters."""
        if not query.strip():
            items = self.store.list_all(category=category, project_name=project_name, limit=limit)
        else:
            items = self.store.search(query, category=category, project_name=project_name, limit=limit * 2)

        return self.rank_memories(items, query=query)[:limit]

    def rank_memories(self, items: list[MemoryItem], query: str = "") -> list[MemoryItem]:
        """Rank memory items based on recency, frequency of access, confidence, and keyword match."""
        now = time.time()
        qterms = [t.lower() for t in query.split() if len(t) > 2]

        def _score(item: MemoryItem) -> float:
            score = 0.0
            # Recency decay (half-life ~7 days = 604800s)
            age = max(0.0, now - item.updated_at)
            recency_score = 1.0 / (1.0 + (age / 86400.0))
            score += recency_score * 3.0

            # Access frequency
            score += min(2.0, item.access_count * 0.2)

            # Confidence multiplier
            score *= item.confidence

            # Keyword match boost
            if qterms:
                clower = item.content.lower()
                klower = item.key.lower()
                matches = sum(1 for qt in qterms if qt in clower or qt in klower)
                score += matches * 2.0

            return score

        return sorted(items, key=_score, reverse=True)

    def get_context_summary(
        self,
        query: str = "",
        category: str | None = None,
        project_name: str | None = None,
        max_words: int = 300,
    ) -> str:
        """Format relevant memory items into a clean, bounded text snippet for context injection."""
        items = self.retrieve(query=query, category=category, project_name=project_name, limit=5)
        if not items:
            return ""

        lines = ["[MEMORY CONTEXT]"]
        total_words = 0
        for item in items:
            clean_content = redact_sensitive(item.content)
            line = f"- ({item.category.upper()}) {item.key}: {clean_content}"
            words = len(line.split())
            if total_words + words > max_words:
                break
            lines.append(line)
            total_words += words

        return "\n".join(lines) if len(lines) > 1 else ""
