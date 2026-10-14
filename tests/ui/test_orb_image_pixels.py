"""The orb is asserted as pixels, not as a record that something was drawn.

This is the whole reason ``orb_image`` is a pure function. A recorded call log
can only say "a draw happened"; it cannot tell a ring from a blob, or catch a
ring that drifted to the wrong radius, or notice that the corners stopped being
transparent and the orb became a square. So every claim below is read off the
image: where the bright band sits, what colour it is, what the corners are, and
whether a louder microphone really does make the ring heavier.

Nothing here opens a window or touches tkinter.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from grandpa.ui.orb_image import (
    ANIMATED_STATES,
    ORB_SIZE,
    ORB_STYLES,
    RING_RADIUS,
    is_animated,
    orb_image,
    orb_on_disc,
    style_for,
    transparent_fraction,
)

pytestmark = pytest.mark.core


def alpha_of(image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[:, :, 3].astype(float)


def radius_map(size: int) -> np.ndarray:
    """Each pixel's distance from the centre, as a fraction of the size."""
    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    return np.hypot(xs - centre, ys - centre) / size


def band(image, inner: float, outer: float) -> np.ndarray:
    """The alpha values in an annulus, by fraction-of-size radius."""
    alpha = alpha_of(image)
    radii = radius_map(alpha.shape[0])
    return alpha[(radii >= inner) & (radii < outer)]


# --- 1. the ring is where it should be --------------------------------------


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_bright_band_sits_at_the_ring_radius(state: str) -> None:
    """Not "something was drawn" -- the brightest ring of pixels is at
    RING_RADIUS, within the ring's own thickness."""
    image = orb_image(state, 0.25, 0.0)
    alpha = alpha_of(image)
    radii = radius_map(alpha.shape[0])

    # The weighted mean radius of everything bright enough to read as the ring.
    bright = alpha >= 0.9 * alpha.max()
    assert bright.any(), f"{state}: nothing is bright"
    mean_radius = float((radii[bright] * alpha[bright]).sum() / alpha[bright].sum())

    width = ORB_STYLES[state].width
    assert abs(mean_radius - RING_RADIUS) <= width + 0.02, (
        f"{state}: the ring's bright band is at {mean_radius:.3f}, not {RING_RADIUS}"
    )


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_middle_is_a_hole_and_the_rim_is_empty(state: str) -> None:
    """A ring, not a disc and not a square. Both halves matter: a filled
    centre would be a blob, and alpha out at the rim would be a box."""
    image = orb_image(state, 0.25, 0.0)
    peak = alpha_of(image).max()

    middle = band(image, 0.0, 0.15)
    rim = band(image, 0.47, 0.71)

    assert middle.mean() < 0.25 * peak, f"{state}: the centre is filled in"
    assert rim.mean() < 0.25 * peak, f"{state}: alpha reaches the rim"


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_corners_are_transparent(state: str) -> None:
    """The literal corners of the rectangle, which is what makes the orb read
    as floating rather than as a tile. Measured at full level too, because the
    loudest ring is the widest glow and the most likely to reach the corner."""
    for level in (0.0, 1.0):
        alpha = alpha_of(orb_image(state, 0.5, level))
        corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]

        assert max(corners) <= 2, (
            f"{state} at level {level}: corners are {corners}, not transparent"
        )


def test_most_of_the_rectangle_is_not_the_orb() -> None:
    """The measurement behind the click-through decision, pinned.

    A layered window takes clicks on its whole rectangle, so what matters is
    not how much is *exactly* transparent but how much is invisible to the eye
    and still swallows a click. If this ever drops a long way, the orb has
    grown into its own rectangle and the problem has shrunk with it; if it
    rises, the dead area has grown. Either way it should be noticed here rather
    than in use.
    """
    alpha = alpha_of(orb_image("idle"))
    invisible = float((alpha < 8).sum()) / alpha.size
    solid = float((alpha > 128).sum()) / alpha.size

    # 76.7% in the 96px window, 43.8% in the 72px one. The ring occupies more
    # of a smaller window, and the analytic halo spreads more faint alpha, so
    # less of the rectangle reads as bare desktop than either the old renderer
    # or the 73.1% predicted from it.
    assert 0.3 < invisible < 0.6, f"invisible-but-clickable share is {invisible:.3f}"
    assert solid < 0.2, f"the orb now covers {solid:.3f} of its rectangle"


