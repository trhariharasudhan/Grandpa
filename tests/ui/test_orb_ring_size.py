"""The orb is smaller because the WINDOW shrank, not because the ring did again.

The complaint was that the ring looked thin inside a large window. Shrinking the
radius a second time would have made that worse on both counts -- a thinner
stroke toward the measured two-pixel floor, and more of the window reading as
bare desktop while still taking a click.

So the window went 96 -> 72 and the stroke was pinned at an absolute 2.5 logical
pixels instead of a fraction of the window. Measured on screen over a magenta
backdrop, before and after:

    window   ring diameter   stroke   outer lit   band at half peak   peak
    96/120   49.9 / 62.4     2.50     64 px       3 physical px       264.6
    72/90    37.4 / 46.8     2.50     48 px       4 physical px       263.3

Same brightness, a *wider* band on screen, and the stroke is now 6.7% of the
ring's diameter rather than 5.0% -- a third thicker relative to its own circle,
which is the thing that was actually wrong.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from grandpa.ui.orb_image import (
    ORB_SIZE,
    ORB_STYLES,
    RING_RADIUS,
    RING_SCALE,
    RING_WIDTH,
    STROKE_PX,
    is_animated,
    orb_image,
    scaled_width,
)

pytestmark = pytest.mark.core

#: The window before this round, so "smaller" is a comparison and not a claim.
PREVIOUS_WINDOW = 96
#: The radius fraction, unchanged. The ring shrank with the window, not inside it.
PREVIOUS_RADIUS = 0.30 * RING_SCALE


def alpha_of(image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[:, :, 3].astype(float)


def radius_map(size: int) -> np.ndarray:
    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    return np.hypot(xs - centre, ys - centre) / size


# --- 1. the window shrank, the ring ratio did not ----------------------------


def test_the_window_is_smaller_than_it_was() -> None:
    assert ORB_SIZE == 72
    assert ORB_SIZE < PREVIOUS_WINDOW
    assert orb_image("idle").size == (72, 72)


def test_the_ring_still_sits_at_the_same_fraction_of_the_window() -> None:
    """The radius was NOT reduced again. Doing both would have taken the stroke
    toward the floor and made the dead area worse."""
    assert RING_RADIUS == pytest.approx(PREVIOUS_RADIUS)
    assert RING_RADIUS == pytest.approx(0.26)


def test_the_reduction_is_moderate() -> None:
    reduction = 1.0 - ORB_SIZE / PREVIOUS_WINDOW

    assert 0.15 < reduction < 0.35, f"window reduced by {reduction:.1%}"


# --- 2. the stroke is absolute now, which is the actual fix ------------------


def test_the_stroke_is_pinned_in_pixels_not_in_a_fraction() -> None:
    """Held at 2.5 logical pixels. A fraction of a smaller window would have
    thinned it, and the measured floor is two final pixels."""
    assert STROKE_PX == 2.5
    assert RING_WIDTH == pytest.approx(STROKE_PX / ORB_SIZE)
    assert ORB_STYLES["idle"].width * ORB_SIZE == pytest.approx(STROKE_PX)


def test_the_ring_reads_thicker_relative_to_its_own_circle() -> None:
    """This is the "looks thin" complaint, as a number. 5.0% before, 6.7% now."""
    before = 0.030 * RING_SCALE / PREVIOUS_RADIUS
    after = RING_WIDTH / RING_RADIUS

    assert after > before * 1.25, f"{before:.3f} -> {after:.3f} is not thicker"


def test_every_stroke_kept_its_ratio_to_the_others() -> None:
    """Only the base changed. A state whose stroke was 1.73x idle's still is."""
    for pre_reduction in (0.028, 0.030, 0.034, 0.038, 0.040, 0.046):
        assert scaled_width(pre_reduction) == pytest.approx(
            RING_WIDTH * (pre_reduction / 0.030)
        )


def test_no_stroke_was_left_behind_at_an_old_value() -> None:
    """Inspected as a syntax tree: every OrbStyle width must be a
    ``scaled_width(...)`` call. A bare literal would be a stroke that missed
    the re-basing, and it would look almost right."""
    tree = ast.parse(Path("src/grandpa/ui/orb_image.py").read_text(encoding="utf-8"))
    styles = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "OrbStyle"
    ]

    assert len(styles) == len(ORB_STYLES), "not every style was found"
    for style in styles:
        widths = [
            keyword.value for keyword in style.keywords if keyword.arg == "width"
        ]
        width = style.args[2] if len(style.args) > 2 else (widths[0] if widths else None)
        assert isinstance(width, ast.Call), f"a raw stroke width at line {style.lineno}"
        assert isinstance(width.func, ast.Name) and width.func.id == "scaled_width", (
            f"line {style.lineno} does not go through scaled_width"
        )


