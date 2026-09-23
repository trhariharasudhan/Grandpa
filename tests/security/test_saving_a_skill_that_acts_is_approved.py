"""Saving a skill that acts is approved when it is saved.

A saved skill is deferred execution. It runs later, on a trigger phrase, and at
that moment nobody is reading its steps -- so the only place a person can see
what they are agreeing to is the moment it is stored. The gate therefore sits
on the save, lists the acting steps, and refuses when there is no one to ask:
``POST /v1/user-skills/create`` has no way to prompt, so it cannot store a
skill that changes the machine.

The step's own ``risk_level`` is not evidence. It is supplied by whoever wrote
the step, and the report's probe declared ``"risk_level": "LOW"`` on a step
that locked the screen. What each step is worth comes from the registry.

Nothing actuates here: nothing is run, only stored.
"""

from __future__ import annotations

import pytest

from grandpa.skill_builder import SkillValidationError, create_user_skill
from grandpa.skill_builder.storage import UserSkillStore

# A step that types. Registered MEDIUM, approval_required -- and declaring
# itself LOW, exactly as the probe did.
TYPING_STEP = {
    "skill": "desktop.keyboard_type",
    "title": "Type the standup note",
    "params": {"text": "hello"},
    "risk_level": "LOW",
    "approval_required": False,
}
READ_STEP = {
    "skill": "desktop.summary",
    "title": "Summarize desktop",
    "params": {},
    "risk_level": "LOW",
}


@pytest.fixture(autouse=True)
def _private_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_USER_SKILLS_DB", str(tmp_path / "user_skills.db"))


def _payload(*steps: dict) -> dict:
    return {"name": "morning routine", "workflow_steps": list(steps)}


def test_with_no_one_to_ask_an_acting_skill_is_not_saved() -> None:
    """The HTTP route's shape: a caller that cannot prompt."""
    with pytest.raises(SkillValidationError) as raised:
        create_user_skill(_payload(TYPING_STEP))

    assert "no way to ask" in str(raised.value)
    assert UserSkillStore().list(limit=10) == []


def test_the_prompt_names_the_step_that_acts() -> None:
    asked: list[str] = []

    with pytest.raises(SkillValidationError):
        create_user_skill(
            _payload(READ_STEP, TYPING_STEP),
            confirm=lambda prompt, _permission: asked.append(prompt) or False,
        )

    assert len(asked) == 1
    prompt = asked[0]
    assert "Type the standup note" in prompt
    assert "desktop.keyboard_type" in prompt
    # The read step is not listed: it is not what is being approved.
    assert "Summarize desktop" not in prompt
    # And it says the saving is what defers the running.
    assert "run them later" in prompt


def test_declining_does_not_save_it() -> None:
    with pytest.raises(SkillValidationError, match="was not saved"):
        create_user_skill(_payload(TYPING_STEP), confirm=lambda *_: False)

    assert UserSkillStore().list(limit=10) == []


def test_agreeing_saves_it() -> None:
    created = create_user_skill(_payload(TYPING_STEP), confirm=lambda *_: True)

    assert created["status"] == "created"
    assert UserSkillStore().list(limit=10)
    # The stored step now carries what the registry says, not what it claimed.
    step = created["skill"]["workflow_steps"][0]
    assert step["risk_level"] == "MEDIUM"
    assert step["approval_required"] is True


def test_a_read_only_skill_still_saves_without_being_asked() -> None:
    """The gate is for steps that act. Reads must not start needing a prompt."""
    asked: list[str] = []

    created = create_user_skill(
        _payload(READ_STEP), confirm=lambda prompt, _p: asked.append(prompt) or True
    )

    assert created["status"] == "created"
    assert asked == []


def test_a_step_naming_nothing_real_is_treated_as_acting() -> None:
    """An unknown skill name cannot be vouched for, so it is not waved through."""
    unknown = dict(READ_STEP, skill="not.a.registered.skill", title="Do the thing")

    with pytest.raises(SkillValidationError) as raised:
        create_user_skill(_payload(unknown))

    assert "Do the thing" in str(raised.value)


def test_the_phrase_path_asks_the_person_in_front_of_it(monkeypatch) -> None:
    """A person's "no" is an answer, not a parse failure.

    ``_parse_user_skill_action`` is wrapped in a broad ``except Exception``
    that returns ``no_match``; without the explicit catch, a declined save
    would be handed to the next route as if the phrase had not been understood,
    and the person who said no would get an answer about something else.

    The phrase path fills its steps from a template, and every template today
    is read-only -- which is why the template is replaced here. The property
    under test is that the phrase path *carries the prompt*, not that today's
    templates happen not to need one.
    """
    monkeypatch.setattr(
        "grandpa.skill_builder.builder.template_steps_for_name",
        lambda _name: [dict(TYPING_STEP)],
    )
    from grandpa.local_actions import _parse_user_skill_action

    asked: list[str] = []

    result = _parse_user_skill_action(
        "create a skill called morning routine",
        confirm=lambda prompt, _p: asked.append(prompt) or False,
    )

    assert asked, "the phrase path saved without asking"
    assert result.status == "error"
    assert result.target == "user_skill|not_saved"
    assert UserSkillStore().list(limit=10) == []


def test_the_http_route_refuses_the_row_from_the_report() -> None:
    """End to end, the exact request that returned 200 and locked the screen.

    It reached ``PowerControlService.execute_system`` through two doors at
    once: the step renamed ``desktop.summary``'s action, and the API stored it
    without anyone seeing the step. Either fix alone would stop it; both are
    in place, and this is the request itself.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from grandpa.server.api_routes import user_skills_router

    app = FastAPI()
    app.include_router(user_skills_router)
    client = TestClient(app)

    response = client.post(
        "/v1/user-skills/create",
        json={
            "name": "desk check",
            "workflow_steps": [
                {
                    "skill": "desktop.summary",
                    "title": "Check the desk",
                    "risk_level": "LOW",
                    "params": {"action_type": "system_lock", "target": ""},
                }
            ],
        },
    )

    # Stored, because desktop.summary really is a read -- and now inert: the
    # rename is refused when it runs, proven in the sibling test module.
    assert response.status_code == 200
    stored = response.json()["skill"]["workflow_steps"][0]
    assert stored["params"]["action_type"] == "system_lock"
    assert stored["risk_level"] == "LOW"

    ran = client.post(
        f"/v1/user-skills/{response.json()['skill']['skill_id']}/run", json={}
    )

    assert ran.status_code == 200
    assert ran.json()["ok"] is False
    assert "cannot be asked to do system lock" in ran.json()["message"]
