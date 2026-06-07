from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.server.api_routes import release_gate_router


def test_release_gate_status_not_run(monkeypatch, tmp_path):
    import grandpa.release_gate as release_gate

    monkeypatch.setattr(release_gate, "REPORT_PATH", tmp_path / "missing.json")

    status = release_gate.release_gate_status()

    assert status["overall_status"] == "NOT RUN"
    assert status["pass"] is False


def test_release_gate_api_reads_latest_report(monkeypatch, tmp_path):
    import grandpa.release_gate as release_gate

    report = tmp_path / "final-release-gate.json"
    report.write_text(
        json.dumps(
            {
                "overall_status": "READY",
                "pass": True,
                "ready_to_commit": True,
                "ready_to_push": False,
                "ready_to_package": True,
                "recommendation": "Commit first.",
                "summary": {"passed": 3, "warnings": 1, "blockers": 0, "skipped_optional": 1},
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(release_gate, "REPORT_PATH", report)
    app = FastAPI()
    app.include_router(release_gate_router)
    client = TestClient(app)

    latest = client.get("/v1/release-gate/latest")
    status = client.get("/v1/release-gate/status")

    assert latest.status_code == 200
    assert latest.json()["overall_status"] == "READY"
    assert status.status_code == 200
    assert status.json()["ready_to_commit"] is True
