"""BM25 memory backend — classic term-frequency retrieval.

Uses the Rust ``BM25Memory`` when the ``grandpa_rust`` binding is built, and an
identical pure-Python implementation otherwise. The module used to call
``get_rust_module()`` at import, so on every normal install (the binding is not
built by default) importing it raised ``ImportError`` and the ``bm25`` backend
silently did not exist.
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List, Optional

from grandpa._rust_bridge import get_rust_module
from grandpa.core.events import EventType, get_event_bus
from grandpa.core.registry import MemoryRegistry
from grandpa.tools.storage._stubs import MemoryBackend, RetrievalResult


def _tokenize(text: str) -> List[str]:
    """Lowercase whitespace tokenizer."""
    return text.lower().split()


def _terms(text: str) -> Dict[str, int]:
    """Term counts, the same normalisation as the Rust backend."""
    counts: Dict[str, int] = {}
    for word in text.split():
        term = word.lower()
        start, end = 0, len(term)
        while start < end and not term[start].isalnum():
            start += 1
        while end > start and not term[end - 1].isalnum():
            end -= 1
        term = term[start:end]
        if term:
            counts[term] = counts.get(term, 0) + 1
    return counts


class _PythonBM25:
    """Pure-Python twin of the Rust ``BM25Memory`` (same API, same scores)."""

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: List[Dict[str, Any]] = []

    def store(self, content: str, source: str, meta_json: Optional[str]) -> str:
        terms = _terms(content)
        doc_id = uuid.uuid4().hex
        self._docs.append(
            {
                "id": doc_id,
                "content": content,
                "source": source,
                "metadata": json.loads(meta_json) if meta_json else {},
                "terms": terms,
                "length": sum(terms.values()),
            }
        )
        return doc_id

    def retrieve(self, query: str, top_k: int) -> str:
        if not self._docs:
            return "[]"
        query_terms = _terms(query)
        n = float(len(self._docs))
        avg_dl = sum(d["length"] for d in self._docs) / n or 1.0
        df: Dict[str, int] = {}
        for doc in self._docs:
            for term in doc["terms"]:
                df[term] = df.get(term, 0) + 1
        scored = []
        for doc in self._docs:
            score = 0.0
            for term in query_terms:
                tf = doc["terms"].get(term, 0)
                freq = df.get(term, 0)
                if not tf or not freq:
                    continue
                idf = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)
                score += (
                    idf
                    * (tf * (self.k1 + 1.0))
                    / (tf + self.k1 * (1.0 - self.b + self.b * doc["length"] / avg_dl))
                )
            if score > 0.0:
                scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return json.dumps(
            [
                {
                    "content": doc["content"],
                    "score": score,
                    "source": doc["source"],
                    "metadata": doc["metadata"],
                }
                for score, doc in scored[:top_k]
            ]
        )

    def delete(self, doc_id: str) -> bool:
        before = len(self._docs)
        self._docs = [d for d in self._docs if d["id"] != doc_id]
        return len(self._docs) != before

    def clear(self) -> None:
        self._docs = []

    def count(self) -> int:
        return len(self._docs)


@MemoryRegistry.register("bm25")
class BM25Memory(MemoryBackend):
    """In-memory BM25 (Okapi) retrieval backend.

    Scores documents against a query with the classic BM25 probabilistic
    ranking function, in Rust when the binding is built and in Python
    otherwise. All data lives in memory — there is no persistence across
    restarts.
    """

    backend_id: str = "bm25"

    def __init__(self) -> None:
        try:
            self._rust_impl = get_rust_module().BM25Memory()
        except (ImportError, AttributeError):
            self._rust_impl = _PythonBM25()

    # -- ABC implementation -------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        meta_json = json.dumps(metadata) if metadata else None
        doc_id = self._rust_impl.store(content, source, meta_json)
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
        """Search for *query* and return the top-k results (Rust or Python)."""
        if not query.strip():
            return []
        from grandpa._rust_bridge import retrieval_results_from_json

        results = retrieval_results_from_json(
            self._rust_impl.retrieve(query, top_k),
        )
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
        """Delete a document by id (Rust or Python)."""
        return self._rust_impl.delete(doc_id)

    def clear(self) -> None:
        """Remove all stored documents (Rust or Python)."""
        self._rust_impl.clear()

    def count(self) -> int:
        """Return the number of stored documents (Rust or Python)."""
        return self._rust_impl.count()


__all__ = ["BM25Memory"]
