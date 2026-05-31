from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa import pc_control
from grandpa.server.routes import router


@pytest.fixture(autouse=True)
def _isolated_pc_control_api(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_RETENTION_CONFIG", str(tmp_path / "retention.json"))
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_local_action_endpoint_schema_for_safe_dry_run(client: TestClient):
    response = client.post(
        "/api/local-action",
        json={"action_type": "open_app", "target": "notepad", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "dry_run"
    assert body["approval_required"] is False
    assert body["risk_level"] == "LOW"
    assert set(body) == {"ok", "action_id", "status", "message", "approval_required", "risk_level", "evidence", "error"}


def test_local_action_endpoint_approval_reject_flow(client: TestClient, tmp_path: Path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")

    create_response = client.post("/api/local-action", json={"action_type": "file_delete", "target": str(target)})
    pending = create_response.json()

    assert create_response.status_code == 200
    assert pending["approval_required"] is True
    assert pending["risk_level"] == "HIGH"
    assert target.exists()

    pending_list = client.get("/api/local-action/pending").json()
    assert pending_list["actions"][0]["action_id"] == pending["action_id"]
    assert pending_list["actions"][0]["decision"] == "pending"
    approvals = client.get("/api/local-action/approvals").json()
    assert approvals["actions"][0]["action_id"] == pending["action_id"]
    assert approvals["storage"]["backend"] == "sqlite"
    assert approvals["storage"]["persistent"] is True
    assert approvals["retention"]["approval_retention_days"] == 30
    assert approvals["maintenance"]["storage_healthy"] is True

    reject_response = client.post(f"/api/local-action/{pending['action_id']}/reject")
    rejected = reject_response.json()

    assert reject_response.status_code == 200
    assert rejected["status"] == "rejected"
    assert target.exists()


def test_local_action_endpoint_approval_execute_flow(client: TestClient, tmp_path: Path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")

    pending = client.post("/api/local-action", json={"action_type": "file_delete", "target": str(target)}).json()
    approved = client.post(f"/api/local-action/{pending['action_id']}/approve").json()

    assert approved["ok"] is True
    assert approved["status"] == "completed"
    assert not target.exists()


def test_local_action_endpoint_emergency_stop_cancels_pending(client: TestClient, tmp_path: Path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = client.post("/api/local-action", json={"action_type": "file_delete", "target": str(target)}).json()

    stopped = client.post("/api/local-action/emergency-stop").json()
    approved = client.post(f"/api/local-action/{pending['action_id']}/approve").json()

    assert stopped["ok"] is True
    assert stopped["evidence"]["cancelled_pending_actions"] == 1
    assert approved["ok"] is False
    assert target.exists()


def test_local_action_audit_endpoint_returns_redacted_entries(client: TestClient, monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        type("FakeClipboard", (), {"copy": staticmethod(lambda _text: None), "paste": staticmethod(lambda: "secret")})(),
    )

    client.post("/api/local-action", json={"action_type": "clipboard_write", "target": "secret"})
    body = client.get("/api/local-action/audit?limit=10").json()

    assert body["entries"]
    assert body["entries"][-1]["target"] == "[redacted]"
    assert "secret" not in str(body["entries"])


def test_local_action_health_endpoint(client: TestClient):
    body = client.get("/api/local-action/health").json()

    assert body["storage"]["backend"] == "sqlite"
    assert body["retention"]["approval_retention_days"] == 30
    assert body["maintenance"]["cleanup_completed"] is True
    assert "pending" in body["counts"]
