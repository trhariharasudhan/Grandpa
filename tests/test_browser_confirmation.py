"""Browser actions are confirmed before anything opens.

Chat took the URL or query from the model and opened the user's real browser
with no prompt: "open <any url>", "search <anything>", "open chrome",
"open browser history", and browser steps inside multi-step plans.
"""

from __future__ import annotations

import pytest

from grandpa.browser import handle_browser_command
from grandpa.browser.safety import is_trusted_url, parse_trusted_domains
from grandpa.desktop.automation import handle_desktop_command
from grandpa.local_actions import LocalActionResult, classify_permission

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real browser implementation with the opener and hotkey runner the test supplies"
)


class Opener:
    """Stands in for the real browser."""

    def __init__(self) -> None:
        self.opened: list[str] = []

    def __call__(self, url: str) -> bool:
        self.opened.append(url)
        return True


@pytest.fixture
def opener() -> Opener:
    return Opener()


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("open example.com", "https://example.com"),
        ("go to https://example.com/login", "https://example.com/login"),
        ("search google for cats", "https://www.google.com/search?q=cats"),
        ("open browser history", "chrome://history"),
    ],
)
def test_navigation_without_a_callback_is_refused(opener, phrase, expected) -> None:
    result = handle_browser_command(phrase, opener=opener, trusted_domains=())

    assert result.status == "needs_confirmation", result
    assert opener.opened == []
    assert expected in result.message or expected in result.url


@pytest.mark.parametrize(
    ("phrase", "expected_url", "prompt_contains"),
    [
        ("open example.com", "https://example.com", "https://example.com"),
        (
            "search google for red pandas",
            "https://www.google.com/search?q=red+pandas",
            "'red pandas'",
        ),
        ("open browser downloads", "chrome://downloads", "chrome://downloads"),
    ],
)
def test_answering_yes_opens_and_no_opens_nothing(
    opener, phrase, expected_url, prompt_contains
) -> None:
    prompts: list[str] = []

    def decline(prompt: str, tier: str) -> bool:
        prompts.append(prompt)
        assert tier == "requires_confirmation"
        return False

    declined = handle_browser_command(
        phrase, opener=opener, confirm=decline, trusted_domains=()
    )

    assert declined.status == "needs_confirmation"
    assert opener.opened == []
    assert prompt_contains in prompts[0], prompts

    accepted = handle_browser_command(
        phrase, opener=opener, confirm=lambda prompt, tier: True, trusted_domains=()
    )

    assert accepted.status == "handled", accepted
    assert opener.opened == [expected_url]


def test_trusted_domains_skip_the_prompt(opener) -> None:
    def refuse(prompt: str, tier: str) -> bool:
        raise AssertionError(f"asked about a trusted domain: {prompt}")

    for phrase in ("open example.com", "go to https://docs.example.com/guide"):
        result = handle_browser_command(
            phrase, opener=opener, confirm=refuse, trusted_domains=("example.com",)
        )
        assert result.status == "handled", result

    assert opener.opened == ["https://example.com", "https://docs.example.com/guide"]
    assert parse_trusted_domains("example.com, www.other.org") == (
        "example.com",
        "other.org",
    )
    assert is_trusted_url("https://sub.example.com/x", ("example.com",))
    assert not is_trusted_url("https://example.com.evil.test/x", ("example.com",))


def test_shortcuts_on_the_open_page_are_not_navigation() -> None:
    keys: list[tuple[str, ...]] = []

    result = handle_browser_command(
        "go back",
        hotkey_runner=lambda pressed: keys.append(pressed) or True,
        trusted_domains=(),
    )

    assert result.status == "handled" and keys == [("alt", "left")]


@pytest.mark.parametrize(
    ("kind", "target"),
    [
        ("url", "https://www.youtube.com"),
        ("browser", "https://www.google.com/search?q=cats"),
        ("browser", "about:blank"),
    ],
)
def test_local_actions_browser_navigation_needs_confirmation(
    monkeypatch, kind, target
) -> None:
    import grandpa.local_actions as local_actions

    result = LocalActionResult(status="handled", kind=kind, target=target, message="")

    monkeypatch.setattr(local_actions, "_is_trusted_navigation", lambda _target: False)
    assert classify_permission("open it", result) == "requires_confirmation"

    monkeypatch.setattr(local_actions, "_is_trusted_navigation", lambda _target: True)
    assert classify_permission("open it", result) == "allowed"


def test_opening_a_browser_app_asks_but_other_apps_do_not() -> None:
    refused = handle_desktop_command("open chrome", dry_run=True)

    assert refused.status == "needs_confirmation", refused
    assert "Chrome" in refused.message

    asked: list[str] = []
    declined = handle_desktop_command(
        "open microsoft edge",
        dry_run=True,
        confirm=lambda action: asked.append(action.label) or False,
    )

    assert declined.status == "needs_confirmation" and asked == ["Microsoft Edge"]

    other = handle_desktop_command("open notepad", dry_run=True)
    assert other.status != "needs_confirmation", other


def test_browser_steps_in_a_plan_are_medium_risk_and_confirmed() -> None:
    from grandpa.planner.decomposer import DeterministicDecomposer
    from grandpa.planner.executor import _step_confirmation_message
    from grandpa.planner.models import (
        ExecutionPlan,
        Goal,
        PlannerLimits,
        PlanStatus,
        RiskLevel,
        utc_now,
    )
    from grandpa.planner.validator import PlanValidator

    text = "open chrome and search for fastapi"
    steps = DeterministicDecomposer().decompose(
        Goal(text, text, "test"), PlannerLimits()
    )
    plan = ExecutionPlan(
        plan_id="p1",
        session_id="test",
        original_goal=text,
        normalized_goal=text,
        created_at=utc_now(),
        status=PlanStatus.CREATED,
        steps=list(steps),
    )

    assert PlanValidator().validate(plan).valid
    assert plan.safety_classification == RiskLevel.MEDIUM

    browser_steps = [step for step in plan.steps if step.action == "browser_search"]
    assert len(browser_steps) == 1
    assert browser_steps[0].requires_confirmation
    assert "https://www.google.com/search?q=fastapi" in _step_confirmation_message(
        browser_steps[0]
    )
