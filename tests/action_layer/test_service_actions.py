"""Web search, the clock, calendar and mail through the action layer.

Calendar and mail need a Google account, so what is checked here is the shape:
the catalogue covers each domain's whole vocabulary, the bindings build the
right dataclass, and an action with no credentials answers "not configured"
rather than crashing. That last one is a real answer, and worth pinning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, Binding, Confirmation, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.calendar.models import CalendarActionType
from grandpa.core.runtime_context import (
    DATETIME_KINDS,
    answer_datetime,
    parse_datetime_intent,
)
from grandpa.gmail.models import GmailActionType
from grandpa.web_search.models import WebSearchActionType

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real domain implementation against the store under the test's own GRANDPA_HOME; reads the real clock"
)


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


def act(action: str, confirm=None, **parameters):
    spec = get(action)
    return execute(
        ActionRequest(
            action,
            parameters,
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        confirm,
    )


def aliases(binding: Binding) -> set[str]:
    return {spec.action_alias for spec in CATALOGUE if spec.binding is binding}


# --- each domain's vocabulary is fully catalogued -----------------------------


def test_every_web_search_action_is_catalogued() -> None:
    assert set(WebSearchActionType.__args__) == aliases(Binding.WEB_SEARCH_ACTION)


def test_every_calendar_action_is_catalogued() -> None:
    assert set(CalendarActionType.__args__) == aliases(Binding.CALENDAR_ACTION)


def test_every_gmail_action_is_catalogued() -> None:
    assert set(GmailActionType.__args__) == aliases(Binding.GMAIL_ACTION)


def test_each_points_at_its_own_domain() -> None:
    for binding, implementation in (
        (
            Binding.WEB_SEARCH_ACTION,
            "grandpa.web_search.automation.WebSearchAutomation.execute",
        ),
        (
            Binding.CALENDAR_ACTION,
            "grandpa.calendar.automation.CalendarAutomation.execute",
        ),
        (Binding.GMAIL_ACTION, "grandpa.gmail.automation.GmailAutomation.execute"),
    ):
        found = {spec.implementation for spec in CATALOGUE if spec.binding is binding}
        assert found == {implementation}, binding


# --- the clock ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "kind"),
    [
        ("what time is it", "time"),
        ("what is the date today", "date"),
        ("what year is it", "year"),
        ("which month is this", "month"),
        ("no, that date is wrong", "dispute"),
        ("tell me a joke", None),
    ],
)
def test_the_clock_parser_decides_what_it_always_did(phrase, kind) -> None:
    """The regexes were lifted out unchanged; this is the proof."""
    assert parse_datetime_intent(phrase) == kind


def test_the_old_entry_point_still_answers_the_same_way() -> None:
    from grandpa.core.runtime_context import handle_datetime_intent

    assert handle_datetime_intent("what time is it") == answer_datetime("time")
    assert handle_datetime_intent("tell me a joke") is None


@pytest.mark.parametrize("kind", DATETIME_KINDS)
def test_every_clock_kind_answers(kind: str) -> None:
    result = act("datetime_now", kind=kind)

    assert result.success is True, result
    assert result.message.strip()


def test_the_clock_is_one_action_not_five() -> None:
    """Every definition sent costs cold-start tokens; a kind is a parameter."""
    clock = [
        spec for spec in CATALOGUE if spec.implementation.endswith("answer_datetime")
    ]

    assert len(clock) == 1
    assert set(clock[0].parameters["properties"]["kind"]["enum"]) <= set(DATETIME_KINDS)


def test_an_unknown_kind_is_refused_by_validation() -> None:
    assert act("datetime_now", kind="fortnight").error == "invalid_parameters"


# --- web search ----------------------------------------------------------------


def test_a_search_builds_a_real_query_object(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_execute(self, action):
        captured["action"] = action
        from grandpa.web_search.models import WebSearchResponse

        return WebSearchResponse("handled", "ok", action)

    monkeypatch.setattr(
        "grandpa.web_search.automation.WebSearchAutomation.execute", fake_execute
    )

    result = act("web_search", query="python packaging", max_results=3)

    assert result.success is True, result
    assert captured["action"].action == "search"
    assert captured["action"].query.text == "python packaging"
    assert captured["action"].query.max_results == 3


def test_web_status_needs_no_query(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_execute(self, action):
        from grandpa.web_search.models import WebSearchResponse

        assert action.query is None
        return WebSearchResponse("handled", "ready", action)

    monkeypatch.setattr(
        "grandpa.web_search.automation.WebSearchAutomation.execute", fake_execute
    )

    assert act("web_search_status").success is True


def test_nothing_in_web_search_asks_for_confirmation() -> None:
    for spec in CATALOGUE:
        if spec.binding is Binding.WEB_SEARCH_ACTION:
            assert spec.requires_confirmation is False, spec.name


# --- calendar and mail without an account -------------------------------------


@pytest.mark.parametrize("action", ["calendar_status", "gmail_status"])
def test_status_answers_rather_than_crashing(action: str) -> None:
    """No account configured is a real answer, not an error to hide."""
    result = act(action)

    assert isinstance(result.message, str) and result.message.strip()
    assert result.data.get("status") in {
        "handled",
        "not_configured",
        "error",
    }, result


@pytest.mark.parametrize(
    "action",
    [
        "calendar_create",
        "calendar_update",
        "calendar_delete",
        "gmail_send",
        "gmail_reply",
        "gmail_forward",
        "gmail_archive",
        "gmail_label",
        "gmail_trash",
    ],
)
def test_the_changing_actions_are_confirmed_by_the_domain(action: str) -> None:
    assert get(action).confirmation is Confirmation.DOMAIN
    assert get(action).requires_confirmation is True


def test_sending_mail_with_nobody_to_ask_is_refused() -> None:
    """No callback means no consent, and no consent means no send."""
    result = act("gmail_send", recipient="someone@example.com", body="hi")

    assert result.error == "confirmation_required", result


def test_a_draft_does_not_ask_because_it_does_not_send() -> None:
    assert get("gmail_draft").requires_confirmation is False
    assert get("gmail_draft").risk is RiskLevel.LOW


def test_deleting_an_event_and_binning_mail_are_the_high_risk_ones() -> None:
    assert get("calendar_delete").risk is RiskLevel.HIGH
    assert get("gmail_trash").risk is RiskLevel.HIGH
