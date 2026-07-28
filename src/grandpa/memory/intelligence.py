"""Local memory intelligence for Grandpa.

The intelligence layer enriches the existing personal-memory SQLite store with
ranking, preference extraction, relationships, and topic summaries. It is
local-only and stores derived metadata beside the existing memory database.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.memory_context import SENSITIVE_PATTERN, MemoryStore

TOPIC_KEYWORDS: dict[str, set[str]] = {
    "Development": {"python", "fastapi", "code", "coding", "vscode", "vs code", "git", "api", "project"},
    "AI": {"ai", "assistant", "ollama", "model", "llm", "local ai", "grandpa"},
    "Personal": {"my", "prefer", "like", "name", "family", "friend"},
    "Devices": {"windows", "desktop", "pc", "chrome", "edge", "device"},
    "Projects": {"project", "building", "working", "grandpa", "app"},
    "Learning": {"learn", "tutorial", "course", "study", "practice"},
}

ENTITY_KEYWORDS: dict[str, set[str]] = {
    "Projects": {"grandpa", "assistant", "project", "app"},
    "Technologies": {"python", "fastapi", "ollama", "local ai", "sqlite"},
    "Devices": {"windows", "desktop", "pc", "chrome", "edge", "vs code", "vscode"},
    "People": {"hari", "user"},
}

PREFERENCE_PATTERNS = [
    (re.compile(r"\bpreferred\s+(.+?)\s+is\s+(.+)", re.I), "{subject}", "{value}"),
    (re.compile(r"\bprefer\s+(.+)", re.I), "general", "{value}"),
    (re.compile(r"\bi\s+use\s+(.+)", re.I), "tool", "{value}"),
    (re.compile(r"\bi\s+like\s+(.+)", re.I), "general", "{value}"),
    (re.compile(r"\bworks?\s+on\s+(.+)", re.I), "project", "{value}"),
]


@dataclass(frozen=True)
class EnrichedMemory:
    memory_id: int
    category: str
    key: str
    value: str
    tags: tuple[str, ...]
    importance_score: float
    relevance_score: float
    confidence: float
    created_at: float
    updated_at: float
    last_used: float | None
    use_count: int
    promoted: bool
    source: str
    topic: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "id": self.memory_id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "tags": list(self.tags),
            "importance_score": self.importance_score,
            "relevance_score": self.relevance_score,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used": self.last_used,
            "use_count": self.use_count,
            "promoted": self.promoted,
            "source": self.source,
            "topic": self.topic,
        }


class MemoryIntelligenceStore:
    """Derived metadata and preferences for the personal memory store."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()
        self.db_path = Path(self.store.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_metadata (
                    memory_id INTEGER PRIMARY KEY,
                    tags TEXT NOT NULL DEFAULT '[]',
                    importance_score REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    last_used REAL,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    promoted INTEGER NOT NULL DEFAULT 0,
                    topic TEXT NOT NULL DEFAULT 'General',
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_memory_id INTEGER,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(subject, value)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_metadata_topic ON memory_metadata(topic)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_preferences_subject ON memory_preferences(subject)")

    def sync(self) -> None:
        memories = self.store.list_memories(limit=1000)
        now = time.time()
        with self._connect() as conn:
            for item in memories:
                memory_id = int(item["id"])
                tags = _tags_for_memory(item)
                topic = _topic_for_memory(item)
                importance = score_memory_importance(item)
                confidence = _confidence_for_memory(item, importance)
                existing = conn.execute(
                    "SELECT use_count, last_used, promoted FROM memory_metadata WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()
                use_count = int(existing["use_count"]) if existing else 0
                last_used = existing["last_used"] if existing else None
                promoted = int(existing["promoted"]) if existing else int(importance >= 0.78)
                conn.execute(
                    """
                    INSERT INTO memory_metadata(
                        memory_id, tags, importance_score, confidence, last_used,
                        use_count, promoted, topic, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id)
                    DO UPDATE SET tags=excluded.tags,
                                  importance_score=excluded.importance_score,
                                  confidence=excluded.confidence,
                                  topic=excluded.topic,
                                  updated_at=excluded.updated_at
                    """,
                    (
                        memory_id,
                        json.dumps(tags),
                        importance,
                        confidence,
                        last_used,
                        use_count,
                        promoted,
                        topic,
                        now,
                    ),
                )
                pref = detect_user_preference(item)
                if pref:
                    conn.execute(
                        """
                        INSERT INTO memory_preferences(
                            subject, value, confidence, source_memory_id, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(subject, value)
                        DO UPDATE SET confidence=max(confidence, excluded.confidence),
                                      source_memory_id=excluded.source_memory_id,
                                      updated_at=excluded.updated_at
                        """,
                        (
                            pref["subject"],
                            pref["value"],
                            pref["confidence"],
                            memory_id,
                            now,
                            now,
                        ),
                    )

    def enriched_memories(self, *, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        self.sync()
        memories = self.store.list_memories(limit=1000)
        metadata = self._metadata()
        enriched: list[EnrichedMemory] = []
        for item in memories:
            meta = metadata.get(int(item["id"]), {})
            relevance = calculate_memory_relevance(item, query) if query else float(meta.get("importance_score", 0.0))
            use_boost = min(0.15, int(meta.get("use_count", 0)) * 0.03)
            enriched.append(
                EnrichedMemory(
                    memory_id=int(item["id"]),
                    category=str(item["category"]),
                    key=str(item["key"]),
                    value=str(item["value"]),
                    tags=tuple(meta.get("tags", _tags_for_memory(item))),
                    importance_score=round(float(meta.get("importance_score", score_memory_importance(item))), 4),
                    relevance_score=round(min(1.0, relevance + use_boost), 4),
                    confidence=round(float(meta.get("confidence", 0.7)), 4),
                    created_at=float(item["created_at"]),
                    updated_at=float(item["updated_at"]),
                    last_used=meta.get("last_used"),
                    use_count=int(meta.get("use_count", 0)),
                    promoted=bool(meta.get("promoted", False)),
                    source=str(item.get("source") or "chat"),
                    topic=str(meta.get("topic", _topic_for_memory(item))),
                )
            )
        enriched.sort(key=lambda item: (item.relevance_score, item.importance_score, item.updated_at), reverse=True)
        selected = enriched[: max(1, limit)]
        if query:
            self._mark_used([item.memory_id for item in selected[:5]])
        return [item.to_dict() for item in selected]

    def preferences(self) -> list[dict[str, Any]]:
        self.sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT subject, value, confidence, source_memory_id, created_at, updated_at
                FROM memory_preferences
                ORDER BY confidence DESC, updated_at DESC
                """
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def _metadata(self) -> dict[int, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, tags, importance_score, confidence, last_used,
                       use_count, promoted, topic
                FROM memory_metadata
                """
            ).fetchall()
        metadata: dict[int, dict[str, Any]] = {}
        for row in rows:
            try:
                tags = json.loads(row["tags"])
            except Exception:
                tags = []
            metadata[int(row["memory_id"])] = {
                "tags": [str(item) for item in tags if str(item)],
                "importance_score": float(row["importance_score"]),
                "confidence": float(row["confidence"]),
                "last_used": row["last_used"],
                "use_count": int(row["use_count"]),
                "promoted": bool(row["promoted"]),
                "topic": row["topic"],
            }
        return metadata

    def _mark_used(self, memory_ids: list[int]) -> None:
        if not memory_ids:
            return
        now = time.time()
        with self._connect() as conn:
            for memory_id in memory_ids:
                conn.execute(
                    """
                    UPDATE memory_metadata
                    SET last_used = ?, use_count = use_count + 1
                    WHERE memory_id = ?
                    """,
                    (now, memory_id),
                )


def score_memory_importance(memory: dict[str, Any]) -> float:
    text = _memory_text(memory)
    if _is_sensitive(text):
        return 0.0
    score = 0.25
    category = str(memory.get("category", "")).lower()
    key = str(memory.get("key", "")).lower()
    if category in {"project", "preferences", "apps_tools", "work_context"}:
        score += 0.25
    if any(term in text for term in ("prefer", "preferred", "use ", "project", "working", "grandpa")):
        score += 0.22
    if any(term in text for term in ("python", "fastapi", "vs code", "vscode", "windows", "local ai")):
        score += 0.13
    if key in {"project", "preferred_browser"} or key.startswith("uses_"):
        score += 0.1
    return round(min(1.0, score), 4)


def calculate_memory_relevance(memory: dict[str, Any], query: str) -> float:
    if not query.strip():
        return score_memory_importance(memory)
    memory_tokens = _tokens(_memory_text(memory))
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    overlap = len(memory_tokens & query_tokens) / max(1, len(query_tokens))
    topic_boost = 0.15 if _topic_for_memory(memory).lower() in query.lower() else 0.0
    category_boost = 0.12 if str(memory.get("category", "")).replace("_", " ") in query.lower() else 0.0
    semantic_boost = _semantic_category_boost(memory, query)
    importance = score_memory_importance(memory) * 0.35
    return round(min(1.0, overlap * 0.55 + topic_boost + category_boost + semantic_boost + importance), 4)


def detect_user_preference(memory: dict[str, Any] | str) -> dict[str, Any] | None:
    item = {"value": memory, "category": "", "key": ""} if isinstance(memory, str) else memory
    text = _memory_text(item)
    if _is_sensitive(text):
        return None
    category = str(item.get("category", "")).lower()
    key = str(item.get("key", "")).lower()
    value = str(item.get("value", "")).strip()
    if category == "project" or key == "project":
        return {"subject": "project", "value": value, "confidence": 0.92}
    if category == "apps_tools" or key.startswith("uses_"):
        return {"subject": "tool", "value": value, "confidence": 0.84}
    if category == "preferences":
        return {"subject": key.replace("_", " ") or "preference", "value": value, "confidence": 0.82}
    for pattern, subject_template, value_template in PREFERENCE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        subject = subject_template
        pref_value = value_template
        if "{subject}" in subject:
            subject = subject.format(subject=_clean_value(match.group(1)))
        if "{value}" in pref_value:
            pref_value = pref_value.format(value=_clean_value(match.group(match.lastindex or 1)))
        return {"subject": subject, "value": pref_value, "confidence": 0.74}
    return None


def build_relationship_graph(store: MemoryStore | None = None) -> dict[str, Any]:
    intelligence = MemoryIntelligenceStore(store)
    memories = intelligence.enriched_memories(limit=500)
    nodes: dict[str, dict[str, Any]] = {"User": {"id": "User", "type": "person", "weight": 1.0}}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for memory in memories:
        text = _memory_text(memory)
        for group, keywords in ENTITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    label = _entity_label(keyword)
                    node_type = group.lower().rstrip("s")
                    nodes[label] = {
                        "id": label,
                        "type": node_type,
                        "weight": max(nodes.get(label, {}).get("weight", 0.0), memory["importance_score"]),
                    }
                    edge = ("User", label, "remembers")
                    if edge not in seen_edges:
                        edges.append({"source": edge[0], "target": edge[1], "relation": edge[2], "weight": memory["importance_score"]})
                        seen_edges.add(edge)
    return {"nodes": list(nodes.values()), "edges": edges, "local_only": True}


def cluster_memory_topics(store: MemoryStore | None = None) -> dict[str, Any]:
    intelligence = MemoryIntelligenceStore(store)
    memories = intelligence.enriched_memories(limit=500)
    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        topics[str(memory["topic"])].append(memory)
    return {
        "topics": [
            {
                "name": name,
                "count": len(items),
                "average_importance": round(sum(float(item["importance_score"]) for item in items) / max(1, len(items)), 4),
                "top_memories": items[:5],
            }
            for name, items in sorted(topics.items(), key=lambda pair: len(pair[1]), reverse=True)
        ],
        "local_only": True,
    }


def summarize_memory_profile(store: MemoryStore | None = None) -> dict[str, Any]:
    intelligence = MemoryIntelligenceStore(store)
    memories = intelligence.enriched_memories(limit=500)
    preferences = intelligence.preferences()
    topics = cluster_memory_topics(store)["topics"]
    promoted = [item for item in memories if item["promoted"]]
    return {
        "status": "ready",
        "memory_count": len(memories),
        "preference_count": len(preferences),
        "top_preferences": preferences[:8],
        "top_memories": memories[:8],
        "promoted_memories": promoted[:8],
        "topics": topics,
        "local_only": True,
        "summary": _profile_summary(memories, preferences, topics),
    }


def promote_long_term_memory(memory_id: int, *, store: MemoryStore | None = None) -> dict[str, Any]:
    intelligence = MemoryIntelligenceStore(store)
    intelligence.sync()
    with intelligence._connect() as conn:
        row = conn.execute("SELECT memory_id FROM memory_metadata WHERE memory_id = ?", (memory_id,)).fetchone()
        if not row:
            return {"ok": False, "message": "Memory not found.", "memory_id": memory_id}
        conn.execute(
            "UPDATE memory_metadata SET promoted = 1, updated_at = ? WHERE memory_id = ?",
            (time.time(), memory_id),
        )
    return {"ok": True, "message": "Memory promoted.", "memory_id": memory_id}


def ranked_memory_context(query: str, *, limit: int = 5, store: MemoryStore | None = None) -> dict[str, Any]:
    intelligence = MemoryIntelligenceStore(store)
    memories = intelligence.enriched_memories(query=query, limit=limit)
    return {
        "available": True,
        "query": query,
        "matches": memories,
        "confidence": round(memories[0]["relevance_score"], 4) if memories else 0.0,
        "local_only": True,
    }


def memory_insights(store: MemoryStore | None = None) -> dict[str, Any]:
    profile = summarize_memory_profile(store)
    relationships = build_relationship_graph(store)
    topics = cluster_memory_topics(store)
    return {
        "status": "ready",
        "profile": profile,
        "relationships": relationships,
        "topics": topics["topics"],
        "recommendations": _recommendations(profile),
        "safety": {
            "local_only": True,
            "password_learning": False,
            "browser_history_collection": False,
            "credential_storage": False,
        },
    }


def _tags_for_memory(memory: dict[str, Any]) -> list[str]:
    text = _memory_text(memory)
    tags = set()
    category = str(memory.get("category", "")).replace("_", "-")
    if category:
        tags.add(category)
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            tags.add(topic.lower())
    if "vs code" in text or "vscode" in text:
        tags.add("vs-code")
    if "grandpa" in text:
        tags.add("grandpa")
    return sorted(tags)


def _topic_for_memory(memory: dict[str, Any]) -> str:
    text = _memory_text(memory)
    scores = {
        topic: sum(1 for keyword in keywords if keyword in text)
        for topic, keywords in TOPIC_KEYWORDS.items()
    }
    topic, score = max(scores.items(), key=lambda pair: pair[1])
    return topic if score else "General"


def _confidence_for_memory(memory: dict[str, Any], importance: float) -> float:
    if _is_sensitive(_memory_text(memory)):
        return 0.0
    value = str(memory.get("value", "")).strip()
    if len(value) < 3:
        return 0.35
    return round(min(0.98, 0.55 + importance * 0.38), 4)


def _profile_summary(memories: list[dict[str, Any]], preferences: list[dict[str, Any]], topics: list[dict[str, Any]]) -> str:
    if not memories:
        return "Grandpa has no personal memories yet."
    topic_names = ", ".join(item["name"] for item in topics[:3]) or "general context"
    pref_text = ", ".join(f"{item['subject']}: {item['value']}" for item in preferences[:3]) or "no clear preferences yet"
    return f"Grandpa has {len(memories)} local memories. Strong topics: {topic_names}. Preferences: {pref_text}."


def _recommendations(profile: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if profile.get("memory_count", 0) == 0:
        recommendations.append('Teach Grandpa with commands like "remember my project is Grandpa".')
    if profile.get("preference_count", 0) == 0:
        recommendations.append("Add preferences such as preferred editor, browser, and coding tools.")
    if not profile.get("promoted_memories"):
        recommendations.append("Important memories will be promoted automatically as they become useful.")
    return recommendations


def _memory_text(memory: dict[str, Any]) -> str:
    return " ".join(
        str(memory.get(part, ""))
        for part in ("category", "key", "value", "topic")
    ).lower()


def _tokens(text: str) -> set[str]:
    aliases = {
        "vscode": "vs code",
        "fastapi": "fastapi",
        "grandpa": "grandpa",
    }
    clean = text.lower().replace("_", " ")
    tokens = {token for token in re.findall(r"[a-z0-9]+", clean) if len(token) > 1}
    for key, value in aliases.items():
        if key in clean:
            tokens.update(value.split())
    return tokens


def _semantic_category_boost(memory: dict[str, Any], query: str) -> float:
    text = _memory_text(memory)
    query_tokens = _tokens(query)
    category = str(memory.get("category", "")).lower()
    if category == "project" and (
        query_tokens & {"assistant", "building", "project", "app"}
        or "ai assistant" in query.lower()
    ):
        return 0.24
    if category == "apps_tools" and (
        query_tokens & {"editor", "coding", "code", "tool", "prefer"}
        or "vs code" in text
        or "vscode" in text
    ):
        return 0.24
    if category == "preferences" and query_tokens & {"prefer", "preferred", "preference"}:
        return 0.18
    return 0.0


def _is_sensitive(text: str) -> bool:
    return bool(SENSITIVE_PATTERN.search(text))


def _clean_value(text: str) -> str:
    return re.sub(r"[.?!]+$", "", text.strip())


def _entity_label(keyword: str) -> str:
    mapping = {"vscode": "VS Code", "vs code": "VS Code", "fastapi": "FastAPI", "grandpa": "Grandpa"}
    return mapping.get(keyword, keyword.title())
