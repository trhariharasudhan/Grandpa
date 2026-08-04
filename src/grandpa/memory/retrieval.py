"""Memory Retrieval and Relevance Engine for Grandpa Memory System V1."""

from __future__ import annotations

import time
from typing import Any

from grandpa.memory.models import MemoryItem, redact_sensitive
from grandpa.memory.store import MemoryStore


class MemoryRetrievalEngine:
    """Engine for querying, filtering, ranking, and formatting memory context."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def retrieve_relevant(
        self,
        query: str = "",
        project_name: str | None = None,
        session_id: str | None = None,
        category: str | None = None,
        limit: int = 5,
        max_chars: int = 1500,
    ) -> list[MemoryItem]:
        """Retrieve bounded, relevance-ranked, sanitized memory items for context injection.

        Enforces strict bounds (max 5 items, max 1,500 total characters).
        """
        # Hard limits
        eff_limit = min(max(1, limit), 5)
        eff_max_chars = min(max(100, max_chars), 1500)

        # Retrieve candidates from store
        candidates: list[MemoryItem] = []

        if query.strip():
            candidates.extend(
                self.store.search(
                    query, category=category, project_name=project_name, limit=15
                )
            )

        # Always include project memory candidates if project_name is active
        if project_name:
            candidates.extend(
                self.store.list_all(
                    category="project", project_name=project_name, limit=5
                )
            )

        # Always include user preference candidates if query mentions preferences or shell/browser
        if any(w in query.lower() for w in ["pref", "shell", "browser", "mic", "lang"]):
            candidates.extend(self.store.list_all(category="preference", limit=5))

        # Fallback to recent knowledge items if candidates are empty and query is provided
        if not candidates and query.strip():
            candidates.extend(self.store.list_all(limit=10))

        # Deduplicate candidates by key
        seen_keys: set[str] = set()
        unique_candidates: list[MemoryItem] = []
        for c in candidates:
            if c.key not in seen_keys and not c.is_deleted:
                seen_keys.add(c.key)
                unique_candidates.append(c)

        ranked = self.rank_memories(
            unique_candidates, query=query, project_name=project_name
        )

        # Truncate by item limit and total character bound
        result: list[MemoryItem] = []
        char_count = 0
        for item in ranked:
            if len(result) >= eff_limit:
                break
            clean_text = redact_sensitive(item.content)
            item_len = len(clean_text) + len(item.key) + 20
            if char_count + item_len > eff_max_chars:
                break
            result.append(item)
            char_count += item_len

        return result

    def retrieve(
        self,
        query: str = "",
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Retrieve memory items matching query and optional category/project filters."""
        if not query.strip():
            items = self.store.list_all(
                category=category, project_name=project_name, limit=limit
            )
        else:
            items = self.store.search(
                query, category=category, project_name=project_name, limit=limit * 2
            )

        return self.rank_memories(items, query=query, project_name=project_name)[:limit]

    def rank_memories(
        self,
        items: list[MemoryItem],
        query: str = "",
        project_name: str | None = None,
    ) -> list[MemoryItem]:
        """Rank memory items based on priority order:
        1. Exact key match
        2. Current project match
        3. Explicit preference match
        4. Recent relevant task
        5. Relevant knowledge memory
        6. Session context
        """
        now = time.time()
        qterms = [t.lower() for t in query.split() if len(t) > 2]

        def _score(item: MemoryItem) -> float:
            score = 0.0

            # 1. Exact key match
            if query and item.key.lower() == query.strip().lower():
                score += 10.0

            # 2. Current project match
            if (
                project_name
                and item.project_name
                and item.project_name.lower() == project_name.lower()
            ):
                score += 8.0

            # 3. Preference match
            if item.category == "preference":
                score += 6.0

            # 4. Keyword matches
            if qterms:
                clower = item.content.lower()
                klower = item.key.lower()
                matches = sum(1 for qt in qterms if qt in clower or qt in klower)
                score += matches * 2.5

            # 5. Recency decay (half-life ~7 days)
            age = max(0.0, now - item.updated_at)
            recency = 1.0 / (1.0 + (age / 86400.0))
            score += recency * 3.0

            # 6. Access count & confidence
            score += min(2.0, item.access_count * 0.2)
            score *= item.confidence

            return score

        return sorted(items, key=_score, reverse=True)

    def explain_retrieval(
        self,
        query: str,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        """Explain why memories were matched and ranked for a query."""
        relevant = self.retrieve_relevant(
            query=query, project_name=project_name, limit=5
        )
        explanations: list[dict[str, Any]] = []

        for item in relevant:
            reasons = []
            if query and item.key.lower() == query.strip().lower():
                reasons.append("Exact key match")
            if project_name and item.project_name == project_name:
                reasons.append(f"Project scope match ({project_name})")
            if item.category == "preference":
                reasons.append("User preference match")
            if any(
                qt in item.content.lower()
                for qt in query.lower().split()
                if len(qt) > 2
            ):
                reasons.append("Keyword content match")

            explanations.append(
                {
                    "id": item.id,
                    "key": item.key,
                    "category": item.category,
                    "project": item.project_name or "N/A",
                    "reasons": reasons or ["Recent context match"],
                    "content_preview": redact_sensitive(item.content[:100]),
                }
            )

        return {
            "query": query,
            "project": project_name,
            "matched_count": len(relevant),
            "matches": explanations,
        }

    def get_context_summary(
        self,
        query: str = "",
        category: str | None = None,
        project_name: str | None = None,
        max_words: int = 300,
    ) -> str:
        """Format relevant memory items into a clean, bounded text snippet for context injection."""
        items = self.retrieve_relevant(
            query=query, project_name=project_name, category=category, limit=5
        )
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
