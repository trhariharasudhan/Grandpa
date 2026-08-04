"""SQLite storage implementation for Grandpa Memory System V1."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.memory.models import MemoryItem, is_sensitive_content
from grandpa.memory_recovery import recover_sqlite_database, validate_sqlite_connection

DEFAULT_MEMORY_DB = DEFAULT_CONFIG_DIR / "memory.db"
CURRENT_SCHEMA_VERSION = 1


class MemoryStore:
    """SQLite-backed persistent memory store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        raw_path = db_path or os.environ.get("GRANDPA_MEMORY_DB") or DEFAULT_MEMORY_DB
        self.db_path = Path(raw_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._init_db()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._closed:
            raise RuntimeError("MemoryStore is closed")
        conn: sqlite3.Connection | None = None
        try:
            conn = self._open_connection()
            validate_sqlite_connection(conn)
        except sqlite3.DatabaseError:
            if conn is not None:
                conn.close()
            recover_sqlite_database(self.db_path)
            self._create_schema()
            conn = self._open_connection()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        if self._has_invalid_header():
            recover_sqlite_database(self.db_path)
        try:
            self._create_schema()
        except sqlite3.DatabaseError:
            recover_sqlite_database(self.db_path)
            self._create_schema()

    def _has_invalid_header(self) -> bool:
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return False
        with self.db_path.open("rb") as handle:
            return handle.read(16) != b"SQLite format 3\x00"

    def _create_schema(self) -> None:
        conn = self._open_connection()
        try:
            validate_sqlite_connection(conn)
            # Schema versioning table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)",
                    (CURRENT_SCHEMA_VERSION,),
                )

            # Memories main table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    project_name TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    source TEXT DEFAULT 'user',
                    confidence REAL DEFAULT 1.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL,
                    access_count INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_name)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")
            conn.commit()
        finally:
            conn.close()

    def insert(self, item: MemoryItem, allow_sensitive: bool = False) -> MemoryItem:
        """Insert or replace a memory item in the store."""
        if not allow_sensitive and (
            is_sensitive_content(item.content) or is_sensitive_content(item.key)
        ):
            raise ValueError(
                "Refused to store raw sensitive authentication materials (passwords, tokens, keys)."
            )

        now = time.time()
        updated_item = MemoryItem(
            id=item.id,
            key=item.key,
            content=item.content,
            category=item.category,
            project_name=item.project_name,
            metadata=item.metadata,
            source=item.source,
            confidence=item.confidence,
            created_at=item.created_at or now,
            updated_at=now,
            expires_at=item.expires_at,
            access_count=item.access_count,
            is_deleted=item.is_deleted,
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    id, key, content, category, project_name, metadata_json,
                    source, confidence, created_at, updated_at, expires_at,
                    access_count, is_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    project_name = excluded.project_name,
                    metadata_json = excluded.metadata_json,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    is_deleted = 0
                """,
                (
                    updated_item.id,
                    updated_item.key,
                    updated_item.content,
                    updated_item.category,
                    updated_item.project_name,
                    json.dumps(updated_item.metadata),
                    updated_item.source,
                    updated_item.confidence,
                    updated_item.created_at,
                    updated_item.updated_at,
                    updated_item.expires_at,
                    updated_item.access_count,
                    1 if updated_item.is_deleted else 0,
                ),
            )
            conn.commit()
        return updated_item

    def close(self) -> None:
        """Prevent new connections; active operation handles close themselves."""

        self._closed = True

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_by_key(self, key: str, include_deleted: bool = False) -> MemoryItem | None:
        """Retrieve a memory item by exact key."""
        with self._connect() as conn:
            query = "SELECT * FROM memories WHERE key = ?"
            if not include_deleted:
                query += " AND is_deleted = 0"
            row = conn.execute(query, (key,)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE key = ?",
                (key,),
            )
            conn.commit()
            item = self._row_to_item(row)
            item.access_count += 1
            return item

    def get_by_id(
        self, item_id: str, include_deleted: bool = False
    ) -> MemoryItem | None:
        """Retrieve a memory item by ID or key."""
        with self._connect() as conn:
            query = "SELECT * FROM memories WHERE (id = ? OR key = ?)"
            if not include_deleted:
                query += " AND is_deleted = 0"
            row = conn.execute(query, (item_id, item_id)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            item = self._row_to_item(row)
            item.access_count += 1
            return item

    def update(
        self,
        item_id_or_key: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> MemoryItem | None:
        """Update an existing memory item."""
        existing = self.get_by_id(item_id_or_key) or self.get_by_key(item_id_or_key)
        if not existing:
            return None

        new_content = content if content is not None else existing.content
        if is_sensitive_content(new_content):
            raise ValueError(
                "Refused to update memory with raw sensitive auth material."
            )

        new_meta = {**existing.metadata, **(metadata or {})}
        new_cat = category or existing.category
        now = time.time()

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memories
                SET content = ?, metadata_json = ?, category = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_content, json.dumps(new_meta), new_cat, now, existing.id),
            )
            conn.commit()

        return self.get_by_id(existing.id)

    def delete(self, item_id_or_key: str, soft: bool = True) -> bool:
        """Delete a memory item (soft delete by default)."""
        existing = self.get_by_id(item_id_or_key) or self.get_by_key(item_id_or_key)
        if not existing:
            return False

        with self._connect() as conn:
            if soft:
                conn.execute(
                    "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE id = ?",
                    (time.time(), existing.id),
                )
            else:
                conn.execute("DELETE FROM memories WHERE id = ?", (existing.id,))
            conn.commit()
        return True

    def clear(self, category: str | None = None) -> int:
        """Clear memories, optionally filtered by category."""
        with self._connect() as conn:
            if category:
                cursor = conn.execute(
                    "DELETE FROM memories WHERE category = ?", (category,)
                )
            else:
                cursor = conn.execute("DELETE FROM memories")
            deleted_count = cursor.rowcount
            conn.commit()
        return deleted_count

    def search(
        self,
        query: str,
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search memory items by content or key substring."""
        qlower = f"%{query.strip().lower()}%"
        with self._connect() as conn:
            sql = """
            SELECT * FROM memories
            WHERE is_deleted = 0
              AND (LOWER(content) LIKE ? OR LOWER(key) LIKE ?)
            """
            params: list[Any] = [qlower, qlower]

            if category:
                sql += " AND category = ?"
                params.append(category)

            if project_name:
                sql += " AND project_name = ?"
                params.append(project_name)

            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_item(r) for r in rows]

    def list_all(
        self,
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """List memory items with optional category or project filter."""
        with self._connect() as conn:
            sql = "SELECT * FROM memories WHERE is_deleted = 0"
            params: list[Any] = []

            if category:
                sql += " AND category = ?"
                params.append(category)

            if project_name:
                sql += " AND project_name = ?"
                params.append(project_name)

            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_item(r) for r in rows]

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        meta_json = row["metadata_json"] or "{}"
        try:
            meta = json.loads(meta_json)
        except Exception:
            meta = {}

        return MemoryItem(
            id=row["id"],
            key=row["key"],
            content=row["content"],
            category=row["category"],
            project_name=row["project_name"],
            metadata=meta,
            source=row["source"] or "user",
            confidence=float(row["confidence"] or 1.0),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            expires_at=row["expires_at"],
            access_count=int(row["access_count"] or 0),
            is_deleted=bool(row["is_deleted"]),
        )
