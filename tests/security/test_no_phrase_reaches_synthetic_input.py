"""Exactly one spoken shape reaches synthetic input, and it reaches only typing.

This file used to assert that *no* shipped phrase mapped to an action the
automation service implements. That was true, and it was the fact that kept two
other guards honest without anyone saying so: the voice tranche guard passed
because voice's phrases never reached the action layer, not because the layer
refused them.

The route is now open, deliberately and narrowly. ``_parse_automation_action``
turns a bare "type hello" into ``("automation", "type|hello")``, and
``_PREFIXED`` maps that prefix to ``keyboard_type``. So the property is no longer
"none" but "one, and this one":

* the only mapping to a synthetic action is ``("automation", "type|")``;
* it yields ``keyboard_type`` and nothing else;
* every other synthetic action remains unreachable from every parsed shape.

Why typing alone, restated here because this is where someone will come to widen
it:

* it is the only action whose target is the window the witness attests.
  ``pyautogui.write`` goes to the focused window, which is the foreground window
  the witness reads. Click and drag carry absolute screen coordinates; scroll
  goes to the window under the *cursor*, which the witness never looks at.
* typing cannot change which window has focus. A hotkey can -- alt+tab, win+d,
  win+e -- so a hotkey can invalidate the invariant the witness rests on, and the
  denylist is four combinations against the whole shortcut space.
* it is the only one with a content filter already in place
  (``automation.is_blocked_text``), and the read-back names the target window,
  which is what turns "typing is arbitrary" into a decision a person can refuse.

Adding a second mapping means arguing those three points for the new action, and
re-reading ``tests/security/test_voice_confirmation.py``, whose property this
file's contents determine.
"""

from __future__ import annotations

import pytest

from grandpa.action_layer.catalogue import AUTOMATION_IMPLEMENTATION, get
from grandpa.natural_actions import _BY_KIND, _PREFIXED, MIGRATED

pytestmark = pytest.mark.core

#: The one shape allowed to reach synthetic input, and what it must yield.
APPROVED_SHAPE = ("automation", "type|")
APPROVED_ACTION = "keyboard_type"

#: A probe target for the callables in _BY_KIND and _PREFIXED, which build a
#: mapping from the phrase's own text.
_PROBE = "probe-target"


def _action_of(mapped: object) -> str:
    """The catalogued action name a mapping yields, or "" if it yields none."""
    if mapped is None:
        return ""
    try:
        name = mapped[0]  # type: ignore[index]
    except (TypeError, IndexError, KeyError):
        return ""
    return str(name)


def _is_synthetic(action: str) -> bool:
    if not action:
        return False
    try:
        spec = get(action)
    except KeyError:
        return False
    return getattr(spec, "implementation", "") == AUTOMATION_IMPLEMENTATION


def _resolve(entry: object) -> str:
    """Resolve a mapping table value, whether it is a pair or a builder."""
    try:
        return _action_of(entry(_PROBE) if callable(entry) else entry)
    except Exception:  # noqa: BLE001 - a builder that cannot build maps nothing
        return ""


def _synthetic_mappings() -> dict[object, str]:
    """Every mapping table entry that yields a synthetic action."""
    found: dict[object, str] = {}
    for key, value in MIGRATED.items():
        action = _resolve(value)
        if _is_synthetic(action):
            found[key] = action
    for key, build in list(_BY_KIND.items()) + list(_PREFIXED.items()):
        action = _resolve(build)
        if _is_synthetic(action):
            found[key] = action
    return found


def test_the_mapping_tables_are_not_empty() -> None:
    """Guards the guard: empty tables would make the checks below vacuous."""
    assert MIGRATED, "MIGRATED is empty -- did the mapping move?"
    assert _BY_KIND, "_BY_KIND is empty"
    assert _PREFIXED, "_PREFIXED is empty"


def test_exactly_one_shape_reaches_synthetic_input() -> None:
    found = _synthetic_mappings()

    assert set(found) == {APPROVED_SHAPE}, _message(found)


def test_that_shape_yields_typing_and_nothing_else() -> None:
    found = _synthetic_mappings()

    assert found.get(APPROVED_SHAPE) == APPROVED_ACTION, found


def test_the_approved_shape_is_what_the_parser_actually_produces() -> None:
    """The mapping is worthless if no phrase produces the shape it matches.

    Asserted against the parser rather than against a string, so renaming the
    spec shape breaks this rather than silently closing the route.
    """
    from grandpa.local.parsers import _normalise, _parse_automation_action

    parsed = _parse_automation_action(_normalise("type hello"))

    assert parsed.status != "no_match", "the parser no longer handles a bare 'type X'"
    assert parsed.kind == APPROVED_SHAPE[0]
    assert parsed.target.startswith(APPROVED_SHAPE[1]), parsed.target


def test_the_approved_shape_resolves_through_request_for() -> None:
    """End to end through the real resolver, not the table directly."""
    from grandpa.natural_actions import request_for

    mapped = request_for("automation", "type|hello there")

    assert mapped is not None, "the approved shape does not resolve"
    assert mapped[0] == APPROVED_ACTION
    assert mapped[1]["text"] == "hello there", mapped


def test_the_chained_focus_and_type_shape_is_not_mapped() -> None:
    """ "type hello in notepad" is focus *plus* type -- two actions, not one.

    One catalogued action cannot honestly stand for a compound spec, and mapping
    it would let a single yes approve a focus change and a keystroke together.
    """
    from grandpa.natural_actions import request_for

    assert request_for("automation", "focus|notepad||type|hello") is None


@pytest.mark.parametrize(
    "action",
    [
        "keyboard_hotkey",
        "mouse_click",
        "mouse_move",
        "mouse_scroll",
        "mouse_drag",
        "desktop_navigate",
    ],
)
def test_every_other_synthetic_action_stays_unreachable(action: str) -> None:
    """Named individually, so opening one is a visible edit to this list."""
    assert _is_synthetic(action), f"{action} is not a synthetic action any more"
    assert action not in _synthetic_mappings().values(), (
        f"{action} is now reachable from a parsed phrase. Only typing is in "
        f"scope; see this module's docstring for the three arguments a new "
        f"action has to satisfy."
    )


def test_the_automation_actions_exist_to_be_found() -> None:
    """The other half: the actions are catalogued, so the checks can bite."""
    assert _is_synthetic(APPROVED_ACTION)
    assert _is_synthetic("mouse_click")
    assert not _is_synthetic("open_folder")


def _message(found: dict) -> str:
    return (
        f"the set of phrases reaching synthetic input changed: {found}.\n"
        f"Expected exactly {{{APPROVED_SHAPE}}}.\n"
        "Two guards change meaning when this set changes, and both should be "
        "re-read rather than assumed:\n"
        "  * tests/security/test_voice_confirmation.py -- its tranche guard "
        "states what voice may and may not actuate. Its property is determined "
        "by which phrases reach the layer.\n"
        "  * tests/security/test_no_staged_input.py -- its sweep allows voice a "
        "witnessed row and no one else any row.\n"
        "If the new mapping is intended, update both and this docstring."
    )
