"""Keyword, title, tag, and recency retrieval for local knowledge."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from grandpa.knowledge.embeddings import KnowledgeEmbedder, cosine_similarity, decode_vector
from grandpa.knowledge.indexing import tokenize
from grandpa.knowledge.storage import KnowledgeDocument, KnowledgeStore


@dataclass(frozen=True)
class KnowledgeSearchResult:
    document: KnowledgeDocument
    score: float
    matched_terms: list[str]
    matched_chunks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.document.to_dict(include_content=False),
            "score": round(self.score, 4),
            "matched_terms": self.matched_terms,
            "matched_chunks": self.matched_chunks[:3],
        }


def search_documents(
    query: str = "",
    *,
    tag: str = "",
    title: str = "",
    project_only: bool = False,
    limit: int = 20,
    store: KnowledgeStore | None = None,
) -> list[dict[str, Any]]:
    knowledge_store = store or KnowledgeStore()
    query_terms = set(tokenize(query))
    title_terms = set(tokenize(title))
    tag_clean = tag.strip().lower()
    scored: list[KnowledgeSearchResult] = []
    for doc in knowledge_store.list_documents(limit=1000):
        if tag_clean and tag_clean not in {item.lower() for item in doc.tags}:
            continue
        if project_only and "project" not in {item.lower() for item in doc.tags}:
            continue
        score, terms, chunks = _score_document(doc, query_terms, title_terms)
        if query_terms or title_terms:
            if score <= 0:
                continue
        else:
            score = 0.15
        scored.append(KnowledgeSearchResult(doc, score, sorted(terms), chunks))
    scored.sort(key=lambda item: (item.score, item.document.updated_at), reverse=True)
    return [item.to_dict() for item in scored[:limit]]


def semantic_search_documents(
    query: str,
    *,
    tag: str = "",
    project_only: bool = False,
    limit: int = 10,
    store: KnowledgeStore | None = None,
    embedder: KnowledgeEmbedder | None = None,
) -> dict[str, Any]:
    knowledge_store = store or KnowledgeStore()
    query_embedding = (embedder or KnowledgeEmbedder()).embed(query)
    tag_clean = tag.strip().lower()
    documents = {doc.document_id: doc for doc in knowledge_store.list_documents(limit=1000)}
    chunk_scores: list[dict[str, Any]] = []
    for row in knowledge_store.all_embeddings():
        doc = documents.get(row["document_id"])
        if not doc:
            continue
        if tag_clean and tag_clean not in {item.lower() for item in doc.tags}:
            continue
        if project_only and "project" not in {item.lower() for item in doc.tags}:
            continue
        score = cosine_similarity(query_embedding.vector, decode_vector(row["embedding"]))
        if score <= 0:
            continue
        chunk = _chunk_by_id(doc, row["chunk_id"])
        chunk_scores.append(
            {
                **doc.to_dict(include_content=False),
                "chunk_id": row["chunk_id"],
                "chunk": chunk,
                "semantic_score": round(score, 4),
                "score": round(score, 4),
                "embedding_model": row["embedding_model"],
                "embedding_version": row["embedding_version"],
                "embedding_backend": row["backend"],
                "true_semantic": bool(row["true_semantic"]) and query_embedding.true_semantic,
                "ranking_explanation": {
                    "semantic_score": round(score, 4),
                    "keyword_score": 0.0,
                    "recency_score": 0.0,
                    "mode": "semantic" if row["true_semantic"] and query_embedding.true_semantic else "deterministic_fallback",
                },
            }
        )
    chunk_scores.sort(key=lambda item: item["semantic_score"], reverse=True)
    return {
        "query": query,
        "results": chunk_scores[:limit],
        "semantic_search": bool(query_embedding.true_semantic),
        "semantic_mode": "ollama" if query_embedding.true_semantic else "deterministic_fallback",
        "embedding_model": query_embedding.model,
        "embedding_version": query_embedding.version,
        "truthful_note": (
            "Semantic embeddings came from a local Ollama model."
            if query_embedding.true_semantic
            else "Ollama semantic embeddings were unavailable; deterministic fallback vectors were used."
        ),
        "local_only": True,
    }


def hybrid_search_documents(
    query: str,
    *,
    tag: str = "",
    title: str = "",
    project_only: bool = False,
    limit: int = 20,
    store: KnowledgeStore | None = None,
) -> dict[str, Any]:
    knowledge_store = store or KnowledgeStore()
    keyword_results = search_documents(query, tag=tag, title=title, project_only=project_only, limit=100, store=knowledge_store)
    semantic = semantic_search_documents(query, tag=tag, project_only=project_only, limit=100, store=knowledge_store)
    by_doc: dict[str, dict[str, Any]] = {}
    now = time.time()
    for item in keyword_results:
        by_doc[item["document_id"]] = {
            **item,
            "keyword_score": float(item.get("score", 0.0)),
            "semantic_score": 0.0,
            "recency_score": _recency_score(float(item.get("updated_at", now)), now),
            "matched_chunks": item.get("matched_chunks", []),
        }
    for item in semantic["results"]:
        doc_id = item["document_id"]
        current = by_doc.setdefault(
            doc_id,
            {
                **{key: value for key, value in item.items() if key not in {"chunk", "ranking_explanation"}},
                "keyword_score": 0.0,
                "semantic_score": 0.0,
                "recency_score": _recency_score(float(item.get("updated_at", now)), now),
                "matched_chunks": [],
            },
        )
        current["semantic_score"] = max(float(current.get("semantic_score", 0.0)), float(item.get("semantic_score", 0.0)))
        chunks = current.setdefault("retrieved_chunks", [])
        chunks.append(item.get("chunk", {}))
        current["true_semantic"] = bool(item.get("true_semantic", False))
    results: list[dict[str, Any]] = []
    for item in by_doc.values():
        keyword_score = min(1.0, float(item.get("keyword_score", 0.0)) / 10.0)
        semantic_score = max(0.0, float(item.get("semantic_score", 0.0)))
        recency_score = float(item.get("recency_score", 0.0))
        combined = 0.45 * keyword_score + 0.45 * semantic_score + 0.10 * recency_score
        item["score"] = round(combined, 4)
        item["ranking_explanation"] = {
            "keyword_score": round(keyword_score, 4),
            "semantic_score": round(semantic_score, 4),
            "recency_score": round(recency_score, 4),
            "weights": {"keyword": 0.45, "semantic": 0.45, "recency": 0.10},
            "semantic_mode": semantic["semantic_mode"],
            "true_semantic": bool(item.get("true_semantic", False)),
        }
        results.append(item)
    results.sort(key=lambda row: row["score"], reverse=True)
    return {
        "query": query,
        "results": results[:limit],
        "semantic_search": bool(semantic["semantic_search"]),
        "semantic_mode": semantic["semantic_mode"],
        "retrieval": "hybrid_keyword_semantic_recency",
        "truthful_note": semantic["truthful_note"],
        "local_only": True,
    }


def recent_documents(*, limit: int = 10, store: KnowledgeStore | None = None) -> list[dict[str, Any]]:
    return [doc.to_dict(include_content=False) for doc in (store or KnowledgeStore()).list_documents(limit=limit)]


def project_documents(*, limit: int = 20, store: KnowledgeStore | None = None) -> list[dict[str, Any]]:
    return search_documents(project_only=True, limit=limit, store=store)


def related_documents(document_id: str, *, limit: int = 8, store: KnowledgeStore | None = None) -> dict[str, Any]:
    knowledge_store = store or KnowledgeStore()
    document = knowledge_store.get_document(document_id)
    if not document:
        raise KeyError(document_id)
    query = " ".join([document.title, *document.tags, document.content[:500]])
    results = hybrid_search_documents(query, limit=limit + 1, store=knowledge_store)["results"]
    return {
        "document_id": document_id,
        "results": [item for item in results if item["document_id"] != document_id][:limit],
        "local_only": True,
    }


def _score_document(
    doc: KnowledgeDocument,
    query_terms: set[str],
    title_terms: set[str],
) -> tuple[float, set[str], list[dict[str, Any]]]:
    terms = query_terms | title_terms
    if not terms:
        return 0.0, set(), []
    title_tokens = set(tokenize(doc.title))
    tag_tokens = {tag.lower() for tag in doc.tags}
    content_tokens = set(tokenize(doc.content))
    matched = terms & (title_tokens | tag_tokens | content_tokens)
    score = 0.0
    score += 3.0 * len(terms & title_tokens)
    score += 2.2 * len(terms & tag_tokens)
    score += 1.0 * len(terms & content_tokens)
    matched_chunks: list[dict[str, Any]] = []
    for chunk in doc.chunks:
        chunk_keywords = {str(item).lower() for item in chunk.get("keywords", [])}
        chunk_hits = sorted(terms & chunk_keywords)
        if chunk_hits:
            score += 0.4 * len(chunk_hits)
            matched_chunks.append(
                {
                    "index": chunk.get("index", 0),
                    "text": chunk.get("text", "")[:500],
                    "matched_terms": chunk_hits,
                }
            )
    return score, matched, matched_chunks


def _chunk_by_id(doc: KnowledgeDocument, chunk_id: str) -> dict[str, Any]:
    try:
        index = int(str(chunk_id).split("_")[-1])
    except Exception:
        index = -1
    for chunk in doc.chunks:
        if int(chunk.get("index", -2)) == index:
            return {
                "document_id": doc.document_id,
                "chunk_id": chunk_id,
                "index": chunk.get("index", 0),
                "text": str(chunk.get("text", ""))[:900],
                "keywords": chunk.get("keywords", [])[:20],
            }
    return {"document_id": doc.document_id, "chunk_id": chunk_id, "text": ""}


def _recency_score(updated_at: float, now: float) -> float:
    age_days = max(0.0, (now - updated_at) / 86400.0)
    return max(0.0, min(1.0, 1.0 / (1.0 + age_days / 30.0)))


__all__ = [
    "KnowledgeSearchResult",
    "hybrid_search_documents",
    "project_documents",
    "recent_documents",
    "related_documents",
    "search_documents",
    "semantic_search_documents",
]
