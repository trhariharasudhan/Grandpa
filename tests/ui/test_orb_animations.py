"""Seven animations, each asserted on pixels rather than on its name.

A test that only checked "the frames differ" would pass for seven states all
doing the same thing. So each animation is checked for the property that makes
it that animation: the waves travel outward, the counter-arcs travel in
opposite directions, the chase's lit arc never grows, the error flashes exactly
twice, and the waveform follows the voice.

That last one is the one worth reading. A ring animated from phase alone would
move beautifully and say nothing, and it would pass every weaker test in this
file. So the waveform is asserted to be a pure function of the level history --
*identical* across phases -- and to put the ring's edge where the history says,
angle by angle.
"""

from __future__ import annotations

import numpy as np
import pytest

from grandpa.ui import orb_image as oi
from grandpa.ui.orb_image import (
    CHASE_LIT,
    CHASE_SEGMENTS,
    LEVEL_BUCKETS,
    ORB_SIZE,
    ORB_STYLES,
    RING_RADIUS,
    STILL_STATES,
    WAVEFORM_AMPLITUDE,
    fps_for,
    frames_for,
    is_animated,
    is_live,
    is_oneshot,
    level_at_angle,
    orb_image,
    orb_on_disc,
)

pytestmark = pytest.mark.core

#: The seven, as specified, plus the two the table did not cover.
EXPECTED_ANIMATIONS = {
    "idle": "breathe",
    "recording": "waveform",
    "transcribing": "counter_arcs",
    "thinking": "counter_arcs",
    "speaking": "waves",
    "success": "ripple",
    "error": "flash",
    "executing": "chase",
    "loading": "arc",
    "unread": "breathe",
}


