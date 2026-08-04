from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.desktop.operator import (
    analyze_desktop_task,
    build_ui_navigation_plan,
    execute_visual_step,
    operator_diagnostics,
    recover_failed_action,
)
from grandpa.server.api_routes import desktop_operator_router
from grandpa.skills.registry import (
    ensure_default_skills_registered,
    execute_skill,
    get_skill,
)


def test_app_profile_detection_for_vscode_terminal() -> None:
    analysis = analyze_desktop_task("open terminal in VS Code")

    assert analysis["app"] == "vscode"
    assert analysis["intent"] == "open_vscode_terminal"
    assert analysis["risk_level"] == "MEDIUM"
    assert analysis["approval_required"] is True
    assert analysis["supported"] is True


def test_plan_generation_marks_risky_steps_for_approval(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_DESKTOP_OPERATOR_DB", str(tmp_path / "operator.db"))

    plan = build_ui_navigation_plan("open terminal in VS Code")

    assert plan["task"]["status"] == "waiting_approval"
    assert plan["task"]["approvals"]
    assert any(step["approval_required"] for step in plan["plan"])


def test_summarize_current_desktop_state_is_read_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_DESKTOP_OPERATOR_DB", str(tmp_path / "operator.db"))

    plan = build_ui_navigation_plan("summarize current desktop state")

    assert plan["task"]["status"] == "planned"
    assert plan["plan"][0]["action_type"] == "observe"
    assert plan["plan"][0]["risk_level"] == "LOW"


def test_low_confidence_visual_step_is_blocked() -> None:
    result = execute_visual_step(
        {
            "action_type": "mouse_click",
            "risk_level": "LOW",
            "visual_target": {"label": "Continue", "confidence": 0.2},
        },
        dry_run=True,
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"


def test_approval_required_step_does_not_execute_without_confirmation() -> None:
    result = execute_visual_step(
        {
            "action_type": "keyboard_type",
            "target": "hello",
            "params": {"text": "hello"},
            "risk_level": "MEDIUM",
            "approval_required": True,
            "visual_target": {"label": "editor", "confidence": 0.9},
        },
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["status"] == "approval_required"


def test_retry_limit_is_bounded() -> None:
    result = recover_failed_action(
        {"step_id": "click"}, {"status": "failed"}, retry_count=2
    )

    assert result["retry_allowed"] is False
    assert result["status"] == "failed"


def test_operator_diagnostics_contract(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_DESKTOP_OPERATOR_DB", str(tmp_path / "operator.db"))

    diagnostics = operator_diagnostics()

    assert diagnostics["ready"] is True
    assert diagnostics["profile_count"] >= 5
    assert diagnostics["visual_targeting"]["pixel_perfect_claimed"] is False
    assert diagnostics["safety"]["blind_clicking_allowed"] is False


def test_operator_api_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_DESKTOP_OPERATOR_DB", str(tmp_path / "operator.db"))
    app = FastAPI()
    app.include_router(desktop_operator_router)
    client = TestClient(app)

    diagnostics = client.get("/v1/desktop/operator/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["ready"] is True

    plan = client.post(
        "/v1/desktop/operator/plan",
        json={"request": "summarize current desktop state", "persist": False},
    )
    assert plan.status_code == 200
    assert plan.json()["task"]["status"] == "planned"

    profiles = client.get("/v1/desktop/operator/profiles")
    assert profiles.status_code == 200
    assert profiles.json()["count"] >= 5


def test_operator_skills_registered(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_DESKTOP_OPERATOR_DB", str(tmp_path / "operator.db"))
    ensure_default_skills_registered()

    assert get_skill("desktop.operator_diagnostics") is not None
    assert get_skill("desktop.operator_plan") is not None

    result = execute_skill(
        "desktop.operator_plan",
        {"request": "summarize current desktop state", "persist": False},
    )
    assert result.ok is True
    assert result.data["task"]["status"] == "planned"