# --- 2. each state is its own colour ----------------------------------------


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_ring_is_the_colour_the_state_says(state: str) -> None:
    """Read off the pixels, not off the style table -- the table could be
    right while the drawing ignored it."""
    image = orb_image(state, 0.25, 0.0).convert("RGBA")
    pixels = np.asarray(image)
    alpha = pixels[:, :, 3]
    lit = alpha >= 0.9 * alpha.max()
    drawn = tuple(int(round(pixels[:, :, channel][lit].mean())) for channel in range(3))

    assert drawn == style_for(state).colour, f"{state} drew {drawn}"


#: Pairs that share a hue, split by *why* -- which turned out to be the part
#: worth asserting, because the two reasons imply opposite properties.
#:
#: Deliberately the same orb entirely. Both are indeterminate processing and
#: the difference is not actionable from across a room, so there is nothing for
#: a reader to tell apart and a difference would only be noise. This has been
#: true since the orb was built; nothing asserted it until now.
IDENTICAL_BY_DESIGN = {("thinking", "transcribing")}

#: Same hue, different orb. Both are neutral because neither is about a
#: request -- during loading there is not one yet -- but "not ready" and
#: "ready" is a distinction a reader acts on, so it is carried by geometry: a
#: travelling arc at half the glow, against a complete still ring.
HUE_SHARED_GEOMETRY_DIFFERS = {("idle", "loading")}

SHARED_HUES = IDENTICAL_BY_DESIGN | HUE_SHARED_GEOMETRY_DIFFERS


def test_the_states_sharing_a_hue_are_exactly_the_intended_pairs() -> None:
    seen: dict[tuple[int, int, int], list[str]] = {}
    for state in ORB_STYLES:
        seen.setdefault(style_for(state).colour, []).append(state)

    shared = {tuple(sorted(names)) for names in seen.values() if len(names) > 1}

    assert shared == SHARED_HUES, f"colours shared: {shared}"


@pytest.mark.parametrize("pair", sorted(IDENTICAL_BY_DESIGN))
def test_a_pair_that_shares_everything_renders_identically(
    pair: tuple[str, str],
) -> None:
    """Pinned, because "they look the same" is a decision and not an accident.
    If one of these ever drifts, it should be because somebody meant it."""
    first, second = (ORB_STYLES[name] for name in pair)

    assert (first.colour, first.arc, first.glow, first.width, first.pulse) == (
        second.colour, second.arc, second.glow, second.width, second.pulse,
    )
    assert np.array_equal(
        np.asarray(orb_image(pair[0], 0.3, 0.0)),
        np.asarray(orb_image(pair[1], 0.3, 0.0)),
    )


@pytest.mark.parametrize("pair", sorted(HUE_SHARED_GEOMETRY_DIFFERS))
def test_a_shared_hue_is_told_apart_by_geometry(pair: tuple[str, str]) -> None:
    """Not by a second colour that is nearly the first. Two greys a shade apart
    is the thing this replaced."""
    first, second = (ORB_STYLES[name] for name in pair)

    assert first.colour == second.colour, f"{pair} no longer shares a hue"
    assert (first.arc, first.glow, first.width, first.pulse) != (
        second.arc, second.glow, second.width, second.pulse,
    ), f"{pair} is identical in both colour and geometry"


@pytest.mark.parametrize("pair", sorted(HUE_SHARED_GEOMETRY_DIFFERS))
def test_a_shared_hue_still_renders_two_different_orbs(pair: tuple[str, str]) -> None:
    """Asserted on the pixels, because geometry numbers that differ and render
    the same are the actual risk."""
    first, second = (alpha_of(orb_image(name, 0.0, 0.0)) for name in pair)
    differing = float((np.abs(first - second) > 8).mean())

    assert differing > 0.05, (
        f"{pair} differ in only {differing:.1%} of pixels, which is not a glance apart"
    )


