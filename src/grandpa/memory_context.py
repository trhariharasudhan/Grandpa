"""Local personal memory and recent activity for Grandpa.

This module is intentionally small and local-first. It stores user-approved
facts and assistant activity in SQLite under the Grandpa config directory and
does not call external services.
"""

from __future__ import annotations

import re
import sqlite3
import time
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_MEMORY_DB = DEFAULT_CONFIG_DIR / "personal_memory.db"
SEMANTIC_DIMENSIONS = 128
SEMANTIC_MODEL = "grandpa-local-semantic-v1"
SEMANTIC_MIN_CONFIDENCE = 0.18
SENSITIVE_PATTERN = re.compile(
    r"\b(password|passcode|credential|secret|token|api\s*key|credit\s*card|"
    r"card\s*number|cvv|otp|pin|private\s*key|seed\s*phrase)\b",
    re.IGNORECASE,
)

MEMORY_CATEGORY_ALIASES: dict[str, set[str]] = {
    "project": {"project", "assistant", "ai", "app", "building", "working", "work"},
    "preferences": {"prefer", "preferred", "preference", "like", "default"},
    "apps_tools": {"app", "apps", "tool", "tools", "editor", "coding", "code", "vscode", "browser"},
    "routines": {"routine", "routines", "reminder", "reminders", "schedule"},
    "people": {"person", "people", "friend", "family", "team", "client"},
    "work_context": {"work", "task", "context", "recent", "lately"},
    "note": {"note", "memory", "remembered", "fact"},
}

TOKEN_ALIASES: dict[str, set[str]] = {
    "ai": {"assistant", "project", "app"},
    "assistant": {"ai", "project", "app", "grandpa"},
    "app": {"application", "project", "assistant", "tool"},
    "building": {"project", "working", "creating"},
    "coding": {"code", "editor", "tool", "vscode"},
    "code": {"coding", "editor", "vscode", "vs"},
    "editor": {"coding", "code", "vscode", "tool"},
    "prefer": {"preferred", "preference", "use"},
    "preferred": {"prefer", "preference", "use"},
    "project": {"assistant", "building", "work"},
    "tool": {"app", "editor", "coding"},
    "use": {"uses", "prefer", "tool"},
    "uses": {"use", "prefer", "tool"},
    "vscode": {"vs", "code", "editor", "coding"},
    "vs": {"vscode", "code", "editor"},
    "work": {"project", "lately", "context"},
    "working": {"project", "building", "lately"},
}


@dataclass(frozen=True)
class MemoryCommandResult:
    status: str
    kind: str
    target: str | None
    message: str
    tts_text: str | None = None
    should_fallback: bool = False


