"""The intent router's read-only promise, enforced rather than asserted.

``skill_router`` is documented as "Skill-backed routing for high-confidence
local read-only intents", and it executes what it matches with
``dry_run=False`` -- the only tranche in this phase that does. It was safe
because of its table, not because of a check: ``match_skill_route`` stamped
every route ``risk_level="LOW", approval_required=False`` without asking the
registry, and ``can_execute_as_skill`` looks only at the source, the name and
the confidence. One row of the table already disagreed with the registry
(``summarize current desktop state`` -> ``desktop.operator_plan``, MEDIUM), and
nothing would have noticed a row for a skill that types.

This is the same shape as the user-skill hole -- something declaring its own
risk and being believed -- with the declaration in code rather than in saved
data. So the route now reads its risk from the registry, and refuses to run a
skill the registry says needs approval, because a routed request has nobody to
ask.

Nothing actuates: reaching a real implementation raises ActuationDenied.
"""

from __future__ import annotations

import pytest

from tests.actuation_guard import ActuationDenied


@pytest.fixture(autouse=True)
def _private_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))


def _registered(name: str):
    from grandpa.skills.registry import ensure_default_skills_registered, get_skill

    ensure_default_skills_registered()
    return get_skill(name)


def test_every_row_names_a_registered_skill_that_needs_no_approval() -> None:
    """The table is the whole of the router's vocabulary, so it is the check."""
    from grandpa.router.skill_router import route_table

    offenders = []
    for phrase, row in route_table().items():
        try:
            skill = _registered(row["skill_name"])
        except KeyError:
            offenders.append(f"{phrase}: {row['skill_name']} is not registered")
            continue
        if skill.approval_required:
            offenders.append(f"{phrase}: {skill.name} needs approval")

    assert offenders == [], (
        "the intent router runs what it matches with dry_run=False and cannot "
        f"ask anyone: {offenders}"
    )


def test_a_route_reports_the_registrys_risk_not_its_own() -> None:
    """``desktop.operator_plan`` is MEDIUM; the route used to call it LOW."""
    from grandpa.router.skill_router import match_skill_route

    route = match_skill_route("summarize current desktop state")

    assert route is not None
    assert route.skill_name == "desktop.operator_plan"
    assert _registered("desktop.operator_plan").risk_level == "MEDIUM"
    assert route.risk_level == "MEDIUM"
    assert route.approval_required is False


def test_the_low_rows_are_still_low() -> None:
    from grandpa.router.skill_router import match_skill_route

    route = match_skill_route("desktop summary")

    assert route is not None
    assert route.risk_level == "LOW"


def test_a_row_for_a_skill_that_needs_approval_is_refused_not_run(
    monkeypatch,
) -> None:
    """The table is code, so the guard is a check, not a promise about the table."""
    import grandpa.router.skill_router as skill_router

    monkeypatch.setitem(
        skill_router._ROUTE_TABLE,
        "type the standup note",
        ("desktop.keyboard_type", "keyboard_type", "desktop"),
    )

    route = skill_router.match_skill_route("type the standup note")

    assert route is not None
    assert route.approval_required is True
    assert route.can_execute_as_skill is False


def test_the_router_reaches_only_reads() -> None:
    """Every phrase in the table, run for real, against the deny fixture.

    The seven that reach an implementation are diagnostics, the desktop
    summary and clipboard history. If a phrase ever reaches an actuator, this
    names it.
    """
    from grandpa.router.intent_router import route_local_intent
    from grandpa.router.skill_router import route_table

    reached: dict[str, str] = {}
    for phrase in route_table():
        try:
            route_local_intent(phrase)
        except ActuationDenied as exc:
            reached[phrase] = str(exc).split(" was called")[0]

    assert set(reached.values()) == {
        "grandpa.browser_control.execute_browser_action",
        "grandpa.desktop.control.clipboard.ClipboardControlService.execute",
        "grandpa.desktop.control.diagnostics.DesktopDiagnosticsService.execute",
    }, f"the router now reaches: {sorted(set(reached.values()))}"
