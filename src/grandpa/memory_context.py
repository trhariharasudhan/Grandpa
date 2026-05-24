"""Local personal memory and recent activity for Grandpa.

This module is intentionally small and local-first. It stores user-approved
facts and assistant activity in SQLite under the Grandpa config directory and
does not call external services.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_MEMORY_DB = DEFAULT_CONFIG_DIR / "personal_memory.db"
SENSITIVE_PATTERN = re.compile(
    r"\b(password|passcode|credential|secret|token|api\s*key|credit\s*card|"
    r"card\s*number|cvv|otp|pin|private\s*key|seed\s*phrase)\b",
    re.IGNORECASE,
)


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

    def __init__(self, db_path: Path | str = DEFAULT_MEMORY_DB) -> None:
        self.db_path = Path(db_path)
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
                "CREATE INDEX IF NOT EXISTS idx_activity_created "
                "ON activity(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_lookup "
                "ON memories(category, key)"
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

    def forget(self, query: str) -> int:
        needle = f"%{query.strip().lower()}%"
        if not query.strip() or query.strip().lower() in {"all", "everything"}:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM memories")
                return cur.rowcount
        with self._connect() as conn:
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

    def search_memories(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        candidates = self.list_memories(limit=250)
        scored: list[tuple[int, float, dict[str, Any]]] = []
        for item in candidates:
            haystack = f"{item['category']} {item['key']} {item['value']}"
            tokens = _tokens(haystack)
            overlap = len(query_tokens & tokens)
            direct = 1 if query.lower() in haystack.lower() else 0
            score = overlap + direct * 3
            if score > 0:
                scored.append((score, float(item["updated_at"]), item))
        scored.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
        return [item for _, _, item in scored[:limit]]

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

    project_questions = {
        "what is my project",
        "what is my project name",
        "what's my project",
        "what's my project name",
    }
    if lower in project_questions:
        return _recall_specific(store, "project", "project", "I do not know your project yet.")

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
    return {
        "memories": store.list_memories(limit=limit),
        "recent_activity": store.list_activity(limit=50),
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
            "preference",
            "preferred_browser",
            "I will remember: your preferred browser is {value}.",
        ),
        (
            r"^i\s+use\s+(.+)$",
            "preference",
            "uses_{value_slug}",
            "I will remember: you use {value}.",
        ),
        (
            r"^my\s+(.+?)\s+is\s+(.+)$",
            "preference",
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
    results = store.search_memories(query)
    if not results:
        message = "I do not have a matching memory yet."
        return MemoryCommandResult("handled", "memory", query, message, message)
    lines = ["Here is what I remember:"]
    for item in results[:5]:
        label = _friendly_label(item)
        lines.append(f"- {label}: {item['value']}")
    message = "\n".join(lines)
    return MemoryCommandResult("handled", "memory", query, message, "I found a few local memories.")


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


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1}


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
    "memory_summary",
    "record_activity",
    "remember_conversation",
]
