"""SQLite/FTS5 memory backend — zero-dependency default."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from grandpa.core.events import EventType, get_event_bus
from grandpa.core.registry import MemoryRegistry
from grandpa.tools.storage._stubs import MemoryBackend, RetrievalResult


def _check_fts5(conn: sqlite3.Connection) -> bool:
    """Return True if the SQLite build includes FTS5."""
    try:
        opts = conn.execute("PRAGMA compile_options").fetchall()
        return any("FTS5" in o[0].upper() for o in opts)
    except sqlite3.Error:
        return False


def _quote_fts_query(query: str) -> str:
    """Convert a plain user query into safe FTS5 terms."""
    terms = [term for term in (part.strip('"') for part in query.split()) if term]
    cleaned = []
    for term in terms:
        token = "".join(ch for ch in term if ch.isalnum() or ch in {"_", "-"})
        if token:
            cleaned.append(f'"{token}"')
    return " OR ".join(cleaned)


@MemoryRegistry.register("sqlite")
class SQLiteMemory(MemoryBackend):
    """Full-text search memory backend using SQLite FTS5.

    Uses the built-in ``sqlite3`` module — no extra dependencies.
    """

    backend_id: str = "sqlite"

    def __init__(self, db_path: str | Path = "") -> None:
        if not db_path:
            from grandpa.core.config import DEFAULT_CONFIG_DIR

            db_path = str(DEFAULT_CONFIG_DIR / "memory.db")

        self._db_path = str(db_path)

        try:
            from grandpa._rust_bridge import get_rust_module

            _rust = get_rust_module()
            self._rust_impl = _rust.SQLiteMemory(self._db_path)
            self._conn = None  # type: ignore[assignment]
        except Exception:
            self._rust_impl = None
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id       TEXT PRIMARY KEY,
                content  TEXT NOT NULL,
                source   TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
            USING fts5(
                content,
                source,
                tokenize='porter unicode61'
            );
        """)

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        meta_json = json.dumps(metadata) if metadata else None
        if self._rust_impl is not None:
            doc_id = self._rust_impl.store(content, source, meta_json)
        else:
            doc_id = str(uuid.uuid4())
            assert self._conn is not None
            with self._conn:
                self._conn.execute(
                    "INSERT INTO documents(id, content, source, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, content, source, meta_json or "{}", time.time()),
                )
                self._conn.execute(
                    "INSERT INTO documents_fts(rowid, content, source) VALUES ((SELECT rowid FROM documents WHERE id = ?), ?, ?)",
                    (doc_id, content, source),
                )
        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            },
        )
        return doc_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search via FTS5 MATCH with BM25 ranking — always via Rust backend."""
        if not query.strip():
            return []

        if self._rust_impl is not None:
            from grandpa._rust_bridge import retrieval_results_from_json

            results = retrieval_results_from_json(
                self._rust_impl.retrieve(_quote_fts_query(query) or query, top_k),
            )
        else:
            assert self._conn is not None
            if _check_fts5(self._conn):
                try:
                    rows = self._conn.execute(
                        """
                        SELECT d.id, d.content, d.source, d.metadata, bm25(documents_fts) AS score
                        FROM documents_fts
                        JOIN documents d ON d.rowid = documents_fts.rowid
                        WHERE documents_fts MATCH ?
                        ORDER BY score
                        LIMIT ?
                        """,
                        (_quote_fts_query(query) or query, top_k),
                    ).fetchall()
                except sqlite3.Error:
                    rows = self._conn.execute(
                        """
                        SELECT id, content, source, metadata, 0.0 AS score
                        FROM documents
                        WHERE content LIKE ? OR source LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (f"%{query}%", f"%{query}%", top_k),
                    ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT id, content, source, metadata, 0.0 AS score
                    FROM documents
                    WHERE content LIKE ? OR source LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", f"%{query}%", top_k),
                ).fetchall()
            results = [
                RetrievalResult(
                    content=row["content"],
                    source=row["source"],
                    score=max(0.0, -float(row["score"]))
                    if _check_fts5(self._conn)
                    else float(row["score"]),
                    metadata=json.loads(row["metadata"] or "{}"),
                )
                for row in rows
            ]
        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            },
        )
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id."""
        if self._rust_impl is not None:
            return self._rust_impl.delete(doc_id)
        assert self._conn is not None
        with self._conn:
            row = self._conn.execute(
                "SELECT rowid FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (row["rowid"],))
            self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return True

    def clear(self) -> None:
        """Remove all stored documents."""
        if self._rust_impl is not None:
            self._rust_impl.clear()
            return
        assert self._conn is not None
        with self._conn:
            self._conn.execute("DELETE FROM documents_fts")
            self._conn.execute("DELETE FROM documents")

    def count(self) -> int:
        """Return the number of stored documents."""
        if self._rust_impl is not None:
            return self._rust_impl.count()
        assert self._conn is not None
        return int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()


__all__ = ["SQLiteMemory"]