class MemoryStore:
    """SQLite-backed personal memory store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or os.getenv("GRANDPA_PERSONAL_MEMORY_DB") or DEFAULT_MEMORY_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'chat',
                    UNIQUE(category, key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT,
                    detail TEXT,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id INTEGER PRIMARY KEY,
                    updated_at REAL NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    embedding TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_created "
                "ON activity(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_lookup "
                "ON memories(category, key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embedding_model "
                "ON memory_embeddings(model)"
            )

    def remember(
        self,
        category: str,
        key: str,
        value: str,
        *,
        source: str = "chat",
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(created_at, updated_at, category, key, value, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, key)
                DO UPDATE SET updated_at=excluded.updated_at,
                              value=excluded.value,
                              source=excluded.source
                """,
                (now, now, category, key, value, source),
            )
            row = conn.execute(
                "SELECT id, updated_at FROM memories WHERE category = ? AND key = ?",
                (category, key),
            ).fetchone()
            if row:
                item = {
                    "id": row["id"],
                    "updated_at": row["updated_at"],
                    "category": category,
                    "key": key,
                    "value": value,
                    "source": source,
                }
                self._store_embedding(conn, item)

    def forget(self, query: str) -> int:
        needle = f"%{query.strip().lower()}%"
        if not query.strip() or query.strip().lower() in {"all", "everything"}:
            with self._connect() as conn:
                conn.execute("DELETE FROM memory_embeddings")
                cur = conn.execute("DELETE FROM memories")
                return cur.rowcount
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id FROM memories
                WHERE lower(category) LIKE ?
                   OR lower(key) LIKE ?
                   OR lower(value) LIKE ?
                """,
                (needle, needle, needle),
            ).fetchall()
            memory_ids = [row["id"] for row in rows]
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                conn.execute(
                    f"DELETE FROM memory_embeddings WHERE memory_id IN ({placeholders})",
                    memory_ids,
                )
            cur = conn.execute(
                """
                DELETE FROM memories
                WHERE lower(category) LIKE ?
                   OR lower(key) LIKE ?
                   OR lower(value) LIKE ?
                """,
                (needle, needle, needle),
            )
            return cur.rowcount

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_embeddings")
            conn.execute("DELETE FROM memories")
            conn.execute("DELETE FROM activity")

    def list_memories(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, updated_at, category, key, value, source
                FROM memories
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def search_memories(
        self,
        query: str,
        limit: int = 8,
        *,
        category: str | None = None,
        min_confidence: float = SEMANTIC_MIN_CONFIDENCE,
    ) -> list[dict[str, Any]]:
        query_tokens = _expanded_tokens(query)
        candidates = self.list_memories(limit=250)
        if category and category != "all":
            candidates = [item for item in candidates if item["category"] == category]
        self._ensure_embeddings(candidates)
        query_embedding = _embed_text(query)
        scored: list[tuple[float, float, dict[str, Any]]] = []
        for item in candidates:
            haystack = f"{item['category']} {item['key']} {item['value']}"
            tokens = _expanded_tokens(haystack)
            overlap = len(query_tokens & tokens)
            direct = 1 if query.lower() in haystack.lower() else 0
            inferred_categories = _infer_query_categories(query)
            category_hint = 1 if item["category"] in inferred_categories else 0
            semantic = self._embedding_similarity(int(item["id"]), query_embedding)
            lexical = min(1.0, overlap / max(1, len(query_tokens)))
            confidence = max(semantic, lexical * 0.72, direct * 0.95)
            confidence = min(1.0, confidence + category_hint * 0.12)
            if inferred_categories and not category_hint and not direct:
                confidence *= 0.45
            try:
                from grandpa.core_ai_brain import BrainStore

                confidence = min(1.0, confidence + BrainStore().habit_score(haystack))
            except Exception:
                pass
            if confidence >= min_confidence or direct or overlap >= 2:
                enriched = dict(item)
                enriched["score"] = round(confidence, 4)
                enriched["relevance_score"] = round(confidence, 4)
                enriched["match_type"] = "semantic" if semantic >= lexical else "keyword"
                enriched["embedding_model"] = SEMANTIC_MODEL
                scored.append((confidence, float(item["updated_at"]), enriched))
        scored.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
        return [item for _, _, item in scored[:limit]]

    def semantic_status(self) -> dict[str, Any]:
        with self._connect() as conn:
            memories = conn.execute("SELECT COUNT(*) AS count FROM memories").fetchone()["count"]
            embeddings = conn.execute("SELECT COUNT(*) AS count FROM memory_embeddings").fetchone()["count"]
        return {
            "enabled": True,
            "backend": "local-sqlite",
            "embedding_model": SEMANTIC_MODEL,
            "dimensions": SEMANTIC_DIMENSIONS,
            "memories": memories,
            "embeddings": embeddings,
            "local_only": True,
        }

    def record_activity(
        self,
        category: str,
        action: str,
        target: str | None,
        detail: str | None,
        status: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity(created_at, category, action, target, detail, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (time.time(), category, action, target, detail, status),
            )

    def list_activity(
        self,
        *,
        limit: int = 50,
        since: float | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, created_at, category, action, target, detail, status
                FROM activity
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def _store_embedding(self, conn: sqlite3.Connection, item: dict[str, Any]) -> None:
        text = _memory_embedding_text(item)
        embedding = _embed_text(text)
        conn.execute(
            """
            INSERT INTO memory_embeddings(
                memory_id, updated_at, model, dimensions, embedding, text, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id)
            DO UPDATE SET updated_at=excluded.updated_at,
                          model=excluded.model,
                          dimensions=excluded.dimensions,
                          embedding=excluded.embedding,
                          text=excluded.text,
                          metadata=excluded.metadata
            """,
            (
                item["id"],
                item["updated_at"],
                SEMANTIC_MODEL,
                SEMANTIC_DIMENSIONS,
                _serialize_vector(embedding),
                text,
                '{"source":"local"}',
            ),
        )

    def _ensure_embeddings(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        ids = [int(item["id"]) for item in items]
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT memory_id, updated_at, model FROM memory_embeddings "
                f"WHERE memory_id IN ({placeholders})",
                ids,
            ).fetchall()
            current = {
                int(row["memory_id"]): (float(row["updated_at"]), str(row["model"]))
                for row in rows
            }
            for item in items:
                memory_id = int(item["id"])
                stored = current.get(memory_id)
                if stored == (float(item["updated_at"]), SEMANTIC_MODEL):
                    continue
                self._store_embedding(conn, item)

    def _embedding_similarity(self, memory_id: int, query_embedding: list[float]) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT embedding FROM memory_embeddings WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if not row:
            return 0.0
        try:
            embedding = _deserialize_vector(row["embedding"])
        except ValueError:
            return 0.0
        return _cosine_similarity(query_embedding, embedding)


def handle_memory_command(text: str, *, store: MemoryStore | None = None) -> MemoryCommandResult:
    """Handle explicit memory commands, returning fallback when not matched."""

    original = text.strip()
    if not original:
        return _fallback()
    store = store or MemoryStore()
    lower = original.lower().strip(" ?!.")

    remember_match = re.match(r"^(please\s+)?remember\s+(?:that\s+)?(.+)$", original, re.I)
    if remember_match:
        fact = remember_match.group(2).strip()
        return _remember_fact(store, fact)

    forget_match = re.match(r"^(please\s+)?forget\s+(?:that\s+)?(.+)$", original, re.I)
    if forget_match:
        target = forget_match.group(2).strip()
        removed = store.forget(target)
        message = (
            f"I forgot {removed} matching memory item{'s' if removed != 1 else ''}."
            if removed
            else "I did not find a matching memory to forget."
        )
        return MemoryCommandResult("handled", "memory", target, message, message)

    if lower in {"clear memory", "clear my memory", "delete memory", "delete my memory"}:
        store.clear_all()
        message = "I cleared Grandpa's local personal memory and recent activity."
        return MemoryCommandResult("handled", "memory", "clear", message, message)

    if lower.startswith("what do you remember"):
        query = re.sub(r"^what do you remember\s*(about|for)?\s*", "", lower).strip()
        return _recall(store, query or original)

    if lower in {
        "what do you know about me",
        "what do you know about me so far",
        "summarize my memory",
        "summarise my memory",
    }:
        return _profile_recall(store)

    if lower in {
        "summarize my preferences",
        "summarise my preferences",
        "what are my preferences",
        "what do i prefer",
    }:
        return _preference_recall(store)

    if lower in {
        "what projects am i working on",
        "what project am i working on",
        "what am i working on",
    }:
        return _project_recall(store)

    project_questions = {
        "what is my project",
        "what is my project name",
        "what's my project",
        "what's my project name",
    }
    if lower in project_questions:
        return _recall_specific(store, "project", "project", "I do not know your project yet.")

    if "project" in lower and (
        re.search(r"[\u0B80-\u0BFF]", original)
        or any(word in lower for word in {"enna", "yenna", "my", "namma"})
    ):
        return _recall_specific(store, "project", "project", "I do not know your project yet.")

    if _looks_like_memory_recall(original):
        return _recall(store, original)

    if lower.startswith("what apps did i open"):
        return _apps_opened_today(store)

    if lower.startswith("what did i do earlier") or lower.startswith("what was i doing"):
        return _recent_activity(store)

    continue_match = re.match(r"^continue\s+my\s+(.+?)\s+project\.?$", original, re.I)
    if continue_match:
        topic = continue_match.group(1).strip()
        return _continue_project(store, topic)

    return _fallback()


def remember_conversation(role: str, content: str) -> None:
    """Record lightweight conversation activity without storing sensitive text."""

    if not content.strip() or _looks_sensitive(content):
        return
    snippet = content.strip()[:500]
    try:
        MemoryStore().record_activity(
            "conversation",
            role,
            None,
            snippet,
            "recorded",
        )
    except Exception:
        return


def record_activity(
    category: str,
    action: str,
    target: str | None,
    detail: str | None,
    status: str,
) -> None:
    """Best-effort activity logger for local actions."""

    if detail and _looks_sensitive(detail):
        detail = "[redacted sensitive detail]"
    try:
        MemoryStore().record_activity(category, action, target, detail, status)
    except Exception:
        return


def memory_summary(limit: int = 100) -> dict[str, Any]:
    store = MemoryStore()
    memories = store.list_memories(limit=limit)
    try:
        from grandpa.memory.intelligence import summarize_memory_profile

        intelligence = summarize_memory_profile(store)
    except Exception:
        intelligence = {"status": "unavailable", "local_only": True}
    return {
        "memories": memories,
        "recent_activity": store.list_activity(limit=50),
        "categories": sorted({str(item["category"]) for item in memories}),
        "intelligence": intelligence,
        "semantic": store.semantic_status(),
        "storage": {
            "backend": "sqlite",
            "path": str(store.db_path),
            "local_only": True,
        },
    }


def clear_memory() -> dict[str, Any]:
    store = MemoryStore()
    store.clear_all()
    return {"status": "ok", "message": "Personal memory cleared"}


def search_personal_memory(
    query: str,
    *,
    category: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    store = MemoryStore()
    results = store.search_memories(query, limit=limit, category=category)
    uncertain = not results or float(results[0].get("score", 0.0)) < SEMANTIC_MIN_CONFIDENCE
    return {
        "query": query,
        "category": category or "all",
        "results": results,
        "uncertain": uncertain,
        "semantic": store.semantic_status(),
    }


def memory_profile() -> dict[str, Any]:
    from grandpa.memory.intelligence import summarize_memory_profile

    return summarize_memory_profile(MemoryStore())


def memory_preferences() -> dict[str, Any]:
    from grandpa.memory.intelligence import MemoryIntelligenceStore

    prefs = MemoryIntelligenceStore(MemoryStore()).preferences()
    return {"status": "ready", "preferences": prefs, "count": len(prefs), "local_only": True}


def memory_relationships() -> dict[str, Any]:
    from grandpa.memory.intelligence import build_relationship_graph

    return build_relationship_graph(MemoryStore())


def memory_topics() -> dict[str, Any]:
    from grandpa.memory.intelligence import cluster_memory_topics

    return cluster_memory_topics(MemoryStore())


def memory_insight_summary() -> dict[str, Any]:
    from grandpa.memory.intelligence import memory_insights

    return memory_insights(MemoryStore())


def _remember_fact(store: MemoryStore, fact: str) -> MemoryCommandResult:
    if _looks_sensitive(fact):
        message = "I blocked this memory for privacy."
        return MemoryCommandResult("blocked", "memory", "sensitive", message, message)

    parsed = _parse_fact(fact)
    store.remember(parsed["category"], parsed["key"], parsed["value"])
    message = parsed["message"]
    return MemoryCommandResult("handled", "memory", parsed["key"], message, message)


def _parse_fact(fact: str) -> dict[str, str]:
    cleaned = fact.strip().strip(".")
    lower = cleaned.lower()

    patterns = [
        (
            r"^my\s+project(?:\s+name)?\s+is\s+(.+)$",
            "project",
            "project",
            "I will remember: your project is {value}.",
        ),
        (
            r"^my\s+preferred\s+browser\s+is\s+(.+)$",
            "preferences",
            "preferred_browser",
            "I will remember: your preferred browser is {value}.",
        ),
        (
            r"^i\s+use\s+(.+)$",
            "apps_tools",
            "uses_{value_slug}",
            "I will remember: you use {value}.",
        ),
        (
            r"^my\s+(.+?)\s+is\s+(.+)$",
            "preferences",
            None,
            "I will remember: your {key} is {value}.",
        ),
    ]
    for pattern, category, key, template in patterns:
        match = re.match(pattern, cleaned, re.I)
        if match:
            if key is None:
                raw_key = match.group(1).strip()
                value = match.group(2).strip()
                key = _slug(raw_key)
                return {
                    "category": category,
                    "key": key,
                    "value": value,
                    "message": template.format(key=raw_key, value=value),
                }
            value = match.group(1).strip()
            if "{value_slug}" in key:
                key = key.replace("{value_slug}", _slug(value) or "tool")
            return {
                "category": category,
                "key": key,
                "value": value,
                "message": template.format(value=value),
            }

    key = _slug(lower[:40]) or "note"
    return {
        "category": "note",
        "key": key,
        "value": cleaned,
        "message": f"I will remember: {cleaned}.",
    }


def _recall(store: MemoryStore, query: str) -> MemoryCommandResult:
    try:
        from grandpa.memory.intelligence import ranked_memory_context

        results = ranked_memory_context(query, limit=5, store=store).get("matches", [])
    except Exception:
        results = store.search_memories(query)
    if not results:
        message = "I do not have a matching memory yet."
        return MemoryCommandResult("handled", "memory", query, message, message)
    top_score = float(results[0].get("relevance_score", results[0].get("score", 0.0)))
    if top_score < max(SEMANTIC_MIN_CONFIDENCE, 0.35):
        message = "I am not confident I have a matching memory for that yet."
        return MemoryCommandResult("handled", "memory", query, message, message)
    lines = ["Here is what I remember:"]
    for item in results[:5]:
        label = _friendly_label(item)
        score = float(item.get("relevance_score", item.get("score", 0.0)))
        lines.append(f"- {label}: {item['value']} ({score:.0%} confidence)")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", query, message, "I found a few local memories.")


def _profile_recall(store: MemoryStore) -> MemoryCommandResult:
    try:
        from grandpa.memory.intelligence import summarize_memory_profile

        profile = summarize_memory_profile(store)
    except Exception:
        return _recall(store, "me preferences projects tools")
    summary = str(profile.get("summary") or "Grandpa has no personal memories yet.")
    top = profile.get("top_memories", [])[:4]
    lines = [summary]
    for item in top:
        lines.append(f"- {_friendly_label(item)}: {item['value']}")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", "profile", message, "I summarized your local memory profile.")


def _preference_recall(store: MemoryStore) -> MemoryCommandResult:
    from grandpa.memory.intelligence import MemoryIntelligenceStore

    prefs = MemoryIntelligenceStore(store).preferences()
    if not prefs:
        message = "I do not have clear saved preferences yet."
        return MemoryCommandResult("handled", "memory", "preferences", message, message)
    lines = ["Here are the preferences I have learned locally:"]
    for item in prefs[:6]:
        confidence = float(item.get("confidence", 0.0))
        lines.append(f"- {item['subject']}: {item['value']} ({confidence:.0%} confidence)")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", "preferences", message, "I summarized your preferences.")


def _project_recall(store: MemoryStore) -> MemoryCommandResult:
    try:
        results = store.search_memories("project working app assistant grandpa", category="project", limit=5)
        if not results:
            from grandpa.memory.intelligence import ranked_memory_context

            results = ranked_memory_context("project working app assistant grandpa", limit=5, store=store).get("matches", [])
    except Exception:
        results = store.search_memories("project working app assistant grandpa", limit=5)
    if not results:
        message = "I do not know which project you are working on yet."
        return MemoryCommandResult("handled", "memory", "projects", message, message)
    lines = ["Here is what I know about your current projects:"]
    for item in results[:5]:
        lines.append(f"- {_friendly_label(item)}: {item['value']}")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", "projects", message, "I found your saved project context.")


def _recall_specific(
    store: MemoryStore,
    category: str,
    key: str,
    empty_message: str,
) -> MemoryCommandResult:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT value FROM memories WHERE category = ? AND key = ?",
            (category, key),
        ).fetchone()
    if not row:
        return MemoryCommandResult("handled", "memory", key, empty_message, empty_message)
    message = f"Your project is {row['value']}."
    return MemoryCommandResult("handled", "memory", key, message, message)


def _apps_opened_today(store: MemoryStore) -> MemoryCommandResult:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = store.list_activity(limit=50, since=start, category="app")
    opened = [row for row in rows if row["action"] == "open"]
    if not opened:
        message = "I do not have any opened app activity for today yet."
        return MemoryCommandResult("handled", "memory", "apps_today", message, message)
    names = []
    for row in opened:
        target = row.get("target") or "unknown app"
        name = Path(str(target)).stem or str(target)
        if name not in names:
            names.append(name)
    message = "Today you opened: " + ", ".join(names[:10]) + "."
    return MemoryCommandResult("handled", "memory", "apps_today", message, message)


def _recent_activity(store: MemoryStore) -> MemoryCommandResult:
    since = (datetime.now() - timedelta(hours=24)).timestamp()
    rows = store.list_activity(limit=8, since=since)
    if not rows:
        message = "I do not have recent activity recorded yet."
        return MemoryCommandResult("handled", "memory", "recent_activity", message, message)
    lines = ["Here is your recent local activity:"]
    for row in rows[:6]:
        when = datetime.fromtimestamp(row["created_at"]).strftime("%H:%M")
        target = row.get("target") or row.get("detail") or row["category"]
        lines.append(f"- {when}: {row['action']} {target} ({row['status']})")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", "recent_activity", message, "Here is your recent activity.")


def _continue_project(store: MemoryStore, topic: str) -> MemoryCommandResult:
    results = store.search_memories(topic)
    if not results:
        message = f"I do not have saved context for your {topic} project yet."
        return MemoryCommandResult("handled", "memory", topic, message, message)
    lines = [f"I found saved context for {topic}:"]
    for item in results[:4]:
        lines.append(f"- {_friendly_label(item)}: {item['value']}")
    lines.append("Tell me what you want to do next and I will use this context.")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", topic, message, "I found saved project context.")


def _fallback() -> MemoryCommandResult:
    return MemoryCommandResult("no_match", "memory", None, "", None, True)


def _looks_sensitive(text: str) -> bool:
    return bool(SENSITIVE_PATTERN.search(text))


def _looks_like_memory_recall(text: str) -> bool:
    lower = text.lower().strip(" ?!.")
    if not re.match(r"^(what|which|who|where|when|tell me|do you know|can you remember)", lower):
        return False
    if "what apps did i open" in lower or "what windows" in lower:
        return False
    has_personal_marker = bool(
        re.search(r"\b(my|me|i)\b", lower)
        or "you remember" in lower
        or "i told you" in lower
    )
    recall_markers = {
        "assistant",
        "project",
        "building",
        "working",
        "lately",
        "coding",
        "editor",
        "prefer",
        "preferred",
        "use",
        "tool",
        "app",
        "reminder",
        "routine",
    }
    tokens = _tokens(lower)
    return has_personal_marker and bool(tokens & recall_markers)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1}


def _expanded_tokens(text: str) -> set[str]:
    tokens = _tokens(text)
    expanded = set(tokens)
    if "vs code" in text.lower() or {"vs", "code"}.issubset(tokens):
        expanded.add("vscode")
    for token in list(tokens):
        expanded.update(TOKEN_ALIASES.get(token, set()))
    for category, aliases in MEMORY_CATEGORY_ALIASES.items():
        if tokens & aliases:
            expanded.add(category)
            expanded.update(aliases)
    if "grandpa" in tokens:
        expanded.update({"assistant", "project", "app"})
    return expanded


def _infer_query_categories(query: str) -> set[str]:
    tokens = _tokens(query)
    if "vs code" in query.lower() or {"vs", "code"}.issubset(tokens):
        tokens.add("vscode")
    categories: set[str] = set()
    for category, aliases in MEMORY_CATEGORY_ALIASES.items():
        if tokens & aliases or category in tokens:
            categories.add(category)
    return categories


def _memory_embedding_text(item: dict[str, Any]) -> str:
    category = str(item.get("category", "note"))
    parts = [
        category,
        str(item.get("key", "")),
        str(item.get("value", "")),
        " ".join(sorted(MEMORY_CATEGORY_ALIASES.get(category, set()))),
    ]
    return " ".join(parts)


def _embed_text(text: str, dimensions: int = SEMANTIC_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = _expanded_tokens(text)
    for token in tokens:
        index = _stable_hash(token) % dimensions
        vector[index] += 1.0
        if len(token) > 4:
            for idx in range(len(token) - 2):
                ngram = token[idx : idx + 3]
                vector[_stable_hash(f"ng:{ngram}") % dimensions] += 0.18
    norm = sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _stable_hash(text: str) -> int:
    value = 2166136261
    for char in text:
        value ^= ord(char)
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def _serialize_vector(vector: list[float]) -> str:
    return ",".join(f"{value:.6f}" for value in vector)


def _deserialize_vector(raw: str) -> list[float]:
    values = [float(part) for part in raw.split(",") if part]
    if len(values) != SEMANTIC_DIMENSIONS:
        raise ValueError("unexpected memory embedding dimensions")
    return values


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return value[:64]


def _friendly_label(item: dict[str, Any]) -> str:
    key = str(item["key"]).replace("_", " ")
    category = str(item["category"]).replace("_", " ")
    if key == category:
        return category
    return f"{category} {key}".strip()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


__all__ = [
    "MemoryCommandResult",
    "MemoryStore",
    "clear_memory",
    "handle_memory_command",
    "memory_insight_summary",
    "memory_preferences",
    "memory_profile",
    "memory_relationships",
    "memory_summary",
    "memory_topics",
    "record_activity",
    "remember_conversation",
    "search_personal_memory",
]
