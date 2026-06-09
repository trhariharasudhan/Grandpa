from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.server.api_routes import audit_router


def test_latest_production_audit_handles_missing_report(tmp_path, monkeypatch):
    import grandpa.production_audit as audit

    monkeypatch.setattr(audit, "JSON_REPORT", tmp_path / "missing.json")
    monkeypatch.setattr(audit, "MD_REPORT", tmp_path / "missing.md")

    report = audit.latest_report()

    assert report["overall_status"] == "not_run"
    assert report["pass"] is False


def test_production_audit_report_preserves_hardware_pending(tmp_path, monkeypatch):
    import grandpa.production_audit as audit

    monkeypatch.setattr(audit, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(audit, "JSON_REPORT", tmp_path / "production-audit.json")
    monkeypatch.setattr(audit, "MD_REPORT", tmp_path / "production-audit.md")

    report = audit._build_report(
        [
            audit.AuditCheck("Agent", "Planner", "validated", "ok"),
            audit.AuditCheck("Voice", "Mic", "unvalidated", "No mic observed.", hardware_dependent=True),
        ],
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:01+00:00",
        1.0,
    )
    audit._write_reports(report)

    loaded = json.loads((tmp_path / "production-audit.json").read_text(encoding="utf-8"))
    assert loaded["overall_status"] == "READY_WITH_HARDWARE_PENDING"
    assert loaded["summary"]["unvalidated"] == 1
    assert "hardware" in loaded["recommendation"].lower()
    assert "Grandpa Production Audit" in (tmp_path / "production-audit.md").read_text(encoding="utf-8")


def test_production_audit_api_reads_latest_report(tmp_path, monkeypatch):
    import grandpa.production_audit as audit

    report_path = tmp_path / "production-audit.json"
    report_path.write_text(
        json.dumps(
            {
                "overall_status": "READY_WITH_HARDWARE_PENDING",
                "pass": True,
                "score": 82,
                "core_score": 100,
                "readiness_verdict": "Core ready.",
                "recommendation": "Validate hardware.",
                "summary": {"validated": 1, "partially_validated": 0, "unvalidated": 1, "blocked": 0, "hardware_dependent": 1, "total": 2},
                "feature_matrix": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "JSON_REPORT", report_path)
    app = FastAPI()
    app.include_router(audit_router)
    client = TestClient(app)

    latest = client.get("/v1/audit/latest")
    status = client.get("/v1/audit/status")

    assert latest.status_code == 200
    assert latest.json()["score"] == 82
    assert status.status_code == 200
    assert status.json()["core_score"] == 100
