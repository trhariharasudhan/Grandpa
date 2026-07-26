from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.knowledge.embeddings import KnowledgeEmbedder, deterministic_embedding
from grandpa.knowledge.engine import (
    KnowledgeEngine,
    knowledge_diagnostics,
    planner_knowledge_context,
)
from grandpa.knowledge.indexing import chunk_text, infer_tags, tokenize
from grandpa.knowledge.storage import KnowledgeStore
from grandpa.server.api_routes import knowledge_router
from grandpa.skills.registry.core import get_skill
from grandpa.skills.registry.defaults import ensure_default_skills_registered
from grandpa.skills.runtime import SkillExecutionContext


@pytest.fixture(autouse=True)
def force_fast_fallback_embeddings(monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "fallback")


def test_indexing_chunks_and_tags():
    text = "Grandpa uses Python and FastAPI for local AI assistant workflows. " * 40
    chunks = chunk_text(text, max_words=40, overlap=5)
    tags = infer_tags("docs/architecture.md", text)

    assert len(chunks) > 1
    assert "python" in tokenize(text)
    assert "development" in tags
    assert "docs" in tags


def test_import_search_and_document_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    store = KnowledgeStore(tmp_path / "knowledge.db")
    engine = KnowledgeEngine(store)

    imported = engine.import_document(
        source="manual:test",
        title="Grandpa Architecture",
        content="Grandpa is a local-first assistant. It uses Python, FastAPI, memory, and workflows.",
        tags=["project"],
    )
    document_id = imported["document"]["document_id"]

    results = engine.search("FastAPI workflows")
    summary = engine.summary(document_id=document_id)

    assert imported["status"] == "imported"
    assert results["results"][0]["document_id"] == document_id
    assert "Grandpa is a local-first assistant" in summary["summary"]
    assert engine.embedding_status()["embedding_count"] >= 1


def test_deterministic_embedding_fallback_is_stable():
    first = deterministic_embedding("Grandpa local knowledge retrieval")
    second = deterministic_embedding("Grandpa local knowledge retrieval")

    assert first == second
    assert len(first) == 128
    assert KnowledgeEmbedder(model="missing-model-for-test").embed("hello").true_semantic is False


def test_semantic_and_hybrid_search_explain_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    engine = KnowledgeEngine(KnowledgeStore(tmp_path / "knowledge.db"))
    engine.import_document(
        source="manual:semantic",
        title="FastAPI Backend Notes",
        content="FastAPI powers Grandpa API routes, planners, skills, and workflow services.",
        tags=["project", "development"],
    )

    semantic = engine.semantic_search("API planner services")
    hybrid = engine.search("API planner services")

    assert semantic["results"]
    assert semantic["semantic_mode"] in {"ollama", "deterministic_fallback"}
    assert "truthful_note" in semantic
    assert hybrid["results"][0]["ranking_explanation"]
    assert hybrid["retrieval"] == "hybrid_keyword_semantic_recency"


def test_knowledge_context_and_related_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    engine = KnowledgeEngine(KnowledgeStore(tmp_path / "knowledge.db"))
    first = engine.import_document(
        source="manual:one",
        title="Grandpa Browser Control",
        content="Browser control uses visible snapshots, links, buttons, and safe page summaries.",
        tags=["project", "browser"],
    )["document"]
    engine.import_document(
        source="manual:two",
        title="Grandpa Browser Agent",
        content="The browser agent plans searches and summarizes visible webpages safely.",
        tags=["project", "browser"],
    )

    context = engine.context("visible webpage summaries")
    related = engine.related(first["document_id"])

    assert context["chunks"]
    assert context["semantic_mode"] in {"ollama", "deterministic_fallback"}
    assert related["results"]


