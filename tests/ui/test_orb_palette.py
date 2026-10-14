"""One palette, two surfaces, and the colour that is deliberately unused.

The fault this exists to prevent is not a wrong hue; it is *two* palettes. The
orb drew idle blue while the panel's dot drew idle green, and thinking was blue
on one surface and violet on the other. A colour that means two things means
nothing, and nothing in either file would have told you.
"""

from __future__ import annotations

import pytest

from grandpa.ui.palette import (
    AMBER_UNREAD,
    BLUE_LISTENING,
    GREEN_SUCCESS,
    NEUTRAL_WHITE,
    ORANGE_SPEAKING,
    PURPLE_EXECUTING,
    RED_ERROR,
    RING_COLOURS,
    YELLOW_PROCESSING,
    rgb,
    ring_colour,
    ring_rgb,
)

pytestmark = pytest.mark.core


# --- 1. the values asked for --------------------------------------------------

#: The table as it was specified, so a drifted hex fails here and names itself.
SPECIFIED = {
    "idle": "#E5E7EB",
    "recording": "#168BFF",
    "thinking": "#FFD21F",
    "error": "#FF3B45",
    "success": "#22C55E",
    "speaking": "#FF922B",
}


@pytest.mark.parametrize("state,expected", sorted(SPECIFIED.items()))
def test_each_state_has_the_colour_it_was_given(state: str, expected: str) -> None:
    assert ring_colour(state).upper() == expected


def test_the_named_constants_are_the_table() -> None:
    """So a caller can say BLUE_LISTENING rather than repeat a hex."""
    assert (NEUTRAL_WHITE, BLUE_LISTENING, YELLOW_PROCESSING) == (
        "#E5E7EB", "#168BFF", "#FFD21F",
    )
    assert (RED_ERROR, GREEN_SUCCESS, ORANGE_SPEAKING) == (
        "#FF3B45", "#22C55E", "#FF922B",
    )


# --- 2. both surfaces read it -------------------------------------------------


def test_the_panel_and_the_orb_agree_about_every_state() -> None:
    """The whole point. Compared value by value rather than by identity, so
    rebuilding either dict cannot quietly reintroduce a second palette."""
    from grandpa.ui.orb_image import ORB_STYLES
    from grandpa.ui.tk_view import STATE_COLOURS

    for state, style in ORB_STYLES.items():
        assert style.colour == ring_rgb(state), f"the orb disagrees about {state}"
        if state in STATE_COLOURS:
            assert rgb(STATE_COLOURS[state]) == style.colour, (
                f"the panel's dot disagrees about {state}"
            )


def test_the_panel_no_longer_calls_idle_green() -> None:
    """It did, while the orb called it blue -- the specific disagreement that
    started this."""
    from grandpa.ui.tk_view import STATE_COLOURS

    assert STATE_COLOURS["idle"].upper() == NEUTRAL_WHITE
    assert STATE_COLOURS["idle"].upper() != GREEN_SUCCESS


def test_the_orb_holds_no_colour_of_its_own() -> None:
    """Inspected as a syntax tree: every OrbStyle's colour must be a call, not
    a literal tuple. A hardcoded hue would otherwise sit there agreeing with
    the palette until the day somebody changed one of them."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/grandpa/ui/orb_image.py").read_text(encoding="utf-8"))
    styles = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "OrbStyle"
    ]

    assert styles, "no OrbStyle calls found"
    for style in styles:
        first = style.args[0]
        assert isinstance(first, ast.Call), (
            f"a colour is written into orb_image at line {style.lineno}"
        )


# --- 3. the colour nothing uses ----------------------------------------------


def test_purple_is_mapped_now_that_something_real_sets_it() -> None:
    """It was reserved and unmapped for two rounds, because nothing told the
    bubble when an automation was running. It is mapped now because
    ``action_layer.executor`` has exactly one site where a catalogued action is
    performed, and it announces the span. The state is set from that
    announcement and from nothing else -- see
    tests/ui/test_orb_executing_state.py, which asserts no dry run and no
    staged approval can light it."""
    assert PURPLE_EXECUTING == "#A855F7"
    assert RING_COLOURS["executing"] == PURPLE_EXECUTING

    users = [state for state, value in RING_COLOURS.items() if value == PURPLE_EXECUTING]

    assert users == ["executing"], f"purple is also used by {users}"


# --- 4. the overlay -----------------------------------------------------------


def test_unread_wins_over_whatever_the_state_is() -> None:
    assert ring_colour("idle", unread=True) == AMBER_UNREAD
    assert ring_colour("error", unread=True) == AMBER_UNREAD


def test_unread_is_not_the_speaking_orange() -> None:
    """They are close on purpose and safe only because they cannot co-occur --
    unread requires the reply was *not* spoken. Still, not the same value: the
    panel shows both and a reader must be able to tell them apart."""
    assert AMBER_UNREAD != ORANGE_SPEAKING


def test_an_unknown_state_falls_back_to_neutral_rather_than_raising() -> None:
    """A UI must not die of a state name it has not met."""
    assert ring_colour("something-new") == NEUTRAL_WHITE


# --- 5. the conversion --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("#E5E7EB", (229, 231, 235)),
        ("E5E7EB", (229, 231, 235)),
        ("#fff", (255, 255, 255)),
        ("#000000", (0, 0, 0)),
    ],
)
def test_hex_becomes_channels(text: str, expected: tuple[int, int, int]) -> None:
    assert rgb(text) == expected


@pytest.mark.parametrize("bad", ["", "#12", "#1234567", "nope"])
def test_a_colour_that_is_not_one_is_refused_loudly(bad: str) -> None:
    """Not silently defaulted: a typo in a palette should fail at import, where
    it is one line to find, not render as black at three in the morning."""
    with pytest.raises(ValueError):
        rgb(bad)


def test_every_palette_entry_converts() -> None:
    for state, colour in RING_COLOURS.items():
        channels = rgb(colour)
        assert len(channels) == 3, state
        assert all(0 <= value <= 255 for value in channels), state


# --- 6. the label that had to change -----------------------------------------


def test_idle_says_standby_not_ready() -> None:
    """Green means an operation completed. A neutral-white ring labelled
    "Ready" would have contradicted it on the same window."""
    from grandpa.ui.bubble import STATE_LABELS, BubbleState

    assert STATE_LABELS[BubbleState.IDLE] == "Standby"
    assert "Ready" not in STATE_LABELS.values()