def alpha_of(image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[:, :, 3].astype(float)


def fields():
    return oi._fields(ORB_SIZE)


def radius_profile(alpha: np.ndarray, bins: int = 36) -> np.ndarray:
    """Mean alpha in concentric annuli, out to the taper."""
    radius, _turns = fields()
    edges = np.linspace(0.0, 0.5, bins + 1)
    return np.array([
        alpha[(radius >= low) & (radius < high)].mean()
        if ((radius >= low) & (radius < high)).any() else 0.0
        for low, high in zip(edges, edges[1:])
    ])


def angular_profile(alpha: np.ndarray, bins: int = 48) -> np.ndarray:
    """Peak alpha per angular wedge, within the ring's own band."""
    radius, turns = fields()
    band = (radius > RING_RADIUS - 0.06) & (radius < RING_RADIUS + 0.09)
    edges = np.linspace(0.0, 1.0, bins + 1)
    return np.array([
        alpha[band & (turns >= low) & (turns < high)].max(initial=0.0)
        for low, high in zip(edges, edges[1:])
    ])


def ring_radius_at(alpha: np.ndarray, turn: float, window: float = 0.02) -> float:
    """Where the ring sits along one angle, as an alpha-weighted centroid.

    A plain ``argmax`` was the first attempt and it was wrong: a round ring has
    alpha 255 at many pixels in the wedge, so argmax picked an arbitrary one
    and reported a different radius each time. The giveaway was that silence --
    which must be a perfect circle -- measured as not round.
    """
    radius, turns = fields()
    near = np.abs(((turns - turn) + 0.5) % 1.0 - 0.5) < window
    bright = near & (alpha > 0.5 * alpha.max())
    if not bright.any():
        return float("nan")
    return float((radius[bright] * alpha[bright]).sum() / alpha[bright].sum())


def lead_wave_radius(alpha: np.ndarray) -> float:
    """The radius of the brightest thing just OUTSIDE the ring.

    Which is how a travelling wave is seen at all. The whole-image mean radius
    cannot see it -- with rings evenly spaced around the cycle the mean is
    constant by construction -- and the outer edge of the glow cannot either,
    because the halo reaches the taper at every phase. A state with no waves
    reads the floor of this band, which makes it a control rather than a
    number nobody can falsify.
    """
    radius, _turns = fields()
    # Wide enough to hold a whole journey: a ripple travels WAVE_SPAN * 1.4 of
    # the size, and at 64 pixels one radius step is 0.0156, so a narrow band is
    # only three or four samples and the measurement inverts.
    band = (radius > RING_RADIUS + 0.040) & (radius < RING_RADIUS + 0.220)
    values = np.where(band, alpha, -1.0)
    index = np.unravel_index(int(np.argmax(values)), values.shape)
    return float(radius[index])


def no_wave_floor() -> float:
    """What ``lead_wave_radius`` reads when there is nothing travelling.

    Derived rather than written down: it is the inner edge of the band the
    helper looks in, which moves with the orb's size. A literal was right at
    72 pixels and wrong at 64, which is a test that fails for the wrong
    reason."""
    return lead_wave_radius(alpha_of(orb_image("error", 0.95, 0.0)))


# --- 1. the seven exist and are what was asked for ---------------------------


def test_every_state_has_the_animation_it_was_given() -> None:
    actual = {name: style.animation for name, style in ORB_STYLES.items()}

    assert actual == EXPECTED_ANIMATIONS


def test_the_seven_named_animations_are_all_distinct_kinds() -> None:
    """Seven states, seven behaviours -- the two that share one share it
    deliberately, and that pair is asserted elsewhere."""
    seven = {
        EXPECTED_ANIMATIONS[state]
        for state in (
            "idle", "recording", "thinking", "speaking", "success", "error",
            "executing",
        )
    }

    assert seven == {
        "breathe", "waveform", "counter_arcs", "waves", "ripple", "flash", "chase",
    }


@pytest.mark.parametrize("state", sorted(EXPECTED_ANIMATIONS))
def test_every_animation_actually_changes_the_pixels(state: str) -> None:
    """The weakest possible claim, kept because its absence would be silent."""
    frames = [
        np.asarray(orb_image(state, index / 8.0, 0.4, levels=_ramp(index)))
        for index in range(8)
    ]

    assert any(not np.array_equal(frames[0], frame) for frame in frames[1:]), state


def _ramp(seed: int) -> tuple[float, ...]:
    return tuple(
        ((index + seed) % LEVEL_BUCKETS) / LEVEL_BUCKETS for index in range(LEVEL_BUCKETS)
    )


# --- 2. the waveform follows the voice ---------------------------------------


def test_the_waveform_is_a_pure_function_of_the_levels_not_the_phase() -> None:
    """**The point of the whole state.** A ring that rotated with phase would
    animate whether or not anyone was speaking, and would pass every other test
    in this file."""
    levels = tuple(
        0.5 + 0.5 * np.sin(index / 3.0) for index in range(LEVEL_BUCKETS)
    )
    first = np.asarray(orb_image("recording", 0.0, 0.0, levels=levels))

    for phase in (0.13, 0.37, 0.5, 0.91):
        assert np.array_equal(
            first, np.asarray(orb_image("recording", phase, 0.0, levels=levels))
        ), f"the waveform moved with phase {phase}"


def test_a_single_loud_sample_pushes_the_ring_out_at_that_angle_only() -> None:
    """A known shape in, and the ring's radius per angle read back out."""
    levels = [0.0] * LEVEL_BUCKETS
    spike = 8
    levels[spike] = 1.0
    alpha = alpha_of(orb_image("recording", 0.0, 0.0, levels=tuple(levels)))

    at_spike = ring_radius_at(alpha, spike / LEVEL_BUCKETS)
    away = [
        ring_radius_at(alpha, index / LEVEL_BUCKETS)
        for index in (spike + 8, spike + 16, spike + 24)
    ]

    assert at_spike > max(away) + 0.015, (
        f"the spike sits at {at_spike:.3f} and the quiet angles at {away}"
    )
    # Where the history says it should be: base + the full amplitude.
    assert at_spike == pytest.approx(RING_RADIUS + WAVEFORM_AMPLITUDE, abs=0.015)


def test_the_ring_follows_a_ramp_monotonically_round_the_circle() -> None:
    """Not just "one bump moved it" -- a known gradient must come out as a
    gradient, which a single-bucket implementation would fail."""
    levels = tuple(index / (LEVEL_BUCKETS - 1) for index in range(LEVEL_BUCKETS))
    alpha = alpha_of(orb_image("recording", 0.0, 0.0, levels=levels))

    radii = [
        ring_radius_at(alpha, index / LEVEL_BUCKETS)
        for index in range(2, LEVEL_BUCKETS - 2, 4)
    ]
    rising = sum(
        1 for before, after in zip(radii, radii[1:]) if after >= before - 0.004
    )

    assert rising == len(radii) - 1, f"the ramp did not read as a ramp: {radii}"
    assert radii[-1] > radii[0] + 0.015


def test_two_loud_samples_make_two_bumps() -> None:
    levels = [0.0] * LEVEL_BUCKETS
    levels[4] = 1.0
    levels[20] = 1.0
    alpha = alpha_of(orb_image("recording", 0.0, 0.0, levels=tuple(levels)))

    loud_one = ring_radius_at(alpha, 4 / LEVEL_BUCKETS)
    loud_two = ring_radius_at(alpha, 20 / LEVEL_BUCKETS)
    between = ring_radius_at(alpha, 12 / LEVEL_BUCKETS)

    assert loud_one > between + 0.015
    assert loud_two > between + 0.015


def test_silence_leaves_a_plain_circle() -> None:
    """A waveform of nothing is a ring, not a wobble."""
    alpha = alpha_of(
        orb_image("recording", 0.0, 0.0, levels=(0.0,) * LEVEL_BUCKETS)
    )
    radii = [ring_radius_at(alpha, index / 16.0) for index in range(16)]

    assert max(radii) - min(radii) < 0.01, f"silence is not round: {radii}"


def test_the_history_is_interpolated_rather_than_stepped() -> None:
    """32 facets would read as a cog. Checked on the sampler itself, which is
    where the interpolation lives."""
    levels = np.array([0.0, 1.0] + [0.0] * (LEVEL_BUCKETS - 2), dtype=np.float32)
    between = float(level_at_angle(levels, np.array([0.5 / LEVEL_BUCKETS]))[0])

    assert 0.2 < between < 0.8, f"midway between samples read {between}"


def test_the_waveform_is_the_only_live_state() -> None:
    """Everything else has a cycle that can be pre-generated and blitted. The
    waveform does not, which is why it is drawn per frame and why it runs at
    the rate its data arrives."""
    live = [state for state in ORB_STYLES if is_live(state)]

    assert live == ["recording"]


# --- 3. each of the others does its own thing --------------------------------


def test_the_speaking_waves_travel_outward() -> None:
    """Grandpa's own output, leaving the ring. Measured within one wave's
    lifetime: across the whole cycle the rings are evenly spaced, so anything
    averaged over it is constant by construction."""
    radii = [
        lead_wave_radius(alpha_of(orb_image("speaking", phase, 0.0)))
        for phase in (0.04, 0.12, 0.20)
    ]

    assert radii == sorted(radii), f"the waves did not travel outward: {radii}"
    assert radii[-1] > radii[0] + 0.002
    # At the first sample the lead wave has not yet reached the band's
    # inner edge, so the claim is that a wave gets outside the ring --
    # not that one is already there when the cycle starts.
    assert max(radii) > no_wave_floor(), "no wave ever leaves the ring"


def test_the_waves_repeat_once_per_ring_in_flight() -> None:
    """Exactly, not approximately: with two rings evenly spaced the picture at
    phase 0 and at phase 1/2 is the same set of radii. A ring that merely
    pulsed in place could not satisfy this."""
    from grandpa.ui.orb_image import WAVE_COUNT

    first = np.asarray(orb_image("speaking", 0.0, 0.0))
    period = np.asarray(orb_image("speaking", 1.0 / WAVE_COUNT, 0.0))
    quarter = np.asarray(orb_image("speaking", 0.5 / WAVE_COUNT, 0.0))

    assert np.array_equal(first, period)
    assert not np.array_equal(first, quarter)


@pytest.mark.parametrize("state", ["idle", "error", "executing"])
def test_a_state_with_no_waves_reads_the_floor(state: str) -> None:
    """The control. Without it, "the waves travel" could be measuring noise."""
    radius = lead_wave_radius(alpha_of(orb_image(state, 0.9, 0.0)))

    assert radius == pytest.approx(no_wave_floor(), abs=0.002), (
        f"{state} has something travelling outside its ring"
    )


def test_the_success_ripple_travels_outward_then_leaves_a_steady_ring() -> None:
    """One ripple, then steady -- which is the shape of the whole state: it
    plays once and the final frame is where the orb rests."""
    early = lead_wave_radius(alpha_of(orb_image("success", 0.10, 0.0)))
    middle = lead_wave_radius(alpha_of(orb_image("success", 0.50, 0.0)))
    late = lead_wave_radius(alpha_of(orb_image("success", 0.95, 0.0)))

    assert middle > early, f"the ripple did not expand: {early} -> {middle}"
    assert late == pytest.approx(no_wave_floor(), abs=0.002), (
        "the ripple is still going at the end of its one and only cycle"
    )


def test_the_counter_arcs_travel_in_opposite_directions() -> None:
    """Two arcs, not one arc twice. Tracked as the two brightest wedges moving
    the opposite way round."""
    def peaks(phase: float) -> tuple[int, int]:
        profile = angular_profile(alpha_of(orb_image("thinking", phase, 0.0)))
        order = np.argsort(profile)[::-1]
        return int(order[0]), int(profile.size)

    first, bins = peaks(0.0)
    later, _ = peaks(0.25)
    # One arc is at phase and the other at 0.5 - phase, so the gap between them
    # changes with phase -- which a single rotating arc could not do.
    gap_at_zero = angular_profile(alpha_of(orb_image("thinking", 0.0, 0.0)))
    gap_at_quarter = angular_profile(alpha_of(orb_image("thinking", 0.25, 0.0)))

    assert first != later, "nothing moved"
    assert not np.allclose(gap_at_zero, gap_at_quarter)
    # Two distinct lit regions at a phase where they are apart.
    profile = angular_profile(alpha_of(orb_image("thinking", 0.125, 0.0)))
    bright = profile > 0.75 * profile.max()
    runs = int(np.sum(np.diff(bright.astype(int)) == 1)) + int(bright[0])

    assert runs >= 2, f"only {runs} lit arc(s) at a phase where there should be two"


def test_the_executing_chase_never_grows_into_a_fraction() -> None:
    """**Indeterminate on purpose.** The signal from the action layer is
    "running" and "finished" -- there is no progress fraction in it, so a ring
    that filled from empty to full would be inventing one. The lit arc travels
    and its width never changes."""
    widths = []
    for index in range(CHASE_SEGMENTS):
        profile = angular_profile(
            alpha_of(orb_image("executing", index / CHASE_SEGMENTS, 0.0)), bins=96
        )
        widths.append(int((profile > 0.7 * profile.max()).sum()))

    assert max(widths) - min(widths) <= 4, f"the lit arc changes width: {widths}"
    expected = 96 * CHASE_LIT / CHASE_SEGMENTS

    assert abs(float(np.mean(widths)) - expected) < expected * 0.6


def test_the_executing_chase_actually_travels() -> None:
    first = angular_profile(alpha_of(orb_image("executing", 0.0, 0.0)), bins=96)
    later = angular_profile(alpha_of(orb_image("executing", 0.5, 0.0)), bins=96)

    assert int(np.argmax(first)) != int(np.argmax(later))


def test_the_error_flashes_twice_and_then_holds() -> None:
    """Two flashes, then solid -- and because it is one-shot, "solid" is where
    it stays rather than the start of a third flash."""
    brightness = [
        float(alpha_of(orb_image("error", index / 40.0, 0.0)).sum())
        for index in range(40)
    ]
    settled = brightness[len(brightness) // 2:]
    baseline = float(np.median(settled))
    peaks = [
        index
        for index in range(1, len(brightness) - 1)
        if brightness[index] > baseline * 1.25
        and brightness[index] >= brightness[index - 1]
        and brightness[index] >= brightness[index + 1]
    ]

    assert len(peaks) == 2, f"found {len(peaks)} flashes at {peaks}"
    assert max(settled) - min(settled) < baseline * 0.05, "it is still moving"


def test_the_idle_breathe_grows_and_settles() -> None:
    """One swell per cycle, not a throb: the brightness rises to a single peak
    and comes back, and the cycle closes."""
    brightness = [
        float(alpha_of(orb_image("idle", index / 20.0, 0.0)).sum())
        for index in range(20)
    ]
    peak = int(np.argmax(brightness))

    assert 6 <= peak <= 14, f"the swell peaks at frame {peak} of 20"
    assert brightness[0] == pytest.approx(brightness[-1], rel=0.05)


def test_the_loading_arc_still_travels() -> None:
    first = angular_profile(alpha_of(orb_image("loading", 0.0, 0.0)))
    later = angular_profile(alpha_of(orb_image("loading", 0.5, 0.0)))

    assert int(np.argmax(first)) != int(np.argmax(later))


# --- 4. telling them apart at a glance ---------------------------------------


GLANCE_STATES = (
    "idle", "recording", "transcribing", "speaking", "executing", "success", "error",
)


@pytest.mark.parametrize("state", GLANCE_STATES)
def test_each_state_is_a_different_colour_or_a_different_shape(state: str) -> None:
    """Colour does most of the work; this asserts the pixels back it up."""
    from grandpa.ui.palette import ring_rgb

    image = orb_image(state, 0.25, 0.6, levels=_ramp(0)).convert("RGBA")
    pixels = np.asarray(image)
    alpha = pixels[:, :, 3]
    lit = alpha >= 0.9 * alpha.max()
    drawn = tuple(int(round(pixels[:, :, channel][lit].mean())) for channel in range(3))

    assert drawn == ring_rgb(state), state


def test_the_closest_pair_is_still_separable() -> None:
    """Success and speaking are the closest: both send a ring outward, and they
    occur next to each other in time. They are separable on two counts -- the
    hue gap, and that one loops while the other plays once."""
    from grandpa.ui.palette import ring_rgb

    assert ring_rgb("success") != ring_rgb("speaking")
    assert is_oneshot("success")
    assert not is_oneshot("speaking")

    difference = max(
        abs(a - b) for a, b in zip(ring_rgb("success"), ring_rgb("speaking"))
    )

    assert difference > 60, f"the hues are only {difference} apart"


# --- 5. the rates, which are the budget --------------------------------------


def test_each_state_runs_at_the_rate_it_was_measured_at() -> None:
    """Not one rate for everything. Idle runs slowly because it runs forever,
    and the waveform runs at the rate its data arrives."""
    assert fps_for("idle") == 5.0
    assert fps_for("recording") == 10.0
    for state in ("loading", "transcribing", "thinking", "speaking", "executing",
                  "success", "error"):
        assert fps_for(state) == 20.0, state


def test_the_breathe_cycle_is_several_seconds_long() -> None:
    seconds = frames_for("idle") / fps_for("idle")

    assert 4.0 <= seconds <= 10.0, f"the breathe takes {seconds:.1f}s"


def test_only_the_two_resting_states_end_up_still() -> None:
    """The property that was pinned when idle started breathing: a state which
    holds still cancels its tick, and success and error keep it exercised."""
    assert STILL_STATES == frozenset({"success", "error"})
    for state in STILL_STATES:
        assert is_animated(state), f"{state} must play once before it rests"
        assert is_oneshot(state)


# --- 6. the disc fallback, which cannot show a waveform ----------------------


@pytest.mark.parametrize("state", sorted(ORB_STYLES))
def test_the_fallback_renders_every_state_as_an_opaque_disc(state: str) -> None:
    """It cannot composite per-pixel alpha, so the ring sits on a dark disc.
    The motion survives -- the same code draws both -- but the glow falls off
    into the disc's colour and stops at a visible edge."""
    disc = orb_on_disc(state, 0.25, 0.6, levels=_ramp(0))
    pixels = np.asarray(disc.convert("RGBA"))

    assert disc.size == (ORB_SIZE, ORB_SIZE)
    assert pixels[ORB_SIZE // 2, ORB_SIZE // 2, 3] == 255, "not opaque"
    assert pixels[0, 0, 3] == 0, "the disc filled the corners"


def test_the_fallback_keeps_the_waveform_rather_than_flattening_it() -> None:
    """Worth checking: the fallback is the same renderer composited onto a
    disc, so the one animation that needs live data still gets it."""
    quiet = np.asarray(orb_on_disc("recording", 0.0, 0.0, levels=(0.0,) * LEVEL_BUCKETS))
    loud = np.asarray(orb_on_disc("recording", 0.0, 0.0, levels=_ramp(0)))

    assert not np.array_equal(quiet, loud)