def test_loading_is_dimmer_and_travels_where_idle_only_breathes() -> None:
    """The pair that shares a hue, stated as the two things a reader uses. Both
    move now, so the difference is the *kind* of movement: a travelling arc
    against a ring that only swells."""
    loading, idle = ORB_STYLES["loading"], ORB_STYLES["idle"]

    assert loading.colour == idle.colour
    assert loading.glow < idle.glow
    assert loading.animation == "arc"
    assert idle.animation == "breathe"
    assert loading.arc is not None
    assert idle.arc is None


def test_the_unread_ring_overrides_whatever_the_state_is() -> None:
    """Amber wins, because the unseen reply is the thing worth saying."""
    plain = orb_image("idle", 0.0, 0.0)
    flagged = orb_image("idle", 0.0, 0.0, unread=True)

    assert style_for("idle", unread=True) == ORB_STYLES["unread"]
    assert not np.array_equal(np.asarray(plain), np.asarray(flagged))


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_unread_overrides_every_state_including_success(state: str) -> None:
    """Success is the one worth naming: an automation finished *and* nobody has
    read the reply is the case where a persistent green would hide the amber.
    Read off the pixels, not off the style table."""
    import numpy as np

    flagged = np.asarray(orb_image(state, 0.25, 0.0, unread=True))
    unread = np.asarray(orb_image("unread", 0.25, 0.0))

    assert np.array_equal(flagged, unread), f"{state} + unread did not render as unread"


def test_success_and_unread_do_not_look_alike() -> None:
    """Green persists and amber must still be able to replace it visibly."""
    green = alpha_of(orb_image("success", 0.25, 0.0))
    amber = alpha_of(orb_image("success", 0.25, 0.0, unread=True))

    assert style_for("success").colour != style_for("success", unread=True).colour
    assert float((np.abs(green - amber) > 8).mean()) > 0.02


# --- 3. listening is driven by the level, as pixels -------------------------


def test_a_louder_microphone_makes_a_heavier_ring() -> None:
    """The level the panel's meter consumes, visible with no panel to look at.

    Asserted as a monotonic rise in lit area, not as "the parameter was
    passed": a ring that ignored the level would pass a call-log test.
    """
    weights = [
        float((alpha_of(orb_image("recording", 0.0, level)) > 64).sum())
        for level in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]

    assert weights == sorted(weights), f"not monotonic: {weights}"
    assert weights[-1] > 1.3 * weights[0], (
        f"full level is barely heavier than silence: {weights[0]} -> {weights[-1]}"
    )


def test_the_level_is_ignored_by_states_that_are_not_listening() -> None:
    """Otherwise a stale level would keep animating a finished state."""
    for state in ("idle", "thinking", "speaking", "error"):
        quiet = np.asarray(orb_image(state, 0.0, 0.0))
        loud = np.asarray(orb_image(state, 0.0, 1.0))

        assert np.array_equal(quiet, loud), f"{state} responded to the level"


def test_the_level_is_clamped_rather_than_trusted() -> None:
    """The RMS comes from a device. Out-of-range must not raise or explode."""
    for level in (-5.0, 1.5, 99.0):
        image = orb_image("recording", 0.0, level)

        assert image.size == (ORB_SIZE, ORB_SIZE)
        assert alpha_of(image).max() <= 255


# --- 4. the pulse, and the states that do not have one ----------------------


def test_a_pulsing_state_actually_changes_between_frames() -> None:
    frames = [np.asarray(orb_image("speaking", i / 8.0, 0.0)) for i in range(8)]

    assert any(not np.array_equal(frames[0], frame) for frame in frames[1:])


def test_the_cycle_closes_so_the_loop_has_no_seam() -> None:
    """Phase 1.0 is phase 0.0. A cosine gives that; a sawtooth would not."""
    for state in sorted(ANIMATED_STATES):
        start = np.asarray(orb_image(state, 0.0, 0.0))
        wrapped = np.asarray(orb_image(state, 1.0, 0.0))

        assert np.array_equal(start, wrapped), f"{state} jumps at the wrap"


