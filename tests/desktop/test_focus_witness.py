"""The focus witness: what it records, and what counts as a mismatch.

A witness turns "consent a turn ago" into "consent for this screen". Its value is
entirely in the comparison, so each tier is tested on its own, and each is tested
in a way that can fail -- a tier that cannot fail is not a tier, it is a comment.

The tiers, and why they are tiered:

* identity (hwnd, pid, exe_path, class_name) -- hard. A relaunched application is
  a mismatch even at the same path: a new process is a new session.
* geometry (rect) -- hard only for actions carrying coordinates. A window that
  moved invalidates an approved (x, y); it does not invalidate a keystroke, which
  follows focus.
* control (control_id) -- hard when the action named one, and resolved by looking
  it up again so a vanished control is caught.
* title -- soft, never decisive. Titles change on their own: clocks tick, unsaved
  markers appear, "(2) Inbox" becomes "(3) Inbox". A title-only change must not
  refuse, or the mechanism becomes noise and gets switched off.
"""

from __future__ import annotations

import pytest
from tests.witness_support import NOTEPAD, make_witness

from grandpa.desktop import focus_witness

pytestmark = pytest.mark.core

#: An action that carries coordinates, and one that does not.
COORDINATE_ACTION = "mouse_click"
FOCUS_ACTION = "keyboard_type"

#: A click inside the witnessed window, for tests about some other tier.
CLICK_AT = {"x": 500, "y": 400}


@pytest.fixture
def owned_points(monkeypatch):
    """Every point belongs to the witnessed window.

    Neutralises the point-ownership tier so a test can be about the tier it
    names. Without it, the real WindowFromPoint runs against a fabricated hwnd
    and every coordinate action refuses for the wrong reason.
    """
    monkeypatch.setattr(focus_witness, "POINT_OWNER", lambda x, y: int(NOTEPAD["hwnd"]))


# --- the fields -----------------------------------------------------------------


def test_a_witness_round_trips_through_the_store_format() -> None:
    """It is persisted as JSON, so what comes back must be what went in."""
    original = make_witness(control_id="SaveButton|Button|save")

    restored = focus_witness.Witness.from_dict(original.to_dict())

    assert restored == original


def test_an_unreadable_stored_witness_is_not_a_witness() -> None:
    """A row we cannot parse must not become a blank that matches anything."""
    assert focus_witness.Witness.from_dict(None) is None
    assert focus_witness.Witness.from_dict({}) is None
    assert focus_witness.Witness.from_dict({"hwnd": "not-a-number"}) is None
    assert focus_witness.Witness.from_dict({"rect": [1, 2]}) is None


def test_the_app_name_is_what_would_be_spoken() -> None:
    """exe_path is normcased for comparison; the spoken form is recapitalised.

    A lower-cased "notepad" in the middle of a sentence reads as a bug, and
    comparison is the only reason the path is normcased at all.
    """
    assert make_witness(exe_path=r"c:\windows\notepad.exe").app_name == "Notepad"
    assert make_witness(exe_path=r"c:\office\OUTLOOK.EXE").app_name == "Outlook"
    # Mixed case is left alone: capitalize() would make this "Vscode".
    assert make_witness(exe_path=r"c:\apps\VSCode.exe").app_name == "VSCode"
    assert make_witness(exe_path="").app_name == "an unknown application"


# --- identity: hard --------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hwnd", 0x9999),
        ("pid", 5555),
        ("exe_path", r"c:\windows\system32\cmd.exe"),
        ("class_name", "ConsoleWindowClass"),
    ],
)
def test_each_identity_field_refuses_on_its_own(field: str, value: object) -> None:
    """One field differs; everything else is identical. Each must be decisive."""
    staged = make_witness()
    current = make_witness(**{field: value})

    verdict = focus_witness.compare(staged, current, action=FOCUS_ACTION)

    assert verdict.matched is False
    assert field in verdict.differences, verdict


def test_a_relaunched_application_is_a_mismatch() -> None:
    """Same path, new process. A new session is not the screen that was approved."""
    staged = make_witness()
    current = make_witness(pid=make_witness().pid + 1, hwnd=make_witness().hwnd)

    verdict = focus_witness.compare(staged, current, action=FOCUS_ACTION)

    assert verdict.matched is False
    assert "pid" in verdict.differences
    assert "restarted" in verdict.reason


