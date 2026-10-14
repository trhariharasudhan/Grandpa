"""The orb, as a pure function of its state, its phase and the live levels.

``orb_image(state, phase, level, levels=...)`` returns an RGBA image and touches
nothing else -- no window, no toolkit, no device. That is deliberate and it is
the whole testing story: the pixels are produced here and blitted by Win32, so
they can be asserted *as pixels* -- the ring is at this radius, the corners are
transparent, the waveform follows this level history -- rather than as a record
that a draw call happened.

**The ring is drawn analytically, in numpy, rather than with PIL.** It used to
be a supersampled PIL ellipse downscaled with LANCZOS under a stack of four
Gaussian blurs. That cannot draw a waveform at all: ``ImageDraw.ellipse`` draws
a circle, and a radius-modulated curve would need a ~360-point polygon at 4x
supersample plus the blurs. So the ring is now a Gaussian of each pixel's
distance from a per-angle target radius, which gives the anti-aliasing and the
glow for free and makes the waveform the same arithmetic as everything else.

Measured, with changing input every frame, at the 72px window:

    generate   0.367 ms      premultiply   0.099 ms      total   0.466 ms

At the capture rate of 10 frames a second that is 0.47% of one core, inside the
0.6% budget. At 20fps it would be 0.93% and over it, which is why the waveform
runs at the rate its data arrives and no faster -- 20fps would draw the same
level history twice.

Two consequences of the rewrite worth stating:

* the halo scales with the orb, because it is a multiple of the stroke and the
  stroke is a fraction of the size. The old blur radii were absolute pixels, so
  the orb was not actually resolution-independent; shrinking the window to 72
  was what exposed it.
* **the waveform is a pure function of the levels, not of the phase.** Its
  motion comes entirely from new samples arriving and old ones falling off the
  end of the history. A ring that rotated with phase would animate whether or
  not anyone was speaking, which is the one thing a voice waveform must not do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from grandpa.ui.palette import ring_rgb

#: Default orb size in logical pixels. 96 before; measured at 72 the ring reads
#: a third thicker relative to its own circle, the lit band is *wider* on screen
#: (4 physical pixels against 3) at equal brightness, and the share of the
#: window that looks like desktop while still taking a click falls from 76.7% to
#: 73.1%. See docs/development/orb-survey.md and the ring-size tests.
ORB_SIZE = 72

#: The reduction applied to the ring's radius in the round before this one.
RING_SCALE = 13 / 15

#: How far out the ring sits, as a fraction of the size.
RING_RADIUS = 0.30 * RING_SCALE

#: The stroke, held at an absolute 2.5 logical pixels of the 72px window rather
#: than at a ratio of it. That is what keeps the band as bright as it was in the
#: larger window: the measured floor is two final pixels, below which the band
#: dims rather than thins.
STROKE_PX = 2.5
RING_WIDTH = STROKE_PX / ORB_SIZE

#: The halo, as three Gaussians of the radial offset: each entry is
#: ``(sigma as a multiple of the stroke, weight)``.
#:
#: A stack rather than one Gaussian, and weighted steeply, for a reason worth
#: recording. A single peak-1 Gaussian wide enough to look like a glow is not
#: normalised the way a blur is: it carries far more energy than a blurred ring
#: does and it *fills the middle*. Measured during the rewrite -- one Gaussian
#: at 5.5x the stroke put alpha 30 of 255 in the centre of idle, against 3 for
#: the blur stack it replaced, and the orb stopped reading as a ring. The
#: widest term here is weighted low enough that the centre stays dark while the
#: narrow terms still carry a visible falloff.
#:
#: Multiples of the stroke rather than absolute radii, so the whole picture
#: scales with the orb. The blur radii this replaced were absolute pixels,
#: which is why the orb was not actually resolution-independent.
HALO_STACK: tuple[tuple[float, float], ...] = ((2.2, 0.30), (4.5, 0.13), (9.0, 0.05))

#: The bright core's sigma, as a multiple of the stroke. exp(-(x/s)^2) is at
#: half its peak where |x| = s * sqrt(ln 2), so its full width at half maximum
#: is 1.665 * s. Dividing by that makes the FWHM equal the nominal stroke --
#: without it a "2.5 pixel" stroke measured 4.2 pixels across and the ring read
#: as a fat band rather than a line.
CORE_SIGMA = 1.0 / 1.665

#: Where the glow is faded to nothing, as fractions of the size. A layered
#: window is composited from exactly these bytes, so "the corners are
#: transparent" is either true in the pixels or it is a hope.
FALLOFF_INNER = 0.42
FALLOFF_OUTER = 0.50

#: How many level samples ride around the circumference, and how far the ring's
#: edge is displaced at full volume. 32 is what the controller's meter deque
#: already holds -- about 3.2 seconds at the capture rate -- so the waveform
#: needs no new storage.
LEVEL_BUCKETS = 32
WAVEFORM_AMPLITUDE = 0.040

#: How far the outward-travelling rings get before they fade out, as a fraction
#: of the size. 0.16 of 72 logical pixels is about 11, which is what gives two
#: rings room to be seen as two.
WAVE_SPAN = 0.16

#: Rings in flight at once for the speaking animation. Three fitted inside the
#: span at the old 96px window; at 72 they overlapped into one soft band and
#: the measured radius of the travelling edge stopped moving at all. Two read
#: as waves.
WAVE_COUNT = 2

#: Segments in the executing chase, and how many of them are lit at a time.
CHASE_SEGMENTS = 12
CHASE_LIT = 4

#: What the fallback disc is filled with when there is no per-pixel alpha.
DISC_BACKGROUND = (23, 24, 27)


def scaled_width(pre_reduction: float) -> float:
    """A pre-reduction stroke width, re-based on the absolute stroke.

    Every width goes through this rather than being written out already
    converted, so the ratios between the states are visible in the source and a
    test can assert that no stroke was left behind at an old value.
    """
    return RING_WIDTH * (pre_reduction / 0.030)


@dataclass(frozen=True)
class OrbStyle:
    """How one state looks and moves.

    Colour comes from the palette; everything here is geometry and motion. That
    split is what lets two states share a hue and still be a glance apart.
    """

    colour: tuple[int, int, int]
    glow: float
    width: float = RING_WIDTH
    #: Which of the seven animations, or None for a still ring.
    animation: str | None = None
    #: How often the phase advances. Not one rate for everything: the waveform
    #: runs at the rate its data arrives, and a breathe that nobody is waiting
    #: on runs slowly because it runs forever.
    fps: float = 20.0
    #: Frames in one cycle. Pre-generated once per state and blitted, except
    #: for the waveform, which has no cycle to pre-build.
    frames: int = 24
    #: True for an animation that plays once and then holds its final look.
    oneshot: bool = False
    #: ``(start, extent)`` in degrees for a travelling arc.
    arc: tuple[float, float] | None = None
    #: How much the ring breathes, 0 for none.
    pulse: float = 0.0


#: One style per controller state, plus ``unread`` which is an orb-level flag.
#:
#: The seven animations, and what each is saying:
#:
#:   idle         a slow breathe. Nothing is happening and nothing is wrong.
#:   recording    the ring's edge displaced by your own voice.
#:   transcribing two arcs travelling in opposite directions: work with no
#:   thinking     knowable end. Both states share the look deliberately.
#:   speaking     waves radiating outward -- Grandpa's output, not yours.
#:   executing    segments chasing round. Indeterminate on purpose: the signal
#:                is "running" and "finished", never a fraction.
#:   success      one ripple expanding, then steady. Plays once.
#:   error        two flashes, then holds solid. Plays once.
#:   loading      the travelling arc it has always had.
ORB_STYLES: dict[str, OrbStyle] = {
    # Loading shares idle's neutral hue and is told apart by geometry: a
    # travelling arc at roughly half idle's glow. During loading there is no
    # request yet, so there is nothing for a colour to be about.
    "loading": OrbStyle(
        ring_rgb("loading"), 0.30, scaled_width(0.028),
        animation="arc", arc=(0.0, 90.0), fps=20.0, frames=32,
    ),
    # 6 seconds at 5 frames a second. Slow because it runs forever: measured at
    # 0.14% of one core, against 0.56% at 20fps.
    "idle": OrbStyle(
        ring_rgb("idle"), 0.55, scaled_width(0.030),
        animation="breathe", fps=5.0, frames=30, pulse=0.16,
    ),
    # 10fps is the capture chunk rate. Faster would redraw the same history.
    "recording": OrbStyle(
        ring_rgb("recording"), 1.05, scaled_width(0.046),
        animation="waveform", fps=10.0, frames=1,
    ),
    "transcribing": OrbStyle(
        ring_rgb("transcribing"), 0.75, scaled_width(0.034),
        animation="counter_arcs", arc=(0.0, 110.0), fps=20.0, frames=40,
    ),
    "thinking": OrbStyle(
        ring_rgb("thinking"), 0.75, scaled_width(0.034),
        animation="counter_arcs", arc=(0.0, 110.0), fps=20.0, frames=40,
    ),
    "speaking": OrbStyle(
        ring_rgb("speaking"), 0.95, scaled_width(0.040),
        animation="waves", fps=20.0, frames=28,
    ),
    "executing": OrbStyle(
        ring_rgb("executing"), 0.85, scaled_width(0.038),
        animation="chase", fps=20.0, frames=CHASE_SEGMENTS * 2,
    ),
    # One ripple, then steady. Success is somewhere the orb rests, so once the
    # ripple has played it costs nothing to sit in.
    "success": OrbStyle(
        ring_rgb("success"), 0.70, scaled_width(0.034),
        animation="ripple", fps=20.0, frames=20, oneshot=True,
    ),
    # Two flashes, then solid. Also a resting state afterwards.
    "error": OrbStyle(
        ring_rgb("error"), 0.85, scaled_width(0.034),
        animation="flash", fps=20.0, frames=20, oneshot=True,
    ),
    "unread": OrbStyle(
        ring_rgb("unread"), 0.95, scaled_width(0.038),
        animation="breathe", fps=10.0, frames=24, pulse=0.30,
    ),
}

#: States whose look changes over time, so the caller knows when a tick is
#: worth scheduling. Everything else is drawn once and left alone.
ANIMATED_STATES = frozenset(
    name for name, style in ORB_STYLES.items() if style.animation is not None
)

#: States that hold still once they have arrived. The tick must *cancel* for
#: these rather than re-arm -- that is the property which keeps an animation
#: from running forever for a thing nobody is looking at, and it survives idle
#: having a breathe because these two do not.
STILL_STATES = frozenset(
    name
    for name, style in ORB_STYLES.items()
    if style.animation is None or style.oneshot
)


def style_for(state: str, *, unread: bool = False) -> OrbStyle:
    """The style to draw. ``unread`` wins, because it is the thing unseen."""
    if unread:
        return ORB_STYLES["unread"]
    return ORB_STYLES.get(str(state), ORB_STYLES["idle"])


def is_animated(state: str, *, unread: bool = False) -> bool:
    """Whether this state needs a tick at all."""
    return style_for(state, unread=unread).animation is not None


def is_oneshot(state: str, *, unread: bool = False) -> bool:
    """Whether the animation plays once and then holds."""
    return bool(style_for(state, unread=unread).oneshot)


def fps_for(state: str, *, unread: bool = False) -> float:
    return float(style_for(state, unread=unread).fps)


def frames_for(state: str, *, unread: bool = False) -> int:
    return max(1, int(style_for(state, unread=unread).frames))


def is_live(state: str, *, unread: bool = False) -> bool:
    """Whether frames depend on live data and so cannot be pre-generated."""
    return style_for(state, unread=unread).animation == "waveform"


# --- the fields every animation is built from --------------------------------


@lru_cache(maxsize=8)
def _fields(size: int) -> tuple[Any, Any]:
    """Each pixel's distance from the centre and its angle, both cached.

    Distance as a fraction of the size, so every constant in this module is
    resolution-independent. Angle in turns (0..1) rather than radians, because
    every use of it here is a fraction of the way round.
    """
    import numpy as np

    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    dx = (xs - centre).astype(np.float32)
    dy = (ys - centre).astype(np.float32)
    radius = (np.hypot(dx, dy) / size).astype(np.float32)
    turns = ((np.arctan2(dy, dx) + math.pi) / (2.0 * math.pi)).astype(np.float32)
    return radius, turns


@lru_cache(maxsize=8)
def _taper(size: int) -> Any:
    """A radial fade to exactly zero, so the rectangle has no edge at all.

    Without it the widest part of the halo leaves alpha 3 of 255 in the corners
    -- invisible, and not transparent, and a layered window composites exactly
    those bytes.
    """
    import numpy as np

    radius, _turns = _fields(size)
    span = max(1e-6, FALLOFF_OUTER - FALLOFF_INNER)
    ramp = np.clip((FALLOFF_OUTER - radius) / span, 0.0, 1.0)
    # Smoothstep rather than linear: a straight ramp leaves a faint ring where
    # its slope changes, visible against a dark desktop.
    return (ramp * ramp * (3.0 - 2.0 * ramp)).astype(np.float32)


def _ring(radius: Any, target: Any, width: float, glow: float) -> Any:
    """One ring: a bright core and a soft halo, as Gaussians of the offset.

    *target* may be a scalar radius or a per-pixel array, which is the whole
    trick -- a waveform is this same expression with a target that varies by
    angle.
    """
    import numpy as np

    offset = radius - target
    weight = np.exp(-((offset / max(width * CORE_SIGMA, 1e-5)) ** 2))
    for multiple, share in HALO_STACK:
        sigma = max(width * multiple, 1e-5)
        weight = weight + np.exp(-((offset / sigma) ** 2)) * (share * glow)
    return weight


def _arc_weight(turns: Any, centre: float, extent: float, soft: float = 0.045) -> Any:
    """How lit each pixel is for an arc centred at *centre* turns."""
    import numpy as np

    distance = np.abs(((turns - centre) + 0.5) % 1.0 - 0.5)
    ramp = np.clip((extent / 2.0 - distance) / max(soft, 1e-5) + 1.0, 0.0, 1.0)
    return (ramp * ramp * (3.0 - 2.0 * ramp)).astype(np.float32)


def level_at_angle(levels: Any, turns: Any) -> Any:
    """The level history mapped around the circumference, interpolated.

    Linear between neighbouring samples so the ring is a curve rather than 32
    facets. Index 0 sits at the left of the circle and runs clockwise; which end
    is newest is the caller's business, and the controller passes oldest first
    so the newest sample is always in the same place.
    """
    import numpy as np

    samples = np.asarray(levels, dtype=np.float32)
    if samples.size == 0:
        return np.zeros_like(turns)
    position = (np.asarray(turns, dtype=np.float32) % 1.0) * samples.size
    low = np.floor(position).astype(np.int32) % samples.size
    high = (low + 1) % samples.size
    blend = (position - np.floor(position)).astype(np.float32)
    return samples[low] * (1.0 - blend) + samples[high] * blend


# --- the seven animations ----------------------------------------------------


def _alpha_for(
    state: str, phase: float, level: float, levels: Any, size: int, unread: bool
) -> Any:
    """The alpha channel for one frame. Everything else is colour and wrapping."""
    import numpy as np

    style = style_for(state, unread=unread)
    radius, turns = _fields(size)
    phase = float(phase) % 1.0
    level = min(1.0, max(0.0, float(level)))
    base = RING_RADIUS
    width = style.width
    glow = style.glow
    animation = style.animation

    if animation == "waveform":
        # Deliberately independent of phase: the motion is the data changing.
        if levels is None:
            levels = (level,) * LEVEL_BUCKETS
        displaced = base + WAVEFORM_AMPLITUDE * level_at_angle(levels, turns)
        loudest = float(np.asarray(levels, dtype=np.float32).max(initial=0.0))
        # Loudness brightens the ring but does NOT thicken it. Thickening it
        # moved the measured radius outward at every angle, including the
        # silent ones, which blurred the one claim this state has to make:
        # that the edge is where the history says, angle by angle.
        weight = _ring(radius, displaced, width, glow * (1.0 + 0.8 * loudest))

    elif animation == "breathe":
        # A cosine so the loop has no seam. Very subtle on purpose.
        breath = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
        weight = _ring(radius, base, width * (1.0 + 0.10 * style.pulse * breath),
                       glow * (1.0 + style.pulse * (breath - 0.5) * 2.0))

    elif animation == "arc":
        start, extent = style.arc or (0.0, 90.0)
        ring = _ring(radius, base, width, glow)
        lit = _arc_weight(turns, (start / 360.0 + phase) % 1.0, extent / 360.0)
        weight = ring * (0.28 + 0.72 * lit)

    elif animation == "counter_arcs":
        _start, extent = style.arc or (0.0, 110.0)
        ring = _ring(radius, base, width, glow)
        one = _arc_weight(turns, phase % 1.0, extent / 360.0)
        other = _arc_weight(turns, (0.5 - phase) % 1.0, extent / 360.0)
        weight = ring * (0.24 + 0.76 * np.maximum(one, other))

    elif animation == "waves":
        # Rings leaving the ring and fading as they go. Grandpa's own output.
        weight = _ring(radius, base, width, glow * 0.8)
        for index in range(WAVE_COUNT):
            progress = (phase + index / WAVE_COUNT) % 1.0
            fading = (1.0 - progress) ** 2
            weight = weight + _ring(
                radius, base + progress * WAVE_SPAN, width, glow
            ) * 0.75 * fading

    elif animation == "ripple":
        # One ring leaving, then nothing but the steady ring. Plays once.
        weight = _ring(radius, base, width, glow)
        fading = (1.0 - phase) ** 2
        weight = weight + _ring(
            radius, base + phase * WAVE_SPAN * 1.4, width, glow
        ) * 0.9 * fading

    elif animation == "flash":
        # Two flashes, then solid for the rest of the cycle -- and the cycle
        # does not repeat, so "solid" is where it stays.
        envelope = 1.0
        for centre in (0.08, 0.30):
            distance = abs(phase - centre)
            if distance < 0.08:
                envelope += 1.15 * (0.5 + 0.5 * math.cos(math.pi * distance / 0.08))
        weight = _ring(radius, base, width * envelope ** 0.35, glow * envelope)

    elif animation == "chase":
        # Segments travelling round. Indeterminate on purpose: the signal is
        # "an automation is running", never how far through it is.
        ring = _ring(radius, base, width, glow)
        step = math.floor(phase * CHASE_SEGMENTS) / CHASE_SEGMENTS
        extent = CHASE_LIT / CHASE_SEGMENTS
        lit = _arc_weight(turns, (step + extent / 2.0) % 1.0, extent, soft=0.012)
        # 0.42 rather than 0.22 for the unlit segments. Measured on screen at
        # 125%: at 0.22 the rest of the ring fell below what reads as lit, so
        # the orb showed a travelling blob instead of segments going round a
        # circle -- and you cannot see segments filling if you cannot see the
        # circle they are filling.
        weight = ring * (0.42 + 0.58 * lit)

    else:
        weight = _ring(radius, base, width, glow)

    return np.clip(weight * _taper(size) * 255.0, 0, 255).astype(np.uint8)


def orb_image(
    state: str = "idle",
    phase: float = 0.0,
    level: float = 0.0,
    *,
    size: int = ORB_SIZE,
    unread: bool = False,
    levels: Any = None,
) -> Any:
    """An RGBA orb for *state*.

    *phase* runs 0..1 over one animation cycle. *level* is the live microphone
    level, 0..1. *levels* is the level *history*, oldest first, which is what
    the waveform needs -- one number cannot describe a shape around a circle.

    The alpha falls to zero before the edge, so the corners are fully
    transparent and the glow has no boundary.
    """
    from PIL import Image

    alpha = _alpha_for(state, phase, level, levels, size, unread)
    out = Image.new("RGBA", (size, size), (*style_for(state, unread=unread).colour, 0))
    out.putalpha(Image.fromarray(alpha))
    return out


def orb_on_disc(
    state: str = "idle",
    phase: float = 0.0,
    level: float = 0.0,
    *,
    size: int = ORB_SIZE,
    unread: bool = False,
    levels: Any = None,
    background: tuple[int, int, int] = DISC_BACKGROUND,
) -> Any:
    """The fallback: the same orb flattened onto an opaque dark disc.

    For when per-pixel alpha is refused -- a remote desktop session, a software
    renderer, a driver that declines layered windows. The glow then falls off
    into the disc's own colour and stops at a visible circular edge, which is
    worse-looking and always works. Built here beside the real one, by the same
    code, so a change to one cannot silently skip the other.
    """
    import numpy as np
    from PIL import Image

    glow = orb_image(state, phase, level, size=size, unread=unread, levels=levels)
    radius, _turns = _fields(size)
    edge = np.clip((0.47 - radius) / 0.02, 0.0, 1.0)
    circle = (edge * edge * (3.0 - 2.0 * edge) * 255.0).astype(np.uint8)
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    disc.paste(
        Image.new("RGBA", (size, size), (*background, 255)),
        (0, 0),
        Image.fromarray(circle),
    )
    disc.alpha_composite(glow)
    return disc


def flatten_onto(image: Any, background: tuple[int, int, int]) -> Any:
    """Composite an RGBA orb onto an opaque colour."""
    from PIL import Image

    base = Image.new("RGB", image.size, background)
    base.paste(image, (0, 0), image)
    return base


def transparent_fraction(image: Any) -> float:
    """How much of the orb's rectangle is fully transparent.

    Recorded because a layered window takes clicks on its whole rectangle: this
    is the share of the orb's area that looks like desktop and does not behave
    like it. Click-through is deliberately not built, so the size of the
    problem is measured rather than guessed.
    """
    import numpy as np

    alpha = np.asarray(image.convert("RGBA"))[:, :, 3]
    return float((alpha == 0).sum()) / float(alpha.size)


__all__ = [
    "ANIMATED_STATES",
    "CHASE_LIT",
    "CHASE_SEGMENTS",
    "DISC_BACKGROUND",
    "FALLOFF_INNER",
    "FALLOFF_OUTER",
    "CORE_SIGMA",
    "HALO_STACK",
    "LEVEL_BUCKETS",
    "ORB_SIZE",
    "ORB_STYLES",
    "RING_RADIUS",
    "RING_SCALE",
    "RING_WIDTH",
    "STILL_STATES",
    "STROKE_PX",
    "WAVEFORM_AMPLITUDE",
    "WAVE_COUNT",
    "WAVE_SPAN",
    "OrbStyle",
    "flatten_onto",
    "fps_for",
    "frames_for",
    "is_animated",
    "is_live",
    "is_oneshot",
    "level_at_angle",
    "orb_image",
    "orb_on_disc",
    "scaled_width",
    "style_for",
    "transparent_fraction",
]