def test_idle_breathes_slowly_rather_than_holding_still() -> None:
    """Idle was still so the tick could be cancelled and cost nothing. It
    breathes now because the cost was measured rather than assumed: 0.14% of
    one core at 5 frames a second, against 0.56% at 20. The property that
    mattered -- a state which holds still cancels its tick -- survives on
    success and error, and is pinned in test_orb_window.py."""
    from grandpa.ui.orb_image import fps_for

    assert is_animated("idle")
    assert "idle" in ANIMATED_STATES
    assert fps_for("idle") == 5.0, "a breathe that runs forever runs slowly"

    frames = [np.asarray(orb_image("idle", i / 6.0, 0.0)) for i in range(6)]

    assert any(not np.array_equal(frames[0], frame) for frame in frames[1:])


def test_the_breathe_is_subtle_rather_than_a_pulse() -> None:
    """"Very subtle" was the brief. Measured as the swing in lit area across
    the cycle, which a throb would blow well past."""
    areas = [
        float((alpha_of(orb_image("idle", index / 12.0, 0.0)) > 64).sum())
        for index in range(12)
    ]
    swing = (max(areas) - min(areas)) / max(areas)

    assert 0.01 < swing < 0.30, f"the breathe swings {swing:.1%} of its lit area"


def test_an_unread_orb_is_animated_even_though_idle_is_not() -> None:
    """Otherwise the amber ring would be a still dot nobody notices."""
    assert is_animated("idle", unread=True)


def test_every_controller_state_has_a_look() -> None:
    """A state with no entry would silently fall back to idle, which is the
    bug where loading looked ready."""
    from grandpa.ui.bubble import BubbleState

    missing = [str(state) for state in BubbleState if str(state) not in ORB_STYLES]

    assert missing == []


# --- 5. the fallback's own pixels -------------------------------------------


def test_the_fallback_is_an_opaque_disc_with_the_same_ring() -> None:
    """The flat-disc look, for when per-pixel alpha is refused. Worse-looking
    and always works -- but it has to actually be a usable orb, which means the
    ring is still there and still in the same place."""
    disc = orb_on_disc("idle")
    alpha = alpha_of(disc)
    size = alpha.shape[0]

    assert alpha[size // 2, size // 2] == 255, "the disc is not opaque"
    assert alpha[0, 0] == 0, "the disc filled the corners"

    pixels = np.asarray(disc.convert("RGBA"))
    radii = radius_map(size)
    ring = (radii >= RING_RADIUS - 0.03) & (radii <= RING_RADIUS + 0.03)
    middle = radii < 0.12
    # The ring is lighter than the disc it sits on, which is what makes it
    # visible at all once the glow has nowhere to fall off to.
    assert pixels[:, :, :3][ring].mean() > pixels[:, :, :3][middle].mean() + 20


def test_the_fallback_covers_the_rectangle_far_less_than_a_square_would() -> None:
    """A disc, not a tile: the corners still read as desktop."""
    assert 0.15 < transparent_fraction(orb_on_disc("idle")) < 0.40


def test_both_looks_exist_for_every_state() -> None:
    """The fallback is built beside the real one, so a state cannot be added to
    one and forgotten in the other."""
    for state in ORB_STYLES:
        assert orb_on_disc(state, 0.5, 0.0).size == (ORB_SIZE, ORB_SIZE)


# --- 6. the geometry is honoured at other sizes -----------------------------


@pytest.mark.parametrize("size", [48, 96, 160])
def test_the_ring_scales_with_the_orb(size: int) -> None:
    """The radius is a fraction, so a bigger orb is the same picture bigger --
    not the same ring in a bigger box."""
    image = orb_image("idle", 0.0, 0.0, size=size)
    alpha = alpha_of(image)
    radii = radius_map(size)
    bright = alpha >= 0.9 * alpha.max()
    mean_radius = float((radii[bright] * alpha[bright]).sum() / alpha[bright].sum())

    assert image.size == (size, size)
    assert math.isclose(mean_radius, RING_RADIUS, abs_tol=0.05)