def test_an_identical_reading_matches() -> None:
    verdict = focus_witness.compare(make_witness(), make_witness(), action=FOCUS_ACTION)

    assert verdict.matched is True
    assert verdict.differences == ()


# --- geometry: hard only where coordinates are involved ---------------------------


def test_a_moved_window_refuses_a_coordinate_action(owned_points) -> None:
    staged = make_witness()
    current = make_witness(rect=(105, 100, 905, 700))

    verdict = focus_witness.compare(
        staged, current, action=COORDINATE_ACTION, parameters=CLICK_AT
    )

    assert verdict.matched is False
    assert "rect" in verdict.differences
    assert "moved or was resized" in verdict.reason


def test_a_moved_window_does_not_refuse_a_keystroke() -> None:
    """The tier's whole point: a keystroke follows focus, not pixels.

    Refusing here would make the mechanism stricter and worse -- every window
    nudge would drop a pending keystroke, and the user would learn to repeat
    themselves rather than to read the prompt.
    """
    staged = make_witness()
    current = make_witness(rect=(105, 100, 905, 700))

    verdict = focus_witness.compare(staged, current, action=FOCUS_ACTION)

    assert verdict.matched is True, verdict


def test_the_coordinate_actions_are_the_ones_that_carry_coordinates() -> None:
    """Stated against the catalogue's own parameter schemas, not a hand-kept list."""
    from grandpa.action_layer.catalogue import get

    for action in focus_witness.GEOMETRY_ACTIONS:
        properties = (get(action).parameters or {}).get("properties") or {}
        assert {"x", "y"} & set(properties) or {"start_x", "end_x"} & set(properties), (
            f"{action} is treated as coordinate-bearing but its schema has no "
            f"coordinates: {sorted(properties)}"
        )
    assert not focus_witness.geometry_matters("keyboard_type")
    assert not focus_witness.geometry_matters("keyboard_hotkey")
    assert not focus_witness.geometry_matters("desktop_navigate")


# --- point ownership: the other half of geometry ---------------------------------
#
# The rect comparison was only half the check, and the weaker half. It says the
# window has not moved; it says nothing about whether a click at (x, y) reaches
# *that* window. Coordinates inside a window's rectangle still land on whatever
# is stacked on top at that point, because Windows delivers a click by z-order.
#
# Containment in the rect was the obvious fix and is the wrong one: necessary,
# not sufficient. Asking the OS which window owns the point answers the real
# question, and subsumes containment -- a point a window owns is inside its
# visible region by construction.


def test_a_click_on_another_window_refuses_even_inside_the_rect(monkeypatch) -> None:
    """The gap this tier closes, stated as the case the rect misses.

    Same window, same position, coordinates well inside its rectangle -- and
    something else on top at that point. The rect tier sees nothing wrong.
    """
    monkeypatch.setattr(focus_witness, "POINT_OWNER", lambda x, y: 0xBEEF)
    inside = {"x": 500, "y": 400}
    staged = make_witness()

    verdict = focus_witness.compare(
        staged, make_witness(), action=COORDINATE_ACTION, parameters=inside
    )

    assert verdict.matched is False
    assert "point_owner" in verdict.differences
    assert "no longer on the Notepad window" in verdict.reason
    # The point is inside the rect, so containment alone would have allowed it.
    left, top, right, bottom = staged.rect
    assert left < inside["x"] < right and top < inside["y"] < bottom


def test_a_click_the_witnessed_window_owns_is_allowed(owned_points) -> None:
    verdict = focus_witness.compare(
        make_witness(), make_witness(), action=COORDINATE_ACTION, parameters=CLICK_AT
    )

    assert verdict.matched is True, verdict


def test_an_unattributable_point_refuses(monkeypatch) -> None:
    """Nobody owns it, or the question could not be asked. Same rule as a failed
    capture: unchecked is not approved."""
    monkeypatch.setattr(focus_witness, "POINT_OWNER", lambda x, y: 0)

    verdict = focus_witness.compare(
        make_witness(), make_witness(), action=COORDINATE_ACTION, parameters=CLICK_AT
    )

    assert verdict.matched is False
    assert "point_unowned" in verdict.differences