# --- 3. still above the floor ------------------------------------------------


def test_the_stroke_is_still_at_least_two_logical_pixels() -> None:
    """The measured floor, and it is about the stroke rather than the radius:
    peak brightness fell from 265 to 234 at a 1.92px stroke and to 172 at
    1.15px, because what is left of a sub-two-pixel line never reaches full
    intensity once it has been stretched to 125%."""
    for state, style in ORB_STYLES.items():
        pixels = style.width * ORB_SIZE

        assert pixels >= 2.0, f"{state} draws a {pixels:.2f}px stroke"


def test_the_band_still_reaches_full_intensity() -> None:
    for state in ORB_STYLES:
        assert alpha_of(orb_image(state, 0.3, 0.0)).max() == 255, state


# --- 4. still centred, at every size ----------------------------------------


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_ring_is_perfectly_centred(state: str) -> None:
    """Centre of mass over a whole cycle. Over one phase a travelling arc is
    lopsided on purpose; averaged across the cycle the picture is rotationally
    symmetric again, which makes this the stronger claim -- the circle is
    centred *and* the rotation is about the same centre."""
    frames = [alpha_of(orb_image(state, index / 12.0, 0.0)) for index in range(12)]
    alpha = np.mean(frames, axis=0)
    total = alpha.sum()
    ys, xs = np.mgrid[0:ORB_SIZE, 0:ORB_SIZE]
    expected = (ORB_SIZE - 1) / 2.0

    assert float((xs * alpha).sum() / total) == pytest.approx(expected, abs=0.3), state
    assert float((ys * alpha).sum() / total) == pytest.approx(expected, abs=0.3), state


@pytest.mark.parametrize("size", [48, 72, 96, 160])
def test_the_whole_picture_scales_with_the_orb(size: int) -> None:
    """Consistent sizing across resolutions, and this is new: the halo used to
    be absolute blur radii, so the orb was not actually resolution-independent.
    It is a multiple of the stroke now, and the stroke is a fraction of the
    size, so the same picture comes out at any size."""
    alpha = alpha_of(orb_image("idle", 0.0, 0.0, size=size))
    radii = radius_map(size)
    lit = alpha >= 0.9 * alpha.max()
    mean_radius = float((radii[lit] * alpha[lit]).sum() / alpha[lit].sum())

    assert mean_radius == pytest.approx(RING_RADIUS, abs=0.03)
    assert alpha[0, 0] <= 2, "a corner stopped being transparent"


# --- 5. the dead-click share, which improved --------------------------------


def test_the_dead_click_share_improved() -> None:
    """A smaller window with the same ring ratio means the ring occupies more
    of it. Measured at 76.7% invisible-but-clickable before and 43.8% now --
    better than the 73.1% predicted from the old blur-stack renderer, because
    the analytic halo spreads more faint alpha and less of the rectangle reads
    as bare desktop."""
    alpha = alpha_of(orb_image("idle"))
    invisible = float((alpha < 8).sum()) / alpha.size
    solid = float((alpha > 128).sum()) / alpha.size

    assert invisible < 0.60, f"{invisible:.1%} is no better than it was"
    assert invisible == pytest.approx(0.438, abs=0.05)
    assert solid > 0.05, f"the ring covers only {solid:.2%} of the window"


def test_the_corners_are_still_transparent() -> None:
    for state in ORB_STYLES:
        for level in (0.0, 1.0):
            alpha = alpha_of(orb_image(state, 0.5, level))
            corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]

            assert max(corners) <= 2, f"{state} at {level}: {corners}"


def test_the_middle_is_still_a_hole() -> None:
    """The halo is a stack of Gaussians now, and an unnormalised one wide
    enough to look like a glow fills the centre -- measured at alpha 30 of 255
    during the rewrite, against 3 for the blur stack it replaced. The weights
    exist to stop that, so this is the test that keeps them honest."""
    for state in ORB_STYLES:
        alpha = alpha_of(orb_image(state, 0.25, 0.0))
        radii = radius_map(ORB_SIZE)
        middle = alpha[radii < 0.15].mean()

        assert middle < 0.25 * alpha.max(), f"{state}: the centre is filling in"


# --- 6. animation untouched by the resize ------------------------------------


def test_which_states_move_did_not_change_with_the_size() -> None:
    assert is_animated("loading")
    assert is_animated("thinking")
    assert is_animated("speaking")
    assert is_animated("idle"), "idle breathes now"
    assert is_animated("recording")


def test_a_louder_microphone_still_makes_a_heavier_ring() -> None:
    weights = [
        float((alpha_of(orb_image("recording", 0.0, level)) > 64).sum())
        for level in (0.0, 0.5, 1.0)
    ]

    assert weights == sorted(weights)
    assert weights[-1] > 1.15 * weights[0]
