"""Synthetic input is never staged for a later yes, by any route.

A staged action waits in the kernel's approval store until someone answers it --
up to five minutes. That is right for opening a folder, and wrong for a
keystroke: keys and clicks land on whatever holds focus at the instant they are
sent, so a yes from four minutes ago is consent for a screen that has moved on.
Screen Automation V2 used to stage its own confirmations (its own 120-second
store, then briefly the kernel's), and was safe only because pc_control then
demanded an approval code nobody in a chat turn has. Removing that dead end
without removing the staging would have turned a stale yes into keystrokes.

So: nothing may leave a pending row in the approval store whose action is
implemented by the automation service. The set of those actions is read from the
catalogue, so an input action added later is covered by this test the day it
exists.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.action_layer.catalogue import AUTOMATION_IMPLEMENTATION, DOMAINS, get
from tests.security.input_recorder import install


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    import grandpa.desktop.control.automation as automation

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    # Module state: one test's successful action would otherwise leave the next
    # blocked by the cooldown, and the assertion would read as a guard.
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


def _input_actions() -> list[str]:
    """Every catalogued action the automation service performs."""
    names = sorted(
        {name for actions in DOMAINS.values() for name in actions}
        | {
            "keyboard_type",
            "keyboard_hotkey",
            "mouse_move",
            "mouse_click",
            "mouse_scroll",
            "mouse_drag",
        }
    )
    found = []
    for name in names:
        try:
            spec = get(name)
        except KeyError:
            continue  # excluded from the catalogue on purpose
        if spec is not None and spec.implementation == AUTOMATION_IMPLEMENTATION:
            found.append(name)
    return found


def _pending_rows() -> list[dict]:
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_id, action_type, consent, status FROM "
                "pc_control_approvals WHERE status = 'pending'"
            ).fetchall()
        ]


def test_the_catalogue_names_the_input_actions() -> None:
    """If this list empties, every test below would pass by testing nothing."""
    actions = _input_actions()

    assert "keyboard_type" in actions
    assert "keyboard_hotkey" in actions
    assert "mouse_click" in actions
    assert len(actions) >= 5, actions


@pytest.mark.parametrize("action", _input_actions())
def test_no_input_action_is_ever_staged(recorder, action) -> None:
    """Drive every route that could stage, for every input action there is."""
    from grandpa.desktop.control.automation import execute_spec
    from grandpa.local import handle_local_action
    from grandpa.natural_actions import run_parsed

    spec_for = {
        "keyboard_type": "type|hello",
        "keyboard_hotkey": "hotkey|ctrl+c",
        "mouse_scroll": "scroll|down",
        "mouse_click": "click_center",
        "mouse_move": "move_center",
    }
    # Every caller that opts into deferred consent, with no inline prompt --
    # the combination that stages for everything else.
    for origin in ("voice", "chat", "http"):
        handle_local_action("type hello", deferred_origin=origin)
        handle_local_action("copy selected text", deferred_origin=origin)
        handle_local_action("scroll down", deferred_origin=origin)
        run_parsed(
            "automation", spec_for.get(action, "type|hello"), deferred_origin=origin
        )
    execute_spec(spec_for.get(action, "type|hello"))

    # pc_control's own door, which used to stage input for an approval code --
    # consent up to PENDING_TTL_SECONDS old, for a keystroke.
    pc_control.run_local_action({"action_type": action, "args": _parameters(action)})

    assert _pending_rows() == [], f"{action} left a pending row: {_pending_rows()}"


def _parameters(action: str) -> dict:
    return {
        "keyboard_type": {"text": "hello"},
        "keyboard_hotkey": {"keys": ["ctrl", "c"]},
        "mouse_click": {"x": 10, "y": 10},
        "mouse_move": {"x": 10, "y": 10},
        "mouse_scroll": {"amount": -3},
        "mouse_drag": {"start_x": 1, "start_y": 1, "end_x": 2, "end_y": 2},
        "desktop_navigate": {"direction": "down"},
    }.get(action, {})


@pytest.mark.parametrize("action", _input_actions())
def test_the_layer_refuses_to_defer_an_input_action(
    recorder, monkeypatch, action
) -> None:
    """The guard that covers an input action a later tranche maps onto the layer.

    No parsed shape maps to one today, so this gives the mapping a stand-in: if
    run_parsed would stage anything the automation service implements, it fails.
    """
    import grandpa.natural_actions as natural_actions

    monkeypatch.setitem(
        natural_actions.MIGRATED,
        ("automation", "staging-probe"),
        (action, _parameters(action)),
    )
    result = natural_actions.run_parsed(
        "automation", "staging-probe", deferred_origin="voice"
    )

    assert result is not None, "the stand-in mapping did not take"
    # A refusal may report requires_confirmation; what must not exist is a
    # staged action to answer later.
    assert result.pending_action is None, result
    assert _pending_rows() == [], _pending_rows()
    assert [name for name in recorder.actuated if name.startswith("pyautogui.")] == []


def test_screen_automation_v2_stages_nothing_and_asks_inline(recorder) -> None:
    """V2's question is answered in the turn it is asked, or not at all."""
    from grandpa.automation.service import ScreenAutomationService
    from tests.security.input_recorder import _fake_windows

    asked: list[str] = []
    service = ScreenAutomationService(
        confirm=lambda prompt, _tier: asked.append(prompt) or False
    )
    service.pin_target(_fake_windows()[0])

    result = service.handle("type hello")

    assert asked, "V2 did not ask"
    assert not result.confirmation_token, result
    assert _pending_rows() == []
    assert [name for name in recorder.actuated if name.startswith("pyautogui.")] == []


def test_screen_automation_v2_with_no_one_to_ask_does_nothing(recorder) -> None:
    from grandpa.automation.service import ScreenAutomationService
    from tests.security.input_recorder import _fake_windows

    service = ScreenAutomationService()  # no confirm callback
    service.pin_target(_fake_windows()[0])

    result = service.handle("type hello")

    assert result.status == "blocked", result
    assert _pending_rows() == []
    assert [name for name in recorder.actuated if name.startswith("pyautogui.")] == []
