from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa import pc_control
from grandpa.desktop.kernel import diagnostics
from grandpa.desktop.kernel.requests import coerce_request, validate_request
from grandpa.desktop.kernel.risk import classify, requires_approval
from grandpa.pc_control import LocalActionRequest, run_local_action
from grandpa.server.routes import router


def test_kernel_request_and_risk_facades_preserve_behavior():
    request = coerce_request({"action_type": "file_delete", "target": "note.txt"})

    assert isinstance(request, LocalActionRequest)
    assert validate_request(request)["valid"] is True
    assert classify(request) == "HIGH"
    assert requires_approval(request) is True


def test_pc_control_facade_still_runs_dry_run():
    result = run_local_action(
        {"action_type": "open_app", "target": "notepad", "dry_run": True}
    )

    assert result.ok is True
    assert result.status == "dry_run"
    assert result.risk_level == "LOW"


def test_kernel_diagnostics_shape(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_RETENTION_CONFIG", str(tmp_path / "retention.json")
    )
    pc_control.reset_emergency_stop()

    data = diagnostics()

    assert data["status"] == "ready"
    assert "approvals" in data
    assert "audits" in data
    assert "risk" in data
    assert "execution" in data
    assert data["emergency"]["active"] is False


def test_desktop_kernel_api_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_RETENTION_CONFIG", str(tmp_path / "retention.json")
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/v1/desktop/kernel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["approvals"]["persistent"] is True
