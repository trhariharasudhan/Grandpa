"""The ring is smaller, still centred, and still above the legibility floor.

"Smaller" is easy to assert and almost worthless on its own: the interesting
claims are that *nothing else moved* -- the proportions, the centring, the
animation -- and that it did not go so small that the 125% bitmap stretch eats
the band. The second one cannot be answered from the generated image, so the
numbers it is pinned against were measured on screen over a known backdrop:

    radius   stroke     peak of 765   band at half peak   solid share
    0.30     2.88 px    276           3 physical px       5.8%
    0.26     2.50 px    265           3 physical px       3.9%   <- shipped
    0.20     1.92 px    234           2 physical px       2.3%   starts to dim
    0.12     1.15 px    172           2 physical px       0.9%   not a ring

The dimming is the supersampled stroke rounding down below two pixels, which is
why the floor assertion below is about the stroke and not about the radius.
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
    SUPERSAMPLE,
    is_animated,
    orb_image,
    scaled_width,
)

pytestmark = pytest.mark.core

#: What the ring was before this round, so "smaller" is a comparison against a
#: number rather than a claim.
PRE_REDUCTION_RADIUS = 0.30
PRE_REDUCTION_WIDTH = 0.030


def alpha_of(image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[:, :, 3].astype(float)


def radius_map(size: int) -> np.ndarray:
    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    return np.hypot(xs - centre, ys - centre) / size


# --- 1. it is smaller, by a stated amount ------------------------------------


def test_the_ring_is_smaller_than_it_was() -> None:
    assert RING_RADIUS < PRE_REDUCTION_RADIUS
    assert RING_RADIUS == pytest.approx(0.26, abs=1e-9)


def test_the_reduction_is_moderate_and_not_a_shrink_to_nothing() -> None:
    """"Compact and balanced, not small" was the brief. 13% of the radius is
    visible as a change; half of it would not be, and a third of it would be a
    dot."""
    reduction = 1.0 - RING_RADIUS / PRE_REDUCTION_RADIUS

    assert 0.08 < reduction < 0.20, f"reduced by {reduction:.1%}"


def test_the_measured_band_sits_at_the_new_radius() -> None:
    """Read off the pixels, not off the constant: a constant nobody drew with
    would pass the test above and change nothing on screen."""
    alpha = alpha_of(orb_image("idle", 0.0, 0.0))
    radii = radius_map(ORB_SIZE)
    lit = alpha >= 0.9 * alpha.max()
    mean_radius = float((radii[lit] * alpha[lit]).sum() / alpha[lit].sum())

    assert mean_radius == pytest.approx(RING_RADIUS, abs=0.02)
    assert mean_radius < PRE_REDUCTION_RADIUS - 0.02, "nothing actually moved"


# --- 2. the proportions did not change ---------------------------------------


def test_every_stroke_shrank_by_the_same_factor() -> None:
    """The whole point of one knob. A width left at its old value would make
    that state's ring proportionally fatter than the others."""
    assert RING_WIDTH == pytest.approx(PRE_REDUCTION_WIDTH * RING_SCALE)
    assert RING_RADIUS / PRE_REDUCTION_RADIUS == pytest.approx(RING_SCALE)
    assert RING_WIDTH / PRE_REDUCTION_WIDTH == pytest.approx(RING_SCALE)


def test_the_width_to_radius_ratio_is_what_it_always_was() -> None:
    """"Preserve the proportions" in one line: the ring is the same shape, just
    smaller. Keeping the stroke while shrinking the radius was measured as the
    alternative -- brighter and 3 points better on dead area -- and rejected
    because it thickens the ring by 15% relative to its own circle."""
    before = PRE_REDUCTION_WIDTH / PRE_REDUCTION_RADIUS
    after = RING_WIDTH / RING_RADIUS

    assert after == pytest.approx(before)


def test_no_stroke_was_left_behind_at_its_old_value() -> None:
    """Inspected as a syntax tree: every OrbStyle width must be a
    ``scaled_width(...)`` call. A bare literal would be a stroke that missed
    the reduction, and it would look almost right."""
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
        width = style.args[2] if len(style.args) > 2 else None
        assert isinstance(width, ast.Call), (
            f"a raw stroke width at line {style.lineno}"
        )
        assert isinstance(width.func, ast.Name) and width.func.id == "scaled_width", (
            f"line {style.lineno} does not go through scaled_width"
        )


def test_the_level_driven_thickening_scaled_too() -> None:
    """Otherwise a loud ring keeps its old thickness around a smaller circle
    and stops matching the quiet one."""
    quiet = ORB_STYLES["recording"].width
    loud_delta = scaled_width(0.028)

    assert loud_delta == pytest.approx(0.028 * RING_SCALE)
    # The widest the ring ever gets, still a sane fraction of the orb.
    assert quiet + loud_delta < 0.09


# --- 3. still centred --------------------------------------------------------


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_ring_is_perfectly_centred(state: str) -> None:
    """Measured as the centre of mass of the alpha over a whole cycle.

    Over one phase a travelling arc is lopsided on purpose -- that is what
    makes it look like it is going somewhere -- so a single frame says nothing
    about centring. Averaged across the cycle the picture is rotationally
    symmetric again, which makes this the stronger claim: the circle is centred
    *and* the rotation is about that same centre.
    """
    frames = [alpha_of(orb_image(state, index / 12.0, 0.0)) for index in range(12)]
    alpha = np.mean(frames, axis=0)
    total = alpha.sum()
    ys, xs = np.mgrid[0:ORB_SIZE, 0:ORB_SIZE]
    expected = (ORB_SIZE - 1) / 2.0

    assert float((xs * alpha).sum() / total) == pytest.approx(expected, abs=0.3), state
    assert float((ys * alpha).sum() / total) == pytest.approx(expected, abs=0.3), state