def test_recent_project_and_diagnostics(tmp_path):
    engine = KnowledgeEngine(KnowledgeStore(tmp_path / "knowledge.db"))
    engine.import_document(
        source="docs/project.md",
        title="Project Docs",
        content="This project document explains Grandpa setup and troubleshooting.",
        tags=["project", "docs"],
    )

    assert engine.recent()["documents"]
    assert engine.projects()["documents"]
    diagnostics = engine.diagnostics()
    assert diagnostics["retrieval"]["keyword"] is True
    assert diagnostics["retrieval"]["semantic_vector_search"] is True
    assert diagnostics["embeddings"]["true_semantic_available"] is False


def test_file_import_supports_txt_md_json(tmp_path):
    engine = KnowledgeEngine(KnowledgeStore(tmp_path / "knowledge.db"))
    note = tmp_path / "note.md"
    note.write_text("# Grandpa Note\n\nLocal knowledge indexing works.", encoding="utf-8")

    imported = engine.import_file(note)

    assert imported["document"]["title"] == "Grandpa Note"
    assert "md" in imported["document"]["tags"]


def test_planner_knowledge_context(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    engine = KnowledgeEngine()
    engine.import_document(
        source="manual:planner",
        title="Python Project",
        content="Python and FastAPI are used for Grandpa backend services.",
        tags=["project"],
    )

    context = planner_knowledge_context("FastAPI backend")

    assert context["available"] is True
    assert context["semantic_search"] is False
    assert context["chunks"]


def test_knowledge_skill_registration_and_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    KnowledgeEngine().import_document(
        source="manual:skill",
        title="Skill Knowledge",
        content="Knowledge skills search local indexed documents.",
        tags=["skills"],
    )
    ensure_default_skills_registered()

    skill = get_skill("knowledge.search")
    result = skill.execute({"query": "indexed documents"}, SkillExecutionContext(user_request="indexed documents"))

    assert result.ok is True
    assert result.data["results"]

    semantic = get_skill("knowledge.semantic_search").execute(
        {"query": "local indexed documents"},
        SkillExecutionContext(user_request="local indexed documents"),
    )
    context = get_skill("knowledge.context").execute(
        {"query": "local indexed documents"},
        SkillExecutionContext(user_request="local indexed documents"),
    )
    status = get_skill("knowledge.embedding_status").execute({}, SkillExecutionContext())
    assert semantic.ok is True
    assert context.ok is True
    assert status.data["embedding_count"] >= 1


def test_knowledge_api_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app)

    imported = client.post(
        "/v1/knowledge/import",
        json={
            "source": "manual:api",
            "title": "API Knowledge",
            "content": "Grandpa knowledge API stores local documents and retrieves them by keyword.",
            "tags": ["api"],
        },
    )
    assert imported.status_code == 200
    document_id = imported.json()["document"]["document_id"]

    assert client.get("/v1/knowledge/diagnostics").json()["document_count"] == 1
    assert client.get("/v1/knowledge/search?q=keyword").json()["results"]
    assert client.get("/v1/knowledge/semantic-search?q=keyword").json()["results"]
    assert client.get("/v1/knowledge/context?q=keyword").json()["chunks"]
    assert client.get("/v1/knowledge/embedding-status").json()["embedding_count"] >= 1
    assert client.get("/v1/knowledge/documents").json()["documents"]
    assert client.get(f"/v1/knowledge/document/{document_id}").json()["title"] == "API Knowledge"
    assert "summary" in client.get(f"/v1/knowledge/summary?document_id={document_id}").json()


def test_module_diagnostics_json_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    info = knowledge_diagnostics()
    assert info["status"] == "ready"


def test_planner_includes_knowledge_context(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    KnowledgeEngine().import_document(
        source="manual:planner-knowledge",
        title="Technical Project Context",
        content="Grandpa uses local SQLite knowledge retrieval and planner context.",
        tags=["project"],
    )
    from grandpa.planner.engine import analyze_request

    analysis = analyze_request("what knowledge retrieval does Grandpa use?")

    assert analysis.memory_context["knowledge"]["available"] is True
    assert analysis.memory_context["knowledge"]["chunks"]