def test_a_coordinate_action_with_no_coordinates_refuses() -> None:
    """A coordinate-bearing action whose coordinates were not supplied."""
    for parameters in (None, {}, {"x": 5}, {"x": "left", "y": 5}):
        verdict = focus_witness.compare(
            make_witness(),
            make_witness(),
            action=COORDINATE_ACTION,
            parameters=parameters,
        )

        assert verdict.matched is False, parameters
        assert "point_unknown" in verdict.differences, parameters


def test_both_ends_of_a_drag_are_checked(monkeypatch) -> None:
    """A drag that starts on the window and ends elsewhere is still a drag away."""
    seen: list[tuple[int, int]] = []

    def owner(x: int, y: int) -> int:
        seen.append((x, y))
        return int(NOTEPAD["hwnd"]) if (x, y) == (110, 110) else 0xBEEF

    monkeypatch.setattr(focus_witness, "POINT_OWNER", owner)

    verdict = focus_witness.compare(
        make_witness(),
        make_witness(),
        action="mouse_drag",
        parameters={"start_x": 110, "start_y": 110, "end_x": 5000, "end_y": 5000},
    )

    assert verdict.matched is False
    assert "point_owner" in verdict.differences
    assert seen == [(110, 110), (5000, 5000)], seen


def test_a_keystroke_has_no_points_to_check(monkeypatch) -> None:
    """The tier must be silent for actions that follow focus.

    Asking who owns a point would be meaningless for typing, and requiring
    coordinates would refuse every keystroke.
    """
    monkeypatch.setattr(
        focus_witness,
        "POINT_OWNER",
        lambda x, y: pytest.fail("the point tier ran for a keystroke"),
    )

    verdict = focus_witness.compare(
        make_witness(), make_witness(), action=FOCUS_ACTION, parameters={"text": "hi"}
    )

    assert verdict.matched is True


def test_the_point_parameters_match_the_catalogue_schemas() -> None:
    """Every named coordinate really is a parameter of that action."""
    from grandpa.action_layer.catalogue import get

    for action, pairs in focus_witness.POINT_PARAMETERS.items():
        properties = (get(action).parameters or {}).get("properties") or {}
        for x_name, y_name in pairs:
            assert x_name in properties, f"{action} has no {x_name}"
            assert y_name in properties, f"{action} has no {y_name}"


# --- control: hard when the action named one -------------------------------------


def test_a_vanished_control_refuses() -> None:
    """Staged against a control that is no longer resolvable.

    Uses a focus action rather than a click on purpose: the control tier applies
    to any action, and driving it through a coordinate-bearing one would let the
    point tier answer first, which is what happened when the point tier landed.
    Typing into a named control ("type into the Search box") is the honest shape
    for this test.
    """
    staged = make_witness(control_id="SaveButton|Button|save")
    current = make_witness(control_id="")

    verdict = focus_witness.compare(staged, current, action=FOCUS_ACTION)

    assert verdict.matched is False
    assert "control_id" in verdict.differences
    assert "no longer there" in verdict.reason


def test_a_changed_control_type_refuses(owned_points) -> None:
    staged = make_witness(control_id="SaveButton|Button|save")
    current = make_witness(control_id="SaveButton|MenuItem|save")

    verdict = focus_witness.compare(
        staged, current, action=COORDINATE_ACTION, parameters=CLICK_AT
    )

    assert verdict.matched is False
    assert "control_id" in verdict.differences


def test_no_control_named_means_the_tier_is_silent() -> None:
    """Both blank is not a match-by-accident: it means no control was named."""
    verdict = focus_witness.compare(
        make_witness(control_id=""), make_witness(control_id=""), action=FOCUS_ACTION
    )

    assert verdict.matched is True
    assert "control_id" not in verdict.differences


def test_the_control_is_resolved_rather_than_carried(monkeypatch) -> None:
    """capture() looks the control up, so the tier can disagree with itself.

    If the staged control_id were copied from the action's parameters, it would
    equal itself at redemption and the tier would never fire.
    """
    monkeypatch.setattr(
        focus_witness,
        "_foreground_reading",
        lambda: {
            "hwnd": 7,
            "pid": 8,
            "class_name": "Notepad",
            "rect": (0, 0, 10, 10),
            "title": "Untitled",
        },
    )
    monkeypatch.setattr(focus_witness, "_executable_for", lambda pid: "c:\\n.exe")
    monkeypatch.setattr(
        focus_witness, "CONTROL_RESOLVER", lambda hwnd, target: f"resolved:{target}"
    )

    witness = focus_witness.capture(control_target="Delete")

    assert witness is not None
    assert witness.control_id == "resolved:Delete"


