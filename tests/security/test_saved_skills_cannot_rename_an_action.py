"""A saved skill's params cannot choose which capability it is.

``_pc_action`` used to build its payload as ``params.get("action_type",
action_type)``. A runtime skill's params arrive from a *stored* workflow step,
so a skill registered as a read could be saved as a write: the HTTP API
accepted ``{"skill": "desktop.summary", "params": {"action_type":
"system_lock"}}`` with ``"risk_level": "LOW"``, and the next time its trigger
phrase was spoken it locked the screen.

Two separate things are checked here, because the hole had two halves:

* what a skill *does* is fixed where it is registered (the rows below), and
* what a saved skill *contains* is approved when it is saved, by someone who
  is shown the steps -- because saving is deferred execution, and at run time
  nobody is reading them.

Nothing actuates: reaching a real implementation raises ActuationDenied
(tests/actuation_guard.py), so "it got through" is an exception and a refusal
is the absence of one.
"""

from __future__ import annotations

import pytest

from tests.actuation_guard import ActuationDenied

# The rows from the escalation report, verbatim. Each was run against the real
# registry before the fix; the third column is where it landed then.
RENAME_ROWS = [
    ({"action_type": "system_lock"}, "PowerControlService.execute_system"),
    (
        {"action_type": "volume_set", "target": "100"},
        "PowerControlService.execute_volume",
    ),
    ({"action_type": "system_shutdown"}, "an approval code staged by pc_control"),
]


def _run(skill: str, params: dict):
    from grandpa.skills.registry import ensure_default_skills_registered, execute_skill

    ensure_default_skills_registered()
    return execute_skill(skill, params)


def test_the_unrenamed_row_still_does_what_the_skill_says() -> None:
    """Row 1 of the report: no override, and the real read still happens.

    Without this the rest would pass just as well if the skill did nothing at
    all, which is not the property being fixed.
    """
    with pytest.raises(ActuationDenied, match="DesktopDiagnosticsService.execute"):
        _run("desktop.summary", {})


@pytest.mark.parametrize("params,used_to_reach", RENAME_ROWS)
def test_a_read_skill_cannot_be_renamed_into_a_write(
    params: dict, used_to_reach: str
) -> None:
    result = _run("desktop.summary", params)

    assert result.ok is False, f"still reaches {used_to_reach}"
    assert result.status == "blocked"
    assert result.error == "action_rename_refused"
    # Named out loud: the caller asked for something it did not get.
    assert params["action_type"].replace("_", " ") in result.message


def test_the_refusal_is_not_special_to_one_skill() -> None:
    """Every registration built by ``_pc_action`` has the same door."""
    for skill in ("desktop.monitors", "desktop.diagnostics"):
        result = _run(skill, {"action_type": "system_lock"})

        assert result.ok is False, skill
        assert result.error == "action_rename_refused", skill


def test_the_fourth_pc_action_skill_never_gets_that_far() -> None:
    """``desktop.keyboard_type`` is registered approval_required.

    So it is refused by ``RuntimeSkill.execute`` before its executor runs, and
    the rename never reaches the door above. Both are refusals; this pins
    which one, so that a later change making the skill approval-free shows up
    here instead of quietly moving it to the other refusal.
    """
    result = _run("desktop.keyboard_type", {"action_type": "system_lock"})

    assert result.ok is False
    assert result.status == "approval_required"


def test_params_still_reach_the_action_they_belong_to() -> None:
    """Removing the override must not remove parameters along with it."""
    result = _run("desktop.summary", {"dry_run": True})

    assert result.status == "dry_run"
    assert result.ok is True