@pytest.mark.parametrize("state", ["idle", "recording", "success", "error"])
def test_a_full_ring_is_centred_in_a_single_frame(state: str) -> None:
    """The states with no arc have nothing to average away, so they are held to
    the tighter claim."""
    alpha = alpha_of(orb_image(state, 0.0, 0.0))
    total = alpha.sum()
    ys, xs = np.mgrid[0:ORB_SIZE, 0:ORB_SIZE]
    expected = (ORB_SIZE - 1) / 2.0

    assert float((xs * alpha).sum() / total) == pytest.approx(expected, abs=0.1)
    assert float((ys * alpha).sum() / total) == pytest.approx(expected, abs=0.1)


@pytest.mark.parametrize("size", [48, 96, 160])
def test_it_stays_centred_at_other_sizes(size: int) -> None:
    """Consistent sizing across resolutions: the geometry is fractions, so a
    bigger orb is the same picture bigger."""
    alpha = alpha_of(orb_image("idle", 0.0, 0.0, size=size))
    radii = radius_map(size)
    lit = alpha >= 0.9 * alpha.max()
    mean_radius = float((radii[lit] * alpha[lit]).sum() / alpha[lit].sum())

    assert mean_radius == pytest.approx(RING_RADIUS, abs=0.03)


# --- 4. above the floor ------------------------------------------------------


def test_the_stroke_is_still_at_least_two_pixels_after_downscaling() -> None:
    """This is the floor, and it is about the stroke rather than the radius.
    ``_ring_mask`` draws at SUPERSAMPLE times the size and rounds the stroke
    down with int(); once that lands under two final pixels, the LANCZOS
    downscale and then the 125% stretch leave a band that never reaches full
    intensity. Measured: peak brightness fell from 265 to 234 at a 1.92px
    stroke and to 172 at 1.15px.
    """
    for state, style in ORB_STYLES.items():
        supersampled = int(ORB_SIZE * SUPERSAMPLE * style.width)
        final = supersampled / SUPERSAMPLE

        assert final >= 2.0, (
            f"{state} draws a {final:.2f}px stroke, under the measured floor"
        )


def test_the_band_still_reaches_full_intensity_in_the_image() -> None:
    """If the stroke were too thin the anti-aliased core would never hit 255,
    and the stretch would start from an already-dim band."""
    for state in ORB_STYLES:
        assert alpha_of(orb_image(state, 0.3, 0.0)).max() == 255, state


def test_the_radius_is_not_taken_below_what_was_measured_as_readable() -> None:
    """0.20 was where it began to dim and 0.12 was no longer a ring. Nothing
    under 0.24 should be called premium, so this fails rather than letting a
    later tidy-up quietly cross the line."""
    assert RING_RADIUS >= 0.24


# --- 5. everything else is unchanged -----------------------------------------


def test_the_window_did_not_change_size() -> None:
    """The ring shrank inside the same rectangle. That is deliberate -- the
    glow keeps its room -- and it is why the dead-click area got worse, which
    is pinned below rather than discovered."""
    assert ORB_SIZE == 96
    assert orb_image("idle").size == (96, 96)


def test_the_corners_are_still_transparent() -> None:
    for state in ORB_STYLES:
        for level in (0.0, 1.0):
            alpha = alpha_of(orb_image(state, 0.5, level))
            corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]

            assert max(corners) <= 2, f"{state} at {level}: {corners}"


def test_the_dead_click_area_got_worse_by_the_amount_measured() -> None:
    """A smaller ring in the same window means more of the rectangle looks like
    desktop and still takes a click. Measured at 69.3% before and 76.7% after.
    Pinned so a later change has to notice it rather than drift."""
    alpha = alpha_of(orb_image("idle"))
    invisible = float((alpha < 8).sum()) / alpha.size
    solid = float((alpha > 128).sum()) / alpha.size

    assert invisible == pytest.approx(0.767, abs=0.03)
    assert solid == pytest.approx(0.039, abs=0.01)


def test_the_animation_is_untouched() -> None:
    """Which states move, and which cost nothing, did not change with the
    size."""
    assert is_animated("loading")
    assert is_animated("thinking")
    assert is_animated("speaking")
    assert not is_animated("idle")
    assert not is_animated("success")
    assert not is_animated("error")


def test_a_pulse_still_moves_and_a_still_state_still_does_not() -> None:
    moving = [np.asarray(orb_image("speaking", i / 8.0, 0.0)) for i in range(8)]
    still = [np.asarray(orb_image("idle", i / 8.0, 0.0)) for i in range(8)]

    assert any(not np.array_equal(moving[0], frame) for frame in moving[1:])
    assert all(np.array_equal(still[0], frame) for frame in still[1:])


def test_a_louder_microphone_still_makes_a_heavier_ring() -> None:
    weights = [
        float((alpha_of(orb_image("recording", 0.0, level)) > 64).sum())
        for level in (0.0, 0.5, 1.0)
    ]

    assert weights == sorted(weights)
    assert weights[-1] > 1.3 * weights[0]