def test_an_unresolvable_control_fails_capture(monkeypatch) -> None:
    """Named a control that is not there, so there is nothing to witness."""
    monkeypatch.setattr(
        focus_witness,
        "_foreground_reading",
        lambda: {
            "hwnd": 7,
            "pid": 8,
            "class_name": "Notepad",
            "rect": (0, 0, 10, 10),
            "title": "Untitled",
        },
    )
    monkeypatch.setattr(focus_witness, "_executable_for", lambda pid: "c:\\n.exe")
    monkeypatch.setattr(focus_witness, "CONTROL_RESOLVER", lambda hwnd, target: "")

    assert focus_witness.capture(control_target="Delete") is None


# --- title: soft, never decisive -------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Untitled - Notepad", "*Untitled - Notepad"),
        ("(2) Inbox - Outlook", "(3) Inbox - Outlook"),
        ("Report.docx - Word", "Report.docx  -  Word"),
        ("Meeting 10:30 AM - Calendar", "Meeting 11:45 AM - Calendar"),
        ("Rendering 12s - Editor", "Rendering 45s - Editor"),
    ],
)
def test_a_title_that_changes_on_its_own_is_not_a_mismatch(
    before: str, after: str
) -> None:
    """These all describe the same window. Refusing on them would be noise."""
    staged = make_witness(title=before)
    current = make_witness(title=after)

    verdict = focus_witness.compare(staged, current, action=FOCUS_ACTION)

    assert verdict.matched is True, f"{before!r} -> {after!r} refused"


def test_a_real_title_change_is_recorded_but_still_not_decisive() -> None:
    """Soft means soft: it is reported for the read-back and the audit, not acted on.

    A different document in the same editor is a genuine change and the user
    should hear about it -- but the hard fields are what refuse, because a title
    is not a reliable signal either way.
    """
    staged = make_witness(title="Report.docx - Word")
    current = make_witness(title="Budget.xlsx - Word")

    verdict = focus_witness.compare(staged, current, action=FOCUS_ACTION)

    assert verdict.matched is True
    assert verdict.title_drifted is True
    assert verdict.extra["staged_title"] == "Report.docx - Word"
    assert verdict.extra["current_title"] == "Budget.xlsx - Word"


def test_normalising_a_title_strips_only_what_moves_by_itself() -> None:
    assert focus_witness.normalise_title("*Untitled - Notepad") == "untitled - notepad"
    assert focus_witness.normalise_title("(12) Inbox") == "inbox"
    assert focus_witness.normalise_title("  A   B  ") == "a b"
    # Not stripped: a number that is part of the name.
    assert "2024" in focus_witness.normalise_title("Budget 2024.xlsx")


# --- a failed capture is a mismatch, not a pass ----------------------------------


@pytest.mark.parametrize(
    ("staged", "current", "expected"),
    [
        (None, "witness", "nothing recorded"),
        ("witness", None, "could not be read now"),
        (None, None, "neither"),
    ],
)
def test_a_missing_reading_refuses(staged, current, expected: str) -> None:
    """The alternative is a blank that compares equal to anything at all."""
    verdict = focus_witness.compare(
        make_witness() if staged else None,
        make_witness() if current else None,
        action=FOCUS_ACTION,
    )

    assert verdict.matched is False
    assert expected in verdict.reason


def test_capture_returns_none_when_the_window_cannot_be_read(monkeypatch) -> None:
    monkeypatch.setattr(focus_witness, "_foreground_reading", lambda: None)

    assert focus_witness.capture() is None


def test_capture_returns_none_without_an_executable_path(monkeypatch) -> None:
    """exe_path is the field that says which application this is."""
    monkeypatch.setattr(
        focus_witness,
        "_foreground_reading",
        lambda: {
            "hwnd": 1,
            "pid": 2,
            "class_name": "X",
            "rect": (0, 0, 1, 1),
            "title": "t",
        },
    )
    monkeypatch.setattr(focus_witness, "_executable_for", lambda pid: "")

    assert focus_witness.capture() is None
