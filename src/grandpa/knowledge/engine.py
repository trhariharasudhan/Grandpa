"""Local-first knowledge engine facade for Grandpa."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from grandpa.knowledge.embeddings import KnowledgeEmbedder, encode_vector
from grandpa.knowledge.indexing import (
    FUTURE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    chunk_text,
    infer_tags,
    infer_title,
    normalize_text,
    read_supported_file,
)
from grandpa.knowledge.retrieval import (
    hybrid_search_documents,
    project_documents,
    recent_documents,
    related_documents,
    search_documents,
    semantic_search_documents,
)
from grandpa.knowledge.storage import (
    DEFAULT_KNOWLEDGE_DB,
    KnowledgeDocument,
    KnowledgeStore,
)
from grandpa.knowledge.summaries import (
    summarize_document,
    summarize_project,
    summarize_topic,
)


class KnowledgeEngine:
    """Deterministic local knowledge ingestion, indexing, retrieval, and summaries."""

    def __init__(self, store: KnowledgeStore | None = None) -> None:
        self.store = store or KnowledgeStore()

    def import_document(
        self,
        *,
        source: str,
        content: str,
        title: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_text(content)
        if not normalized:
            raise ValueError("Knowledge import needs non-empty content")
        final_title = infer_title(source, content, title)
        final_tags = infer_tags(source, content, tags)
        chunks = chunk_text(normalized)
        document = self.store.save_document(
            source=source,
            title=final_title,
            tags=final_tags,
            content=normalized,
            chunks=chunks,
            metadata=metadata or {},
        )
        self._ensure_document_embeddings(document)
        self._memory_writeback(document)
        return {
            "status": "imported",
            "document": document.to_dict(include_content=False),
            "summary": summarize_document(document),
            "local_only": True,
        }

    def import_file(self, path: str | Path, *, tags: list[str] | None = None) -> dict[str, Any]:
        content, metadata = read_supported_file(path)
        return self.import_document(
            source=str(Path(path)),
            content=content,
            title=None,
            tags=tags,
            metadata=metadata,
        )

    def import_project_docs(self, root: str | Path = "docs", *, limit: int = 100) -> dict[str, Any]:
        root_path = Path(root)
        if not root_path.is_absolute():
            root_path = Path(__file__).resolve().parents[3] / root_path
        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for path in sorted(root_path.rglob("*"))[:limit]:
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                imported.append(self.import_file(path, tags=["project", "docs"])["document"])
            except Exception as exc:
                skipped.append({"path": str(path), "error": exc.__class__.__name__})
        return {"status": "completed", "imported": imported, "skipped": skipped, "count": len(imported)}

    def search(self, query: str = "", *, tag: str = "", title: str = "", project_only: bool = False, limit: int = 20) -> dict[str, Any]:
        if query.strip():
            self.ensure_embeddings()
            return hybrid_search_documents(
                query,
                tag=tag,
                title=title,
                project_only=project_only,
                limit=limit,
                store=self.store,
            )
        return {
            "query": query,
            "tag": tag,
            "title": title,
            "project_only": project_only,
            "results": search_documents(query, tag=tag, title=title, project_only=project_only, limit=limit, store=self.store),
            "semantic_search": False,
            "retrieval": "keyword_title_tag_recency",
            "truthful_note": "No query was provided, so semantic ranking was not used.",
            "local_only": True,
        }

    def semantic_search(self, query: str, *, tag: str = "", project_only: bool = False, limit: int = 10) -> dict[str, Any]:
        self.ensure_embeddings()
        return semantic_search_documents(query, tag=tag, project_only=project_only, limit=limit, store=self.store)

    def related(self, document_id: str, *, limit: int = 8) -> dict[str, Any]:
        self.ensure_embeddings()
        return related_documents(document_id, limit=limit, store=self.store)

    def context(self, query: str, *, limit: int = 5, project_only: bool = False) -> dict[str, Any]:
        search = self.search(query, project_only=project_only, limit=limit)
        chunks: list[dict[str, Any]] = []
        for item in search.get("results", []):
            chunks.extend(item.get("retrieved_chunks") or item.get("matched_chunks") or [])
        doc_ids = []
        documents = []
        for item in search.get("results", []):
            if item["document_id"] in doc_ids:
                continue
            doc_ids.append(item["document_id"])
            documents.append({key: item.get(key) for key in ("document_id", "title", "source", "tags", "score", "ranking_explanation")})
        return {
            "query": query,
            "chunks": chunks[:limit],
            "documents": documents[:limit],
            "summary": self.summary(project=True if project_only else False),
            "semantic_search": search.get("semantic_search", False),
            "semantic_mode": search.get("semantic_mode", "keyword_only"),
            "truthful_note": search.get("truthful_note", ""),
            "local_only": True,
        }

    def documents(self, *, limit: int = 100) -> dict[str, Any]:
        return {"documents": [doc.to_dict(include_content=False) for doc in self.store.list_documents(limit=limit)]}

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.get_document(document_id)
        return document.to_dict() if document else None

    def recent(self, *, limit: int = 10) -> dict[str, Any]:
        return {"documents": recent_documents(limit=limit, store=self.store)}

    def projects(self, *, limit: int = 20) -> dict[str, Any]:
        return {"documents": project_documents(limit=limit, store=self.store), "summary": summarize_project(store=self.store)}

    def summary(self, *, document_id: str = "", topic: str = "", project: bool = False) -> dict[str, Any]:
        if document_id:
            document = self.store.get_document(document_id)
            if not document:
                raise KeyError(document_id)
            return summarize_document(document)
        if project:
            return summarize_project(store=self.store)
        if topic:
            return summarize_topic(topic, store=self.store)
        return {
            "summary": "Knowledge engine is ready. Import documents to build local project knowledge.",
            "document_count": self.store.count(),
            "tags": self.store.tags(),
            "deterministic": True,
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "ready": True,
            "db_path": str(self.store.db_path),
            "document_count": self.store.count(),
            "tags": self.store.tags(),
            "supported_sources": sorted(SUPPORTED_EXTENSIONS),
            "future_sources": sorted(FUTURE_EXTENSIONS),
            "retrieval": {
                "keyword": True,
                "title": True,
                "tags": True,
                "recent": True,
                "project_documents": True,
                "semantic_vector_search": True,
                "hybrid_search": True,
            },
            "embeddings": self.embedding_status(),
            "local_only": True,
        }

    def embedding_status(self) -> dict[str, Any]:
        status = KnowledgeEmbedder().status()
        stored = self.store.embedding_status()
        expected = sum(len(doc.chunks) for doc in self.store.list_documents(limit=1000))
        return {
            **status,
            **stored,
            "expected_chunk_embeddings": expected,
            "complete": expected == stored.get("embedding_count", 0),
            "external_vector_db": False,
        }

    def ensure_embeddings(self) -> dict[str, Any]:
        created = 0
        for document in self.store.list_documents(limit=1000):
            before = len(self.store.embeddings_for_document(document.document_id))
            self._ensure_document_embeddings(document)
            after = len(self.store.embeddings_for_document(document.document_id))
            created += max(0, after - before)
        return {"created": created, "status": self.embedding_status()}

    def _ensure_document_embeddings(self, document: KnowledgeDocument) -> None:
        existing = {row["chunk_id"] for row in self.store.embeddings_for_document(document.document_id)}
        embedder = KnowledgeEmbedder()
        for chunk in document.chunks:
            chunk_id = f"chunk_{chunk.get('index', 0)}"
            if chunk_id in existing:
                continue
            result = embedder.embed(str(chunk.get("text", "")))
            self.store.save_embedding(
                document_id=document.document_id,
                chunk_id=chunk_id,
                embedding=encode_vector(result.vector),
                embedding_model=result.model,
                embedding_version=result.version,
                backend=result.backend,
                true_semantic=result.true_semantic,
                created_at=result.created_at,
            )

    def _memory_writeback(self, document: KnowledgeDocument) -> None:
        try:
            from grandpa.memory_context import SENSITIVE_PATTERN, MemoryStore

            if SENSITIVE_PATTERN.search(document.content):
                return
            MemoryStore().remember(
                "knowledge",
                document.document_id,
                f"Imported knowledge document: {document.title}",
                source="knowledge_engine",
            )
        except Exception:
            return


def import_knowledge_document(**kwargs: Any) -> dict[str, Any]:
    return KnowledgeEngine().import_document(**kwargs)


def search_knowledge(query: str = "", **kwargs: Any) -> dict[str, Any]:
    return KnowledgeEngine().search(query, **kwargs)


def semantic_search_knowledge(query: str, **kwargs: Any) -> dict[str, Any]:
    return KnowledgeEngine().semantic_search(query, **kwargs)


def knowledge_context(query: str, **kwargs: Any) -> dict[str, Any]:
    return KnowledgeEngine().context(query, **kwargs)


def related_knowledge(document_id: str, **kwargs: Any) -> dict[str, Any]:
    return KnowledgeEngine().related(document_id, **kwargs)


def list_knowledge_documents(limit: int = 100) -> dict[str, Any]:
    return KnowledgeEngine().documents(limit=limit)


def recent_knowledge_documents(limit: int = 10) -> dict[str, Any]:
    return KnowledgeEngine().recent(limit=limit)


def summarize_knowledge_document(document_id: str) -> dict[str, Any]:
    return KnowledgeEngine().summary(document_id=document_id)


def project_knowledge_summary() -> dict[str, Any]:
    return KnowledgeEngine().summary(project=True)


def knowledge_diagnostics() -> dict[str, Any]:
    return KnowledgeEngine().diagnostics()


def knowledge_embedding_status() -> dict[str, Any]:
    return KnowledgeEngine().embedding_status()


def planner_knowledge_context(query: str, *, limit: int = 5) -> dict[str, Any]:
    engine = KnowledgeEngine()
    context = engine.context(query, limit=limit)
    context["available"] = True
    return context


__all__ = [
    "DEFAULT_KNOWLEDGE_DB",
    "KnowledgeEngine",
    "import_knowledge_document",
    "knowledge_diagnostics",
    "knowledge_context",
    "knowledge_embedding_status",
    "list_knowledge_documents",
    "planner_knowledge_context",
    "project_knowledge_summary",
    "related_knowledge",
    "recent_knowledge_documents",
    "search_knowledge",
    "semantic_search_knowledge",
    "summarize_knowledge_document",
]
