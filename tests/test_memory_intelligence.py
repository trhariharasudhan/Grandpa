from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.memory.intelligence import (
    build_relationship_graph,
    calculate_memory_relevance,
    cluster_memory_topics,
    detect_user_preference,
    ranked_memory_context,
    score_memory_importance,
    summarize_memory_profile,
)
from grandpa.memory_context import MemoryStore, handle_memory_command
from grandpa.planner.engine import analyze_request
from grandpa.server.routes import router
from grandpa.skills.registry import (
    clear_skills,
    ensure_default_skills_registered,
    execute_skill,
)


def _store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path / "memory.db")
    store.remember("project", "project", "Grandpa", source="test")
    store.remember("apps_tools", "uses_vs_code", "VS Code", source="test")
    store.remember("apps_tools", "uses_python", "Python", source="test")
    store.remember("preferences", "preferred_framework", "FastAPI", source="test")
    store.remember("preferences", "preferred_os", "Windows", source="test")
    return store


def test_importance_scoring_prefers_core_context(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memory = store.list_memories()[0]

    assert score_memory_importance(memory) >= 0.5
    assert calculate_memory_relevance(memory, "what project am I building") > 0


def test_preference_detection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memories = store.list_memories()

    preferences = [detect_user_preference(item) for item in memories]

    assert any(item and item["value"] == "VS Code" for item in preferences)
    assert any(item and item["value"] == "Grandpa" for item in preferences)


def test_relationship_graph_and_topic_clustering(tmp_path: Path) -> None:
    store = _store(tmp_path)

    graph = build_relationship_graph(store)
    topics = cluster_memory_topics(store)

    assert any(node["id"] == "Grandpa" for node in graph["nodes"])
    assert graph["edges"]
    assert any(
        topic["name"] in {"Development", "AI", "Projects"} for topic in topics["topics"]
    )


def test_ranked_context_and_profile(tmp_path: Path) -> None:
    store = _store(tmp_path)

    context = ranked_memory_context("what editor do I prefer", store=store)
    profile = summarize_memory_profile(store)

    assert context["available"] is True
    assert context["matches"]
    assert context["confidence"] > 0
    assert profile["preference_count"] >= 3
    assert "Grandpa has" in profile["summary"]


def test_memory_commands_use_intelligence(tmp_path: Path) -> None:
    store = _store(tmp_path)

    profile = handle_memory_command("what do you know about me?", store=store)
    prefs = handle_memory_command("summarize my preferences", store=store)
    projects = handle_memory_command("what projects am I working on?", store=store)

    assert profile.status == "handled"
    assert "Grandpa" in profile.message
    assert "VS Code" in prefs.message
    assert "Grandpa" in projects.message


def test_planner_uses_memory_intelligence(tmp_path: Path, monkeypatch) -> None:
    _store(tmp_path)

    def fake_ranked(query: str, limit: int = 3, store: MemoryStore | None = None):
        return ranked_memory_context(
            query, limit=limit, store=store or _store(tmp_path)
        )

    monkeypatch.setattr(
        "grandpa.memory.intelligence.ranked_memory_context", fake_ranked
    )

    analysis = analyze_request("research Python tutorials and summarize them")

    assert analysis.memory_context["source"] == "memory_intelligence"
    assert "confidence" in analysis.memory_context


def test_memory_skills(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr("grandpa.memory_context.MemoryStore", lambda: store)
    clear_skills()
    ensure_default_skills_registered()

    profile = execute_skill("memory.profile")
    preferences = execute_skill("memory.preferences")
    topics = execute_skill("memory.topic_summary")

    assert profile.ok
    assert preferences.ok
    assert topics.ok


def test_memory_intelligence_api(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr("grandpa.memory_context.MemoryStore", lambda: store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    assert client.get("/v1/memory/profile").status_code == 200
    prefs = client.get("/v1/memory/preferences")
    graph = client.get("/v1/memory/relationships")
    insights = client.get("/v1/memory/insights")
    topics = client.get("/v1/memory/topics")

    assert prefs.json()["count"] >= 3
    assert graph.json()["nodes"]
    assert insights.json()["status"] == "ready"
    assert topics.json()["topics"]
