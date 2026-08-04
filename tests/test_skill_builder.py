from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.local_actions import handle_local_action
from grandpa.server.api_routes import user_skills_router
from grandpa.skill_builder import (
    create_user_skill,
    delete_user_skill,
    diagnostics,
    list_user_skills,
    run_user_skill,
)
from grandpa.skill_builder.validator import (
    SkillValidationError,
    validate_skill_definition,
)
from grandpa.skills.registry import ensure_default_skills_registered, get_skill


def test_create_user_skill_uses_safe_template(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))

    created = create_user_skill({"name": "start coding session"})
    skill = created["skill"]

    assert skill["name"] == "start coding session"
    assert skill["trigger_phrases"] == ["start coding session"]
    assert skill["workflow_steps"]
    assert all(
        step["schema_version"] == "skill_graph_v2" for step in skill["workflow_steps"]
    )


def test_validator_rejects_shell_like_skills() -> None:
    try:
        validate_skill_definition(
            {
                "name": "run shell command",
                "trigger_phrases": ["run shell command"],
                "workflow_steps": [{"skill": "system.shell", "params": {}}],
            }
        )
    except SkillValidationError as exc:
        assert "unsafe" in str(exc).lower() or "blocked" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("unsafe skill was accepted")


def test_user_skill_registers_as_runtime_skill(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))
    create_user_skill({"name": "start coding session"})
    ensure_default_skills_registered()

    skill = get_skill("start coding session")

    assert skill.name == "user.start_coding_session"
    assert skill.category == "user"


def test_run_user_skill_records_usage(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))
    created = create_user_skill({"name": "desktop readiness"})

    result = run_user_skill(created["skill"]["skill_id"])
    listed = list_user_skills()["skills"][0]

    assert result["status"] == "completed"
    assert listed["usage_count"] == 1
    assert listed["success_count"] == 1


def test_user_skill_api_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))
    app = FastAPI()
    app.include_router(user_skills_router)
    client = TestClient(app)

    created = client.post(
        "/v1/user-skills/create", json={"name": "start coding session"}
    )
    assert created.status_code == 200
    skill_id = created.json()["skill"]["skill_id"]

    listed = client.get("/v1/user-skills")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    run = client.post(f"/v1/user-skills/{skill_id}/run", json={"dry_run": True})
    assert run.status_code == 200
    assert run.json()["status"] == "completed"

    diag = client.get("/v1/user-skills/diagnostics")
    assert diag.status_code == 200
    assert diag.json()["status"] == "ready"

    deleted = client.post(f"/v1/user-skills/{skill_id}/delete")
    assert deleted.status_code == 200


def test_local_action_creates_and_runs_user_skill(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))

    created = handle_local_action(
        "Create a skill called start coding session", execute=False
    )
    assert created.status == "handled"
    assert "Saved user skill" in created.message

    run = handle_local_action("start coding session", execute=False)
    assert run.status == "handled"
    assert "Ran user skill" in run.message


def test_delete_user_skill_hides_skill(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))
    created = create_user_skill({"name": "temporary skill"})

    deleted = delete_user_skill(created["skill"]["skill_id"])

    assert deleted["status"] == "deleted"
    assert list_user_skills()["count"] == 0


def test_diagnostics_are_local_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))

    info = diagnostics()

    assert info["status"] == "ready"
    assert info["declarative_only"] is True
    assert info["code_generation_allowed"] is False
    assert info["local_only"] is True
