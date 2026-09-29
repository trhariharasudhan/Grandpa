"""Nothing the automation service actuates may run without a yes.

Synthetic input is arbitrary code execution in practice: a keystroke or a click
lands on whatever UI is in front of it, and the caller does not know what that
is. Four of the seven automation actions were gated on that reasoning and three
were not, on the grounds that they "activate nothing":

* ``desktop_navigate`` is ``pyautogui.press(direction)`` -- an arrow keystroke,
  which moves the selection that the next keystroke acts on.
* ``mouse_scroll`` emits ``MOUSEEVENTF_WHEEL``, delivered to the window under
  the cursor. Over a combo box, spinner, slider or numeric field, a notch
  changes that control's value.
* ``mouse_move`` commits nothing itself, but ``mouse_scroll`` has no
  coordinates, so the pointer position is its aim and this is the only way to
  set it.

The gap was reachable. ``AUTOMATION_IMPLEMENTATION`` names
``AutomationControlService.execute``, which checks the foreground window and a
cooldown but never confirmation, and ``action_layer.executor`` skips its own gate
when ``requires_confirmation`` is False. ``automation.execute_spec`` does refuse a
caller that cannot be asked, but that is a different function on the phrase path
only -- the action layer never calls it.

So this enumerates the catalogue rather than listing names. An automation action
added next month is covered the day it exists.
"""

from __future__ import annotations

import pytest

from grandpa.action_layer import catalogue

pytestmark = pytest.mark.core


def automation_actions() -> list[str]:
    """Every catalogued action the automation service actuates."""
    return sorted(
        name
        for name in catalogue.names()
        if getattr(catalogue.get(name), "implementation", "")
        == catalogue.AUTOMATION_IMPLEMENTATION
    )


def test_the_catalogue_still_has_automation_actions() -> None:
    """Guards the guard: an empty enumeration would make the next test vacuous."""
    found = automation_actions()

    assert len(found) >= 7, found
    # Named, not just counted, so a rename cannot quietly shrink the set while
    # the count still passes.
    assert {
        "desktop_navigate",
        "keyboard_hotkey",
        "keyboard_type",
        "mouse_click",
        "mouse_drag",
        "mouse_move",
        "mouse_scroll",
    } <= set(found)


@pytest.mark.parametrize("action", automation_actions())
def test_every_automation_action_requires_confirmation(action: str) -> None:
    spec = catalogue.get(action)

    assert spec.requires_confirmation is True, (
        f"{action} is implemented by the automation service -- it sends real "
        f"keystrokes or pointer events to whatever is in front of the user -- but "
        f"is catalogued requires_confirmation=False. The action layer's executor "
        f"has no gate for an action that does not ask, and "
        f"AutomationControlService.execute does not check confirmation, so this "
        f"actuates with no consent. Add it to _ALWAYS_CONFIRM in "
        f"action_layer/catalogue.py, with the reason."
    )


def test_synthetic_input_is_exactly_the_automation_set() -> None:
    """The voice refusal and this invariant must be talking about the same actions.

    ``natural_actions._is_synthetic_input`` decides what voice refuses to stage
    by comparing against ``AUTOMATION_IMPLEMENTATION``. If that predicate and
    this test ever disagreed about which actions are synthetic input, one of them
    would be protecting a set nobody else believed in.
    """
    from grandpa.natural_actions import _is_synthetic_input

    for action in automation_actions():
        assert _is_synthetic_input(catalogue.get(action)) is True, action

    others = [name for name in catalogue.names() if name not in automation_actions()]
    assert others, "expected the catalogue to hold more than automation actions"
    for action in others:
        assert _is_synthetic_input(catalogue.get(action)) is False, action
