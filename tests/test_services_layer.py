from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.server.api_routes import (
    intent_router,
    planner_router,
    release_gate_router,
    services_router,
    skills_router,
)
from grandpa.services import service_diagnostics, service_names


def test_service_registry_reports_expected_facades():
    data = service_diagnostics()

    assert data["service_count"] >= 8
    assert "skills" in service_names()
    assert "planner" in service_names()
    assert "release_gate" in service_names()
    assert all("health" in service for service in data["services"])
    assert all("readiness" in service for service in data["services"])


def test_services_api_returns_diagnostics():
    app = FastAPI()
    app.include_router(services_router)
    client = TestClient(app)

    response = client.get("/v1/services")

    assert response.status_code == 200
    body = response.json()
    assert body["service_count"] == len(body["services"])
    assert any(service["name"] == "desktop" for service in body["services"])


def test_decomposed_skill_routes_keep_contract():
    app = FastAPI()
    app.include_router(skills_router)
    client = TestClient(app)

    listed = client.get("/v1/skills")
    categories = client.get("/v1/skills/categories")

    assert listed.status_code == 200
    assert "skills" in listed.json()
    assert "runtime" in listed.json()
    assert categories.status_code == 200
    assert "categories" in categories.json()


def test_decomposed_planner_and_router_routes_keep_contract():
    app = FastAPI()
    app.include_router(planner_router)
    app.include_router(intent_router)
    client = TestClient(app)

    planner = client.post("/v1/planner/analyze", json={"request": "desktop summary"})
    route = client.post("/v1/router/analyze", json={"request": "desktop summary"})

    assert planner.status_code == 200
    assert "intent" in planner.json()
    assert route.status_code == 200
    assert route.json()["request_text"] == "desktop summary"


def test_decomposed_release_routes_keep_contract(monkeypatch, tmp_path):
    import grandpa.release_gate as release_gate

    monkeypatch.setattr(release_gate, "REPORT_PATH", tmp_path / "missing.json")
    app = FastAPI()
    app.include_router(release_gate_router)
    client = TestClient(app)

    status = client.get("/v1/release-gate/status")

    assert status.status_code == 200
    assert status.json()["overall_status"] == "NOT RUN"
