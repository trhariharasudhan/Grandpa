from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.router import (
    analyze_intent,
    reset_router_diagnostics,
    route_local_intent,
    router_diagnostics,
)
from grandpa.server.api_routes import intent_router
from grandpa.skills.registry import clear_skills


def setup_function() -> None:
    clear_skills()
    reset_router_diagnostics()


def teardown_function() -> None:
    clear_skills()
    reset_router_diagnostics()


def test_read_only_desktop_route_maps_to_runtime_skill():
    route = analyze_intent("desktop summary")

    assert route.intent == "desktop_summary"
    assert route.category == "desktop"
    assert route.skill_name == "desktop.summary"
    assert route.risk_level == "LOW"
    assert route.approval_required is False


def test_skill_route_executes_through_registry(monkeypatch):
    def fake_run_local_action(payload):
        class Response:
            ok = True
            status = "completed"
            message = "Desktop summary ready."
            evidence = {"monitors": 1}
            action_id = None
            risk_level = "LOW"
            approval_required = False
            error = None

        assert payload["action_type"] == "desktop_summary"
        return Response()

    monkeypatch.setattr("grandpa.pc_control.run_local_action", fake_run_local_action)

    result = route_local_intent("desktop summary")

    assert result is not None
    assert result.status == "handled"
    assert result.message == "Desktop summary ready."
    diagnostics = router_diagnostics()
    assert diagnostics["skill_routed_count"] == 1


def test_approval_required_command_stays_on_legacy_path():
    route = analyze_intent("type hello")

    assert route.execution_source == "fallback"
    assert route.fallback_reason
    assert route_local_intent("type hello") is None


def test_planner_route_is_detected_without_executing_tools():
    route = analyze_intent("start my coding workspace")

    assert route.execution_source == "planner"
    assert route.category == "planner"
    assert route.planner_suitable is True
    assert "desktop.summary" in route.params["required_skills"]


def test_planner_routing_respects_disabled_memory_context(monkeypatch):
    observed = {}

    def fake_analyze_request(_text, *, include_memory=True):
        observed["include_memory"] = include_memory
        return SimpleNamespace(
            confidence=0.0,
            steps=(),
            estimated_risk="LOW",
        )

    config = SimpleNamespace(agent=SimpleNamespace(context_from_memory=False))
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: config)
    monkeypatch.setattr("grandpa.planner.analyze_request", fake_analyze_request)

    analyze_intent("an unmatched conversational request")

    assert observed["include_memory"] is False


def test_router_api_analyzes_and_reports_diagnostics():
    app = FastAPI()
    app.include_router(intent_router)
    client = TestClient(app)

    analyzed = client.post(
        "/v1/router/analyze", json={"request": "browser diagnostics"}
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["skill_name"] == "browser.diagnostics"

    diagnostics = client.get("/v1/router/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["status"] == "ready"
    assert "browser diagnostics" in diagnostics.json()["skill_routes"]
