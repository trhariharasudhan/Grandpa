from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.advanced_ai import build_plan, choose_model, classify_task
from grandpa.core.types import Message
from grandpa.server.routes import router


class FakeEngine:
    engine_id = "fake"

    def __init__(self):
        self.calls: list[str] = []

    def list_models(self):
        return ["qwen2.5:3b", "nomic-embed-text:latest", "gpt-5-mini"]

    def health(self):
        return True

    def generate(self, messages: list[Message], *, model: str, **kwargs):
        self.calls.append(model)
        return {"content": f"used {model}", "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}


def _client(engine: FakeEngine | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine or FakeEngine()
    app.state.model = "qwen2.5:3b"
    app.state.engine_name = "fake"
    app.state.agent = None
    return TestClient(app)


def test_task_classifier_recognizes_major_capabilities():
    assert classify_task("open chrome") == "pc_control"
    assert classify_task("summarize this webpage") == "browser"
    assert classify_task("what is on my screen") == "screen"
    assert classify_task("remember my project is Grandpa") == "memory"
    assert classify_task("create a morning routine") == "workflow"


def test_choose_model_prefers_available_requested_model():
    decision = choose_model(
        "What is Python?",
        requested_model="qwen2.5:3b",
        available_models=["qwen2.5:3b", "gpt-5-mini"],
        cloud_allowed=True,
    )

    assert decision.selected_model == "qwen2.5:3b"
    assert not decision.fallback_used


def test_choose_model_falls_back_to_local_chat_model():
    decision = choose_model(
        "What is Python?",
        requested_model="missing-model",
        available_models=["nomic-embed-text:latest", "qwen2.5:3b"],
    )

    assert decision.selected_model == "qwen2.5:3b"
    assert decision.fallback_used
    assert decision.engine_hint == "local"


def test_complex_reasoning_can_use_cloud_when_allowed():
    decision = choose_model(
        "Analyze this strategy, compare trade-offs, and produce a detailed plan.",
        requested_model="missing-model",
        available_models=["qwen2.5:3b", "gpt-5-mini"],
        cloud_allowed=True,
    )

    assert decision.selected_model in {"gpt-5-mini", "qwen2.5:3b"}
    assert decision.task_type == "reasoning"


def test_plan_decomposes_browser_workflow():
    plan = build_plan(
        "open YouTube and search for Python tutorials",
        requested_model="qwen2.5:3b",
        available_models=["qwen2.5:3b"],
    )

    assert plan.task_type == "browser"
    assert "browser_control" in plan.tool_order
    assert any(step.risk == "MEDIUM" for step in plan.steps)
    assert plan.self_analysis


def test_ai_diagnostics_route_returns_planner_summary():
    response = _client().get("/v1/ai/diagnostics?query=summarize%20this%20webpage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["planner"]["enabled"] is True
    assert payload["planner"]["last_plan"]["task_type"] == "browser"


def test_ai_plan_route_is_read_only():
    response = _client().post(
        "/v1/ai/plan",
        json={"query": "what is on my screen", "model": "missing-model"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_type"] == "screen"
    assert payload["routing"]["selected_model"] == "qwen2.5:3b"


def test_chat_route_uses_model_fallback():
    engine = FakeEngine()
    response = _client(engine).post(
        "/v1/chat/completions",
        json={
            "model": "missing-model",
            "messages": [{"role": "user", "content": "What is Python?"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "qwen2.5:3b"
    assert engine.calls == ["qwen2.5:3b"]
