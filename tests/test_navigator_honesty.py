"""SmartNavigator must not claim scrolls that never happened.

``browser_control.execute_browser_action`` has no ``"scroll"`` action; it
falls through to "not supported yet". These paths used to report
"Scrolled page towards heading ..." and "Scrolled N times ..." regardless.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import grandpa.browser_intelligence.navigator as navigator

# planner/executor.py treats these statuses as a successful step.
_SUCCESS_STATUSES = {"handled", "success"}


@pytest.fixture
def issued(monkeypatch) -> list[str]:
    actions: list[str] = []

    def fake_execute_browser_action(action: str, target: str = ""):
        actions.append(action)
        return SimpleNamespace(
            status="unsupported", message="That browser action is not supported yet."
        )

    monkeypatch.setattr(
        navigator, "execute_browser_action", fake_execute_browser_action
    )
    return actions


def _page(*headings: str):
    return SimpleNamespace(headings=tuple(SimpleNamespace(text=h) for h in headings))


def test_smart_navigate_to_heading_is_not_success_shaped(monkeypatch, issued) -> None:
    monkeypatch.setattr(navigator, "read_current_browser_page", lambda: _page())
    monkeypatch.setattr(
        navigator,
        "resolve_target_link",
        lambda page, goal: {"type": "heading", "target": "Installation"},
    )

    result = navigator.SmartNavigator().smart_navigate("Go to Installation")

    assert result["status"] not in _SUCCESS_STATUSES
    assert "not implemented" in result["message"]
    assert "Scrolled" not in result["message"]


def test_scroll_until_heading_absent_is_not_success_shaped(monkeypatch, issued) -> None:
    monkeypatch.setattr(navigator, "read_current_browser_page", lambda: _page("Intro"))

    result = navigator.SmartNavigator().scroll_until_heading("Installation")

    assert result["status"] not in _SUCCESS_STATUSES
    assert result["status"] != "partially_handled"
    assert "not implemented" in result["message"]
    assert "Scrolled" not in result["message"]
    assert "scroll" not in issued, "a no-op scroll was issued and reported"


def test_scroll_until_heading_present_does_not_claim_a_scroll(
    monkeypatch, issued
) -> None:
    monkeypatch.setattr(
        navigator, "read_current_browser_page", lambda: _page("Installation")
    )

    result = navigator.SmartNavigator().scroll_until_heading("Installation")

    assert result["status"] == "handled"
    assert "scroll" not in result["message"].lower()
    assert not issued
