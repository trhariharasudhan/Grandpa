"""Synthetic input is never staged for a later yes *without a focus witness*.

A staged action waits in the kernel's approval store until someone answers it --
up to five minutes. That is right for opening a folder, and wrong for a bare
keystroke: keys and clicks land on whatever holds focus at the instant they are
sent, so a yes from four minutes ago is consent for a screen that has moved on.
Screen Automation V2 used to stage its own confirmations and was safe only
because pc_control then demanded an approval code nobody in a chat turn has.

This file used to assert the absolute: no pending row may ever name an action the
automation service implements. That property is now one notch narrower, and the
notch is the whole of the voice-consent change: a row may exist **if it carries a
reading of the foreground window it was approved against**, which is re-taken and
compared before anything is sent (grandpa.desktop.focus_witness). "Consent a turn
ago" becomes "consent for this screen", which is the only thing the old rule was
really protecting.

What did not change: a caller that cannot produce a witness is refused and stages
nothing. Voice earns this by having a witness, not by being voice -- and on a
machine or platform where the foreground window cannot be read, nobody earns it.

The set of input actions is read from the catalogue, so one added later is covered
the day it exists.
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


_SPEC_FOR = {
    "keyboard_type": "type|hello",
    "keyboard_hotkey": "hotkey|ctrl+c",
    "mouse_scroll": "scroll|down",
    "mouse_click": "click_center",
    "mouse_move": "move_center",
}


@pytest.mark.parametrize("action", _input_actions())
def test_no_input_action_is_staged_without_a_witness(recorder, action) -> None:
    """Drive every route that could stage, for every input action there is.

    This test used to assert no pending row at all. "type hello" now maps to
    keyboard_type and voice can stage it, so the assertion is on the *shape* of
    any row that appears rather than on their absence: every pending input row
    must be one voice staged, with a witness on it. A row without a witness, or
    from another origin, is the defect the old absolute rule was protecting
    against, and is still caught here.
    """
    from grandpa.desktop.control.automation import execute_spec
    from grandpa.local import handle_local_action
    from grandpa.natural_actions import run_parsed

    spec = _SPEC_FOR.get(action, "type|hello")
    # Every caller that opts into deferred consent, with no inline prompt --
    # the combination that stages for everything else.
    for origin in ("voice", "chat", "http"):
        handle_local_action("type hello", deferred_origin=origin)
        handle_local_action("copy selected text", deferred_origin=origin)
        handle_local_action("scroll down", deferred_origin=origin)
        run_parsed("automation", spec, deferred_origin=origin)
    execute_spec(spec)

    # pc_control's own door, which used to stage input for an approval code --
    # consent up to PENDING_TTL_SECONDS old, for a keystroke.
    pc_control.run_local_action({"action_type": action, "args": _parameters(action)})

    for row in _witnessed_rows():
        assert row["origin"] == "voice", (
            f"{row['action_type']} was staged by {row['origin']}, which may not "
            f"carry a witness (see focus_witness.WITNESS_ORIGINS)"
        )
        assert row["witness_json"], (
            f"{row['action_type']} is staged with no witness, so redeeming it "
            f"would check nothing"
        )
        assert row["action_type"] == "keyboard_type", (
            f"{row['action_type']} was staged, but typing is the only synthetic "
            f"action in scope for a spoken route"
        )


@pytest.mark.parametrize("action", _input_actions())
def test_no_route_stages_input_for_chat_or_http(recorder, action) -> None:
    """Split out from the sweep above, because it is a different property.

    The sweep allows voice a witnessed row. This says the same phrases and specs
    give chat and the HTTP API nothing at all -- not a witnessed row, not any
    row. Kept separate so a change that loosened one could not be mistaken for a
    change that loosened both.
    """
    from grandpa.desktop.control.automation import execute_spec
    from grandpa.local import handle_local_action
    from grandpa.natural_actions import run_parsed

    spec = _SPEC_FOR.get(action, "type|hello")
    for origin in ("chat", "http"):
        handle_local_action("type hello", deferred_origin=origin)
        handle_local_action("copy selected text", deferred_origin=origin)
        handle_local_action("scroll down", deferred_origin=origin)
        run_parsed("automation", spec, deferred_origin=origin)
    execute_spec(spec)
    pc_control.run_local_action({"action_type": action, "args": _parameters(action)})

    assert _witnessed_rows() == [], (
        f"{action}: chat or http left a pending input row: {_witnessed_rows()}"
    )


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


def _map_probe(monkeypatch, action: str) -> None:
    """Give the layer a parsed shape that maps to ``action``.

    No real parsed shape maps to a synthetic action today, so every test of this
    branch needs a stand-in. That is also why the branch was dead code before the
    witness landed, and why this file is where its behaviour is pinned.
    """
    import grandpa.natural_actions as natural_actions

    monkeypatch.setitem(
        natural_actions.MIGRATED,
        ("automation", "staging-probe"),
        (action, _parameters(action)),
    )


@pytest.mark.parametrize("action", _input_actions())
def test_the_layer_refuses_to_defer_an_input_action_with_no_witness(
    recorder, monkeypatch, action
) -> None:
    """The invariant that survived: no witness, no staging, nothing sent.

    This is the case on any platform where the foreground window cannot be read,
    and on a machine where it can but the reading fails. The refusal must stage
    nothing -- a pending row with no witness is a keystroke waiting for a yes that
    nothing will check.
    """
    import grandpa.natural_actions as natural_actions
    from tests.witness_support import stub_capture

    _map_probe(monkeypatch, action)
    stub_capture(monkeypatch, [None])

    result = natural_actions.run_parsed(
        "automation", "staging-probe", deferred_origin="voice"
    )

    assert result is not None, "the stand-in mapping did not take"
    assert result.pending_action is None, result
    assert result.status == "blocked", result
    assert _pending_rows() == [], _pending_rows()
    assert [name for name in recorder.actuated if name.startswith("pyautogui.")] == []


@pytest.mark.parametrize("action", _input_actions())
def test_a_staged_input_row_always_carries_a_witness(
    recorder, monkeypatch, action
) -> None:
    """The new invariant, stated over the store rather than over one call path.

    Whatever route stages an input action, the row it leaves must carry a witness.
    A row without one would be redeemed with nothing checked, which is precisely
    the stale-yes-becomes-keystrokes case the old absolute rule prevented.
    """
    import grandpa.natural_actions as natural_actions
    from tests.witness_support import make_witness, stub_capture

    _map_probe(monkeypatch, action)
    stub_capture(monkeypatch, [make_witness()])

    result = natural_actions.run_parsed(
        "automation", "staging-probe", deferred_origin="voice"
    )

    assert result is not None
    assert result.pending_action is not None, "a witnessed action was not staged"
    rows = _witnessed_rows()
    assert len(rows) == 1, rows
    assert rows[0]["action_type"] == action
    assert rows[0]["witness_json"], f"{action} staged a row with no witness"
    # Staging is not sending. Nothing may actuate until the yes arrives and the
    # witness is re-checked.
    assert [name for name in recorder.actuated if name.startswith("pyautogui.")] == []


def _witnessed_rows() -> list[dict]:
    """Pending rows whose action is one the automation service performs.

    Filtered to input actions on purpose: the sweep above also says phrases that
    stage a folder or a URL, and those rows are ordinary deferred consent that
    has always been allowed.
    """
    inputs = set(_input_actions())
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_id, action_type, consent, status, witness_json, "
                "staged_turn_seq, origin FROM pc_control_approvals "
                "WHERE status = 'pending'"
            ).fetchall()
            if str(row["action_type"]) in inputs
        ]


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
