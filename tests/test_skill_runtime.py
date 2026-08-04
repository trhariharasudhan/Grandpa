from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.server.api_routes import skills_router
from grandpa.skills.registry import (
    SkillRegistryError,
    clear_skills,
    ensure_default_skills_registered,
    execute_skill,
    get_skill,
    list_categories,
    register_skill,
)
from grandpa.skills.runtime import RuntimeSkill, SkillExecutionContext, SkillResult


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_skills()
    yield
    clear_skills()


def test_register_duplicate_skill_is_blocked():
    skill = RuntimeSkill(
        name="test.echo",
        description="Echo test",
        category="system",
        risk_level="LOW",
        approval_required=False,
        executor=lambda params, context: SkillResult(
            ok=True, status="completed", message="ok"
        ),
    )
    register_skill(skill)

    with pytest.raises(SkillRegistryError):
        register_skill(skill)


def test_default_skills_register_and_execute_pc_summary(monkeypatch):
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

        return Response()

    monkeypatch.setattr("grandpa.pc_control.run_local_action", fake_run_local_action)
    ensure_default_skills_registered()

    skill = get_skill("desktop summary")
    assert skill.name == "desktop.summary"
    assert "desktop" in {item["name"] for item in list_categories()}

    result = execute_skill(
        "desktop.summary", context=SkillExecutionContext(source="test", dry_run=True)
    )
    assert result.ok is True
    assert result.message == "Desktop summary ready."
    assert result.data["evidence"]["monitors"] == 1


def test_approval_required_skill_does_not_execute_without_approval():
    called = False

    def executor(params, context):
        nonlocal called
        called = True
        return SkillResult(ok=True, status="completed", message="typed")

    register_skill(
        RuntimeSkill(
            name="desktop.type_test",
            description="Type test",
            category="desktop",
            risk_level="MEDIUM",
            approval_required=True,
            executor=executor,
        )
    )

    result = execute_skill(
        "desktop.type_test", context=SkillExecutionContext(source="test")
    )
    assert result.status == "approval_required"
    assert result.approval_required is True
    assert called is False


def test_skills_api_lists_gets_executes_and_categorizes(monkeypatch):
    def fake_run_local_action(payload):
        class Response:
            ok = True
            status = "completed"
            message = "Diagnostics ready."
            evidence = {"ready": True}
            action_id = None
            risk_level = "LOW"
            approval_required = False
            error = None

        return Response()

    monkeypatch.setattr("grandpa.pc_control.run_local_action", fake_run_local_action)
    app = FastAPI()
    app.include_router(skills_router)
    client = TestClient(app)

    listed = client.get("/v1/skills")
    assert listed.status_code == 200
    body = listed.json()
    assert body["runtime"]["runtime_ready"] is True
    assert any(item["name"] == "desktop.summary" for item in body["skills"])

    categories = client.get("/v1/skills/categories")
    assert categories.status_code == 200
    assert any(item["name"] == "desktop" for item in categories.json()["categories"])

    detail = client.get("/v1/skills/desktop.summary")
    assert detail.status_code == 200
    assert detail.json()["name"] == "desktop.summary"

    executed = client.post(
        "/v1/skills/execute", json={"name": "desktop.summary", "source": "test"}
    )
    assert executed.status_code == 200
    assert executed.json()["ok"] is True
