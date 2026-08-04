"""SQLite storage for Grandpa's local knowledge engine."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KNOWLEDGE_DIR = ROOT / "runtime" / "knowledge"
DEFAULT_KNOWLEDGE_DB = DEFAULT_KNOWLEDGE_DIR / "knowledge.db"


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    source: str
    title: str
    tags: list[str]
    content: str
    chunks: list[dict[str, Any]]
    created_at: float
    updated_at: float
    embeddings_placeholder: dict[str, Any]
    metadata: dict[str, Any]

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["chunk_count"] = len(self.chunks)
        payload["word_count"] = len(self.content.split())
        if not include_content:
            payload.pop("content", None)
            payload.pop("chunks", None)
        return payload


class KnowledgeStore:
    """Local SQLite knowledge document store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(
            db_path or os.environ.get("GRANDPA_KNOWLEDGE_DB") or DEFAULT_KNOWLEDGE_DB
        )
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
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    content TEXT NOT NULL,
                    chunks TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    embeddings_placeholder TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_title ON knowledge_documents(title)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_documents(source)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_updated ON knowledge_documents(updated_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_version TEXT NOT NULL,
                    backend TEXT NOT NULL DEFAULT 'unknown',
                    true_semantic INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(document_id, chunk_id),
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(document_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_model "
                "ON knowledge_embeddings(embedding_model, embedding_version)"
            )

    def save_document(
        self,
        *,
        source: str,
        title: str,
        tags: list[str],
        content: str,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> KnowledgeDocument:
        now = time.time()
        existing = self.find_by_source(source)
        doc_id = document_id or (
            existing["document_id"] if existing else "knw_" + uuid.uuid4().hex[:12]
        )
        created = float(existing["created_at"]) if existing else now
        document = KnowledgeDocument(
            document_id=doc_id,
            source=source,
            title=title,
            tags=tags,
            content=content,
            chunks=chunks,
            created_at=created,
            updated_at=now,
            embeddings_placeholder={
                "status": "not_built",
                "reason": "Knowledge v1 uses deterministic keyword retrieval; embeddings are planned.",
            },
            metadata=metadata or {},
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_documents(
                    document_id, source, title, tags, content, chunks,
                    created_at, updated_at, embeddings_placeholder, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source=excluded.source,
                    title=excluded.title,
                    tags=excluded.tags,
                    content=excluded.content,
                    chunks=excluded.chunks,
                    updated_at=excluded.updated_at,
                    embeddings_placeholder=excluded.embeddings_placeholder,
                    metadata=excluded.metadata
                """,
                (
                    document.document_id,
                    document.source,
                    document.title,
                    json.dumps(document.tags, ensure_ascii=True),
                    document.content,
                    json.dumps(document.chunks, ensure_ascii=True),
                    document.created_at,
                    document.updated_at,
                    json.dumps(document.embeddings_placeholder, ensure_ascii=True),
                    json.dumps(document.metadata, ensure_ascii=True),
                ),
            )
        return document

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return _row_to_document(row) if row else None

    def find_by_source(self, source: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT document_id, created_at FROM knowledge_documents WHERE source = ?",
                (source,),
            ).fetchone()
        return dict(row) if row else None

    def list_documents(self, *, limit: int = 100) -> list[KnowledgeDocument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_documents ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_document(row) for row in rows]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_documents"
            ).fetchone()
        return int(row["count"] if row else 0)

    def tags(self) -> list[str]:
        tags: set[str] = set()
        for doc in self.list_documents(limit=1000):
            tags.update(doc.tags)
        return sorted(tags)

    def save_embedding(
        self,
        *,
        document_id: str,
        chunk_id: str,
        embedding: str,
        embedding_model: str,
        embedding_version: str,
        backend: str,
        true_semantic: bool,
        created_at: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_embeddings(
                    document_id, chunk_id, embedding, embedding_model,
                    embedding_version, backend, true_semantic, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, chunk_id) DO UPDATE SET
                    embedding=excluded.embedding,
                    embedding_model=excluded.embedding_model,
                    embedding_version=excluded.embedding_version,
                    backend=excluded.backend,
                    true_semantic=excluded.true_semantic,
                    created_at=excluded.created_at
                """,
                (
                    document_id,
                    chunk_id,
                    embedding,
                    embedding_model,
                    embedding_version,
                    backend,
                    1 if true_semantic else 0,
                    created_at,
                ),
            )

    def embeddings_for_document(self, document_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_embeddings WHERE document_id = ? ORDER BY chunk_id ASC",
                (document_id,),
            ).fetchall()
        return [_embedding_row(row) for row in rows]

    def all_embeddings(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_embeddings ORDER BY created_at DESC"
            ).fetchall()
        return [_embedding_row(row) for row in rows]

    def embedding_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_embeddings"
            ).fetchone()
        return int(row["count"] if row else 0)

    def embedding_status(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_embeddings"
            ).fetchone()["count"]
            semantic = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_embeddings WHERE true_semantic = 1"
            ).fetchone()["count"]
            rows = conn.execute(
                """
                SELECT embedding_model, embedding_version, backend, true_semantic, COUNT(*) AS count
                FROM knowledge_embeddings
                GROUP BY embedding_model, embedding_version, backend, true_semantic
                ORDER BY count DESC
                """
            ).fetchall()
        return {
            "embedding_count": int(total),
            "true_semantic_count": int(semantic),
            "fallback_count": int(total) - int(semantic),
            "models": [_embedding_model_row(row) for row in rows],
        }


def _row_to_document(row: sqlite3.Row) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=row["document_id"],
        source=row["source"],
        title=row["title"],
        tags=_loads_list(row["tags"]),
        content=row["content"],
        chunks=_loads_list(row["chunks"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        embeddings_placeholder=_loads_dict(row["embeddings_placeholder"]),
        metadata=_loads_dict(row["metadata"]),
    )


def _loads_list(value: str) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
        return loaded if isinstance(loaded, list) else []
    except Exception:
        return []


def _loads_dict(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _embedding_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "document_id": row["document_id"],
        "chunk_id": row["chunk_id"],
        "embedding": row["embedding"],
        "embedding_model": row["embedding_model"],
        "embedding_version": row["embedding_version"],
        "backend": row["backend"],
        "true_semantic": bool(row["true_semantic"]),
        "created_at": float(row["created_at"]),
    }


def _embedding_model_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "embedding_model": row["embedding_model"],
        "embedding_version": row["embedding_version"],
        "backend": row["backend"],
        "true_semantic": bool(row["true_semantic"]),
        "count": int(row["count"]),
    }


__all__ = [
    "DEFAULT_KNOWLEDGE_DB",
    "DEFAULT_KNOWLEDGE_DIR",
    "KnowledgeDocument",
    "KnowledgeStore",
]
