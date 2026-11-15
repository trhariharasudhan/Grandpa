"""V1-T8: personal memory matches by meaning (Ollama embeddings), not words.

Ollama is faked here: the fake maps words to a few "concepts" so a
paraphrase and its fact share a vector, which is what a real embedding model
does and the hashed bag-of-words cannot. These tests prove the plumbing --
model selection, task prefixes, fallback, re-embedding, thresholds and the
"I don't know" answer. Real recall numbers come from
``grandpa memory recall-test --backend personal`` on a machine with Ollama.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from grandpa import memory_context
from grandpa.memory.recall_test import PersonalMemoryAdapter, run_recall_test
from grandpa.memory_context import (
    HASH_EMBEDDER,
    MEMORY_EMBEDDER_ENV,
    MemoryStore,
    active_memory_embedder,
    build_personal_memory_context,
    reset_memory_embedder_cache,
)

pytestmark = pytest.mark.core

CONCEPTS = {
    "car": 0,
    "vehicle": 0,
    "drive": 0,
    "hyundai": 0,
    "sister": 1,
    "sibling": 1,
    "priya": 1,
    "tea": 2,
    "coffee": 2,
    "drink": 2,
    "dentist": 3,
    "teeth": 3,
    "doctor": 3,
}
DIMS = 8


def _fake_vector(text: str) -> list[float]:
    vector = [0.05] * DIMS
    for word in text.lower().replace("'", " ").split():
        word = word.strip("?.,:")
        if word in CONCEPTS:
            vector[CONCEPTS[word]] += 1.0
    return vector


class FakeOllama:
    def __init__(self, *, models=("nomic-embed-text:latest",), up=True, embed_ok=True):
        self.models = list(models)
        self.up = up
        self.embed_ok = embed_ok
        self.inputs: list[str] = []
        self.embed_calls = 0

    def get(self, url, timeout=None):
        if not self.up:
            raise ConnectionError("ollama is not running")
        assert url.endswith("/api/tags")
        return _Response({"models": [{"name": name} for name in self.models]})

    def post(self, url, json=None, timeout=None):
        assert url.endswith("/api/embed")
        self.embed_calls += 1
        if not self.embed_ok:
            raise ConnectionError("ollama went away")
        self.inputs.extend(json["input"])
        return _Response({"embeddings": [_fake_vector(t) for t in json["input"]]})


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


@pytest.fixture
def ollama(monkeypatch) -> FakeOllama:
    import httpx

    fake = FakeOllama()
    monkeypatch.setattr(httpx, "get", fake.get)
    monkeypatch.setattr(httpx, "post", fake.post)
    monkeypatch.setenv(MEMORY_EMBEDDER_ENV, "auto")
    reset_memory_embedder_cache()
    yield fake
    reset_memory_embedder_cache()


def _store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path / "personal_memory.db")
    store.remember("note", "car", "My car is a blue Hyundai i20")
    store.remember("note", "sister", "My sister's name is Priya")
    store.remember("note", "drink", "I prefer tea over coffee in the morning")
    return store


def test_paraphrase_finds_the_fact_by_meaning(tmp_path, ollama) -> None:
    results = _store(tmp_path).search_memories("what vehicle do I drive")

    assert results[0]["key"] == "car"
    assert results[0]["embedding_model"] == "ollama:nomic-embed-text:latest"
    assert results[0]["semantic_score"] > 0.5


def test_nomic_task_prefixes_are_sent(tmp_path, ollama) -> None:
    _store(tmp_path).search_memories("who is my sibling")

    assert any(text.startswith("search_document: ") for text in ollama.inputs)
    assert "search_query: who is my sibling" in ollama.inputs


def test_grandpa_memory_is_preferred_when_installed(ollama) -> None:
    ollama.models = ["nomic-embed-text:latest", "grandpa-memory:latest"]
    assert active_memory_embedder().ollama_tag == "grandpa-memory:latest"


def test_no_embedding_model_installed_means_hash(ollama) -> None:
    ollama.models = ["qwen3:8b"]
    assert active_memory_embedder() is HASH_EMBEDDER


def test_unreachable_ollama_falls_back_to_hash(tmp_path, ollama) -> None:
    ollama.up = False
    results = _store(tmp_path).search_memories("what car do I have")

    assert results[0]["key"] == "car"
    assert results[0]["embedding_model"] == HASH_EMBEDDER.model
    assert ollama.embed_calls == 0


def test_ollama_failing_mid_search_falls_back_without_raising(tmp_path, ollama) -> None:
    store = _store(tmp_path)  # embedded with Ollama
    ollama.embed_ok = False
    reset_memory_embedder_cache()  # the probe still says Ollama is up

    results = store.search_memories("what car do I have")

    assert results[0]["key"] == "car"
    assert results[0]["embedding_model"] == HASH_EMBEDDER.model
    # and the next search does not retry Ollama for a minute
    calls = ollama.embed_calls
    store.search_memories("what car do I have")
    assert ollama.embed_calls == calls


def test_rows_are_re_embedded_when_the_model_changes(tmp_path, monkeypatch, ollama):
    monkeypatch.setenv(MEMORY_EMBEDDER_ENV, "hash")
    store = _store(tmp_path)
    monkeypatch.setenv(MEMORY_EMBEDDER_ENV, "auto")
    reset_memory_embedder_cache()

    store.search_memories("what vehicle do I drive")

    with store._connect() as conn:
        models = {
            row["model"] for row in conn.execute("SELECT model FROM memory_embeddings")
        }
    assert models == {"ollama:nomic-embed-text:latest"}


def test_context_includes_a_paraphrased_match(tmp_path, ollama) -> None:
    context = build_personal_memory_context(
        "what vehicle do I drive", store=_store(tmp_path)
    )
    assert "Hyundai" in context
    assert "Priya" not in context


def test_unmatched_personal_question_says_i_dont_know(tmp_path, ollama) -> None:
    context = build_personal_memory_context(
        "what is my blood group", store=_store(tmp_path)
    )
    assert "say you don't know" in context
    assert "Hyundai" not in context


def test_unmatched_non_question_adds_nothing(tmp_path) -> None:
    assert build_personal_memory_context("tell a joke", store=_store(tmp_path)) == ""


def test_recall_with_nothing_relevant_says_i_dont_know(tmp_path) -> None:
    result = memory_context._recall(MemoryStore(tmp_path / "m.db"), "zebra stripes")
    assert result.message.startswith("I don't know")


def test_recall_test_measures_the_personal_backend(tmp_path) -> None:
    adapter = PersonalMemoryAdapter(tmp_path / "personal_memory.db")
    report = run_recall_test(adapter)
    adapter.close()

    assert adapter.embedding_model == HASH_EMBEDDER.model
    assert report.stored == 12
    assert report.recall_at_1("direct") >= 0.9


def test_recall_test_with_ollama_reports_the_ollama_model(tmp_path, ollama) -> None:
    adapter = PersonalMemoryAdapter(tmp_path / "personal_memory.db")
    run_recall_test(adapter)
    adapter.close()
    assert adapter.embedding_model == "ollama:nomic-embed-text:latest"


def test_recall_test_cli_accepts_the_personal_backend() -> None:
    from grandpa.cli import cli

    result = CliRunner().invoke(cli, ["memory", "recall-test", "--help"])
    assert "personal" in result.output


def test_context_min_score_default_is_above_zero() -> None:
    from grandpa.core.config import StorageConfig

    assert StorageConfig().context_min_score > 0


def test_sqlite_ignores_stop_words_so_unrelated_questions_find_nothing(tmp_path):
    from grandpa.tools.storage.context import ContextConfig, inject_context
    from grandpa.tools.storage.sqlite import SQLiteMemory

    backend = SQLiteMemory(db_path=str(tmp_path / "m.db"))
    backend.store("My car is a blue Hyundai i20", source="car")
    backend.store("I prefer tea over coffee in the morning", source="drink")
    try:
        assert backend.retrieve("what vehicle do I drive", top_k=5) == []
        assert backend.retrieve("what car do I have", top_k=5)[0].source == "car"
        cfg = ContextConfig(min_score=0.01)
        assert inject_context("what vehicle do I drive", [], backend, config=cfg) == []
    finally:
        backend.close()
