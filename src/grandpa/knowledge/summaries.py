"""Deterministic summaries for Grandpa knowledge documents."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from grandpa.knowledge.indexing import tokenize
from grandpa.knowledge.storage import KnowledgeDocument, KnowledgeStore


def summarize_document(
    document: KnowledgeDocument, *, max_sentences: int = 4
) -> dict[str, Any]:
    sentences = _sentences(document.content)
    chosen = sentences[:max_sentences]
    if not chosen and document.content:
        chosen = [document.content[:320]]
    keywords = _top_keywords(document.content)
    return {
        "document_id": document.document_id,
        "title": document.title,
        "summary": " ".join(chosen).strip() or "No summary available yet.",
        "keywords": keywords,
        "tags": document.tags,
        "chunk_count": len(document.chunks),
        "deterministic": True,
    }


def summarize_topic(
    topic: str, *, store: KnowledgeStore | None = None, limit: int = 8
) -> dict[str, Any]:
    from grandpa.knowledge.retrieval import search_documents

    results = search_documents(query=topic, tag=topic, limit=limit, store=store)
    titles = [item["title"] for item in results]
    return {
        "topic": topic,
        "document_count": len(results),
        "titles": titles,
        "summary": (
            f"Found {len(results)} local knowledge document(s) related to {topic}: "
            + ", ".join(titles[:5])
            if results
            else f"No local knowledge documents are indexed for {topic} yet."
        ),
        "deterministic": True,
    }


def summarize_project(*, store: KnowledgeStore | None = None) -> dict[str, Any]:
    from grandpa.knowledge.retrieval import project_documents

    docs = project_documents(store=store, limit=20)
    tags = Counter(tag for doc in docs for tag in doc.get("tags", []))
    titles = [doc["title"] for doc in docs[:8]]
    return {
        "document_count": len(docs),
        "titles": titles,
        "top_tags": [
            {"tag": tag, "count": count} for tag, count in tags.most_common(10)
        ],
        "summary": (
            f"Grandpa has {len(docs)} project knowledge document(s) indexed. "
            f"Recent project documents: {', '.join(titles[:5])}."
            if docs
            else "No project knowledge documents are indexed yet."
        ),
        "deterministic": True,
    }


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return []
    parts = re.split(r"(?<=[.!?])\s+", compact)
    return [part.strip() for part in parts if len(part.strip()) > 20]


def _top_keywords(text: str, limit: int = 12) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "your",
        "grandpa",
        "should",
        "will",
    }
    counts = Counter(token for token in tokenize(text) if token not in stop)
    return [token for token, _count in counts.most_common(limit)]


__all__ = ["summarize_document", "summarize_project", "summarize_topic"]
