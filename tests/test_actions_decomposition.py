from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.actions import (
    action_audit_summary,
    action_diagnostics,
    reset_action_diagnostics,
)
from grandpa.local_actions import handle_local_action
from grandpa.server.api_routes import actions_router


def test_action_audit_summary_classifies_domains():
    summary = action_audit_summary()

    assert summary["desktop"].startswith("partially migrated")
    assert summary["browser"].startswith("partially migrated")
    assert summary["memory"] == "legacy"
    assert "coverage" in summary


def test_migrated_read_only_handlers_preserve_dry_run_shape():
    reset_action_diagnostics()

    desktop = handle_local_action("desktop summary", execute=False)
    browser = handle_local_action("browser diagnostics", execute=False)
    vision = handle_local_action("visual targeting diagnostics", execute=False)

    assert desktop.status == "handled"
    assert desktop.kind == "pc_control"
    assert desktop.target == "desktop_summary|desktop"
    assert browser.kind == "browser"
    assert browser.target == "diagnostics|browser"
    assert vision.kind == "screen"
    assert vision.target == "visual_diagnostics"

    diagnostics = action_diagnostics()
    assert diagnostics["migrated_route_count"] >= 3
    assert diagnostics["fallback_count"] == 0


def test_unknown_command_still_uses_legacy_fallback():
    reset_action_diagnostics()

    result = handle_local_action("What is Python?", execute=False)

    assert result.status == "no_match"
    assert result.should_fallback
    assert action_diagnostics()["fallback_count"] >= 1


def test_actions_diagnostics_api():
    app = FastAPI()
    app.include_router(actions_router)
    client = TestClient(app)

    response = client.get("/v1/actions/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["migrated_count"] > 0
    assert "legacy_handlers" in body
