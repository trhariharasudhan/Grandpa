"""What a goal's content can name, and what that gets it.

Saved skills hid an escalation, so the same question is asked of agent_plan:
can a plan's content name a capability a person did not?

It can name one. ``_match_runtime_skill`` matches the *whole* request against
registered skill names and aliases, so ``{"user_request": "desktop.keyboard_
type"}`` to ``POST /v1/agent-runtime/goals`` becomes a plan step naming that
skill, and the planner stamps its own ``risk_level="LOW",
approval_required=False`` on it. Three things stop that from mattering, and each
is pinned below, because each is load-bearing:

* every planned step runs with ``dry_run=True``;
* ``RuntimeSkill.execute`` uses the *registered* ``approval_required``, not the
  plan's; and
* a stored goal's steps are a record -- ``continue_goal`` recomputes the plan
  from the request, so nothing replays saved step content.

Nothing actuates: reaching a real implementation raises ActuationDenied
(tests/actuation_guard.py).
"""

from __future__ import annotations

import pytest

from tests.actuation_guard import ActuationDenied


@pytest.fixture(autouse=True)
def _private_goal_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))


def _goal(request_text: str):
    from grandpa.agents.goal_mode import create_goal

    return create_goal(request_text, execute=True)


def test_a_goal_naming_a_typing_skill_does_not_type() -> None:
    """The step is planned, and refused before its executor runs."""
    goal = _goal("desktop.keyboard_type")

    assert [step["skill"] for step in goal.steps] == ["desktop.keyboard_type"]
    # The plan's own opinion of the step, which is the understatement:
    assert goal.steps[0]["approval_required"] is False
    assert goal.steps[0]["risk_level"] == "LOW"
    # And the registry's, which is what decides. The plan said no approval was
    # needed, so _act ran the step; RuntimeSkill.execute refused it, and the
    # goal ends without a keystroke.
    assert [action["status"] for action in goal.actions_taken] == ["approval_required"]
    assert goal.status == "failed"
    # Nothing was staged for later either: the plan's word did not create a
    # pending approval that someone could clear with a code.
    assert goal.approvals_needed == []


def test_a_goal_naming_a_power_skill_does_not_reach_power() -> None:
    """If it reached, ActuationDenied would come out of create_goal."""
    goal = _goal("desktop.summary")

    assert goal.steps
    assert goal.status != "failed"
    for action in goal.actions_taken:
        assert action["status"] in {"dry_run", "completed", "unsupported"}


def test_every_planned_step_runs_as_a_dry_run() -> None:
    """The property the two tests above depend on, stated directly."""
    import grandpa.agents.goal_mode as goal_mode

    seen: list[bool] = []
    real = goal_mode.execute_skill

    def _record(name, params=None, context=None):
        seen.append(bool(context and context.dry_run))
        return real(name, params, context)

    goal_mode.execute_skill = _record
    try:
        _goal("set up my coding workspace")
    finally:
        goal_mode.execute_skill = real

    assert seen, "no step ran"
    assert all(seen), "a planned step ran without dry_run"


def test_continuing_a_goal_replans_instead_of_replaying_saved_steps(
    monkeypatch,
) -> None:
    """A saved step is a record. Replaying one would be the user-skill hole."""
    from grandpa.agents.goal_mode import AgentGoalStore, continue_goal, create_goal

    store = AgentGoalStore()
    goal = create_goal("desktop.summary", execute=False, store=store)
    tampered = store.get(goal.goal_id)
    assert tampered is not None
    tampered.steps = [
        {
            "id": "step_1",
            "skill": "desktop.summary",
            "params": {"action_type": "system_lock"},
            "risk_level": "LOW",
            "approval_required": False,
        }
    ]
    store.save(tampered)

    continued = continue_goal(goal.goal_id, store=store)

    assert continued is not None
    # Replanned from the request: the tampered params are gone, not executed.
    assert continued.steps[0]["params"] == {}


def test_the_observation_phase_goes_through_the_layer() -> None:
    """It read the desktop through pc_control directly until this tranche."""
    import inspect

    from grandpa.agents import goal_mode

    source = inspect.getsource(goal_mode._observe)

    assert "grandpa.desktop.layer_runner" in source
    assert "pc_control" not in source


def test_dry_run_is_advisory_and_two_skills_ignore_it() -> None:
    """Recorded, not excused.

    ``RuntimeSkill.execute`` never checks ``dry_run``; each executor has to
    honour it. Two of the 44 registered skills do not, and both are reads --
    which is the only reason agent_plan's dry_run is enough. If a *write* ever
    joins this list, this test fails and says so.
    """
    from grandpa.skills.registry import (
        clear_skills,
        ensure_default_skills_registered,
        execute_skill,
        list_skills,
    )
    from grandpa.skills.runtime import SkillExecutionContext

    # The registered set, not whatever this session happens to have accumulated.
    # The runtime skill registry is global and conftest does not clear it, so an
    # earlier test that called register_user_skills() leaves the user's own saved
    # skills in it -- and UserSkillStore's default path is relative to the working
    # directory, so "the user's own" can mean a store left behind in the repo.
    # Running this from D:\Grandpa picked up a leaked "start coding session".
    clear_skills()
    ensure_default_skills_registered()
    acted: set[str] = set()
    for skill in list_skills():
        try:
            execute_skill(
                skill.name, {}, SkillExecutionContext(dry_run=True, source="test")
            )
        except ActuationDenied:
            acted.add(skill.name)
        except Exception:  # noqa: BLE001 - a broken skill is not this test's business
            continue

    assert acted == {"browser.diagnostics", "desktop.clipboard_history"}, (
        "the set of skills that act despite dry_run changed: "
        f"{sorted(acted)}. agent_plan relies on dry_run, so a write here is a hole."
    )
