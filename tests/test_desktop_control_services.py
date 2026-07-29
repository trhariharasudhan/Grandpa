from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa import pc_control
from grandpa.desktop.control import (
    desktop_control_diagnostics,
    get_application_service,
    list_desktop_services,
)
from grandpa.desktop.control.applications import ApplicationControlService
from grandpa.server.routes import router
from grandpa.windows_app_resolver import AppResolution
from grandpa.windows_window_control import (
    NotepadDocumentInfo,
    NotepadDocumentTarget,
    WindowInfo,
)


def test_desktop_control_registry_lists_domain_services():
    services = list_desktop_services(platform="linux")
    names = {service["service"] for service in services}

    assert {
        "applications",
        "windows",
        "clipboard",
        "monitors",
        "diagnostics",
        "files",
        "automation",
        "power",
    } <= names
    info = desktop_control_diagnostics(platform="linux")
    assert info["service_count"] == len(services)
    assert "applications" in info["support_matrix"]


def test_application_service_preserves_safe_aliases():
    service = get_application_service()

    assert service.app_id("VS Code") == "vscode"
    assert service.app_id("unknown app") is None


def test_application_service_verifies_new_notepad_document(monkeypatch):
    existing = NotepadDocumentTarget(
        WindowInfo(10, "Existing - Notepad", "notepad", 101),
        NotepadDocumentInfo("doc-old", "Existing", True, True, 0),
    )
    created = NotepadDocumentTarget(
        WindowInfo(10, "Untitled - Notepad", "notepad", 101),
        NotepadDocumentInfo("doc-new", "Untitled", False, True, 1),
    )
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda _app: AppResolution(
            "notepad",
            "Notepad",
            "found",
            "path",
            "notepad.exe",
            "test",
            "Found Notepad.",
        ),
    )
    monkeypatch.setattr(
        "grandpa.windows_window_control.snapshot_notepad_documents",
        lambda: (existing,),
    )
    monkeypatch.setattr(
        "grandpa.windows_window_control.create_new_notepad_document",
        lambda: ("created", created),
    )

    result = ApplicationControlService().execute(
        pc_control.LocalActionRequest(
            "open_app",
            "notepad",
            {"new_instance": True},
        ),
        "open_app",
    )

    assert result.ok is True
    assert result.message == "Opened a new Notepad document."
    assert result.evidence["launch_target"]["document_id"] == "doc-new"


def test_pc_control_facade_still_detects_app(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db"))
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda _app: AppResolution("chrome", "Chrome", "found", "path", "chrome.exe", "test", "Found Chrome."),
    )

    result = pc_control.run_local_action({"action_type": "detect_app", "target": "chrome"})

    assert result.ok is True
    assert result.evidence["app_id"] == "chrome"


def test_power_actions_still_require_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db"))

    result = pc_control.run_local_action({"action_type": "system_shutdown"})

    assert result.status == "approval_required"
    assert result.risk_level == "HIGH"
    assert result.approval_required is True


def test_desktop_service_api_endpoints():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    diagnostics = client.get("/v1/desktop/diagnostics")
    services = client.get("/v1/desktop/services")

    assert diagnostics.status_code == 200
    assert services.status_code == 200
    assert diagnostics.json()["service_count"] >= 8
    assert services.json()["local_only"] is True
