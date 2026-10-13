"""The orb, as a pure function of its state.

``orb_image(state, phase, level)`` returns an RGBA image and touches nothing
else -- no window, no toolkit, no device. That is deliberate and it is the whole
testing story for the orb: the survey measured that tkinter cannot paint a glow
(``-transparentcolor`` left 62% of the window magenta), so the pixels are
produced here and blitted by Win32. Which means they can be asserted *as
pixels* -- the ring is at this radius, the corners are transparent, listening is
thicker than idle -- rather than as a record that a draw call happened.

PIL does the drawing because tk's Canvas has neither a blur nor an
anti-aliased stroke, and a glow is a gradient by definition. ``pillow`` and
``numpy`` are already declared dependencies, so this costs nothing new.

The glow is built by supersampling a ring, downscaling it with LANCZOS to get a
smooth edge, then stacking four Gaussian blurs at increasing radii. The stack is
what makes the falloff look like light rather than a single soft edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from grandpa.ui.palette import ring_rgb

#: Default orb size in pixels. Small enough to sit on a desktop unremarked,
#: large enough that the glow has room to fall off inside its own rectangle.
ORB_SIZE = 96

#: How far out the ring sits, and how thick it is, as fractions of the size.
#: The ring is well inside its rectangle because the glow needs somewhere to go:
#: a ring at the edge would have its falloff clipped flat.
RING_RADIUS = 0.30
RING_WIDTH = 0.030

#: Supersample factor before downscaling. The survey measured x4 at 5.9ms and
#: x1 at 3.6ms per frame; the cost is paid once per frame of a pre-rendered
#: cycle, so the smoother one is affordable.
SUPERSAMPLE = 4

#: The blur stack: (radius in final pixels, weight).
GLOW_STACK: tuple[tuple[int, float], ...] = ((3, 0.55), (7, 0.35), (14, 0.22), (26, 0.14))

#: Where the glow is faded to nothing, as fractions of the size. The widest
#: blur in the stack reaches every pixel of the rectangle, which left alpha 3 of
#: 255 in the corners -- invisible, and still not transparent. A layered window
#: is composited from exactly these bytes, so "the corners are transparent" is
#: either true in the pixels or it is a hope. The taper starts well outside the
#: ring and its own glow, so nothing visible is clipped to buy it.
FALLOFF_INNER = 0.42
FALLOFF_OUTER = 0.50

#: What the fallback disc is filled with when there is no per-pixel alpha.
#: Matches the panel's background so the two read as one object.
DISC_BACKGROUND = (23, 24, 27)


@dataclass(frozen=True)
class OrbStyle:
    """How one state looks. Colour, glow strength, ring thickness, arc."""

    colour: tuple[int, int, int]
    glow: float
    width: float = RING_WIDTH
    #: ``(start, extent)`` in degrees for a travelling arc, or None for a full
    #: ring. An arc is drawn over a dimmed full ring so it reads as moving along
    #: something rather than floating.
    arc: tuple[float, float] | None = None
    #: How much the ring breathes, 0 for none. Idle is still by default: the
    #: survey measured an always-on animation at 0.6% of a core forever.
    pulse: float = 0.0


#: One style per controller state, plus ``unread`` which is an orb-level flag
#: rather than a controller state.
#:
#: **The colours are not here.** They come from :mod:`grandpa.ui.palette`, which
#: the panel reads too -- the orb and the panel's dot used to disagree about
#: every state, which is how a colour stops meaning anything. What *is* here is
#: the geometry: glow, ring width, arc and pulse. That split is what lets two
#: states share a hue and still be told apart, as transcribing and thinking do.
ORB_STYLES: dict[str, OrbStyle] = {
    "loading": OrbStyle(ring_rgb("loading"), 0.30, 0.028, arc=(0.0, 90.0)),
    "idle": OrbStyle(ring_rgb("idle"), 0.55, 0.030, pulse=0.0),
    "recording": OrbStyle(ring_rgb("recording"), 1.25, 0.052),
    "transcribing": OrbStyle(ring_rgb("transcribing"), 0.75, 0.034, arc=(0.0, 120.0)),
    "thinking": OrbStyle(ring_rgb("thinking"), 0.75, 0.034, arc=(0.0, 120.0)),
    "speaking": OrbStyle(ring_rgb("speaking"), 1.00, 0.042, pulse=0.35),
    "error": OrbStyle(ring_rgb("error"), 0.85, 0.034),
    "unread": OrbStyle(ring_rgb("unread"), 0.95, 0.038, pulse=0.25),
}

#: States whose look changes over time, so the caller knows when a tick is
#: worth scheduling. Everything else is drawn once and left alone -- the
#: survey's requirement that idle costs nothing.
ANIMATED_STATES = frozenset(
    name for name, style in ORB_STYLES.items() if style.arc or style.pulse
)


def style_for(state: str, *, unread: bool = False) -> OrbStyle:
    """The style to draw. ``unread`` wins, because it is the thing unseen."""
    if unread:
        return ORB_STYLES["unread"]
    return ORB_STYLES.get(str(state), ORB_STYLES["idle"])


def is_animated(state: str, *, unread: bool = False) -> bool:
    """Whether this state needs a tick at all."""
    if unread:
        return bool(ORB_STYLES["unread"].pulse)
    return str(state) in ANIMATED_STATES


def _pil() -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    return Image, ImageDraw, ImageFilter


@lru_cache(maxsize=16)
def _falloff(size: int) -> Any:
    """A radial taper to exactly zero, so the rectangle has no edge at all."""
    import numpy as np

    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    radius = np.hypot(xs - centre, ys - centre) / size
    span = max(1e-6, FALLOFF_OUTER - FALLOFF_INNER)
    ramp = np.clip((FALLOFF_OUTER - radius) / span, 0.0, 1.0)
    # Smoothstep rather than linear: a straight ramp leaves a faint ring where
    # its slope changes, which is visible against a dark desktop.
    return (ramp * ramp * (3.0 - 2.0 * ramp)).astype(np.float32)


@lru_cache(maxsize=256)
def _ring_mask(size: int, width: float, arc: tuple[float, float] | None,
               rotation: float) -> Any:
    """The ring alone, anti-aliased, as an L-mode mask. Cached: a pulse cycle
    reuses the same handful of geometries."""
    Image, ImageDraw, _ = _pil()
    big = size * SUPERSAMPLE
    layer = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(layer)
    centre = big / 2.0
    radius = big * RING_RADIUS
    stroke = max(2, int(big * width))
    box = [centre - radius, centre - radius, centre + radius, centre + radius]
    if arc is None:
        draw.ellipse(box, outline=255, width=stroke)
    else:
        start, extent = arc
        draw.ellipse(box, outline=70, width=stroke)
        draw.arc(box, start + rotation, start + rotation + extent, fill=255,
                 width=stroke)
    return layer.resize((size, size), Image.LANCZOS)


def orb_image(
    state: str = "idle",
    phase: float = 0.0,
    level: float = 0.0,
    *,
    size: int = ORB_SIZE,
    unread: bool = False,
) -> Any:
    """An RGBA orb for *state*.

    *phase* runs 0..1 over one animation cycle: it rotates a travelling arc and
    drives a pulse. *level* runs 0..1 and is the live microphone level, which
    thickens and brightens the ring while recording -- the same number the
    panel's meter consumes, so the orb answers "is it hearing me" while there
    is no panel to look at.

    The alpha channel falls to zero before the edge, so the corners are fully
    transparent and the glow has no boundary.
    """
    Image, _, ImageFilter = _pil()
    import numpy as np

    style = style_for(state, unread=unread)
    phase = float(phase) % 1.0
    level = min(1.0, max(0.0, float(level)))

    # A pulse is a cosine so the loop has no seam; a level adds on top of it.
    breath = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
    glow = style.glow * (1.0 + style.pulse * (breath - 0.5) * 2.0)
    width = style.width
    if state == "recording":
        glow += 1.1 * level
        width += 0.028 * level
    glow = max(0.05, glow)

    rotation = 360.0 * phase if style.arc else 0.0
    mask = _ring_mask(size, round(width, 4), style.arc, round(rotation, 1))

    halo = Image.new("L", (size, size), 0)
    halo_array = np.asarray(halo, dtype=np.float32)
    mask_array = np.asarray(mask, dtype=np.float32)
    for blur, weight in GLOW_STACK:
        hazy = np.asarray(
            mask.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32
        )
        halo_array = halo_array + hazy * weight * glow
    alpha = np.clip(
        (halo_array + mask_array) * _falloff(size), 0, 255
    ).astype(np.uint8)

    out = Image.new("RGBA", (size, size), (*style.colour, 0))
    out.putalpha(Image.fromarray(alpha))
    return out


def orb_on_disc(
    state: str = "idle",
    phase: float = 0.0,
    level: float = 0.0,
    *,
    size: int = ORB_SIZE,
    unread: bool = False,
    background: tuple[int, int, int] = DISC_BACKGROUND,
) -> Any:
    """The fallback: the same orb flattened onto an opaque dark disc.

    For when per-pixel alpha is refused -- a remote desktop session, a software
    renderer, a driver that declines layered windows. The glow then falls off
    into the disc's own colour and stops at a visible circular edge, which is
    worse-looking and always works. It is built here, beside the real one, so
    both are drawn by the same code and a change to one cannot silently skip
    the other.
    """
    Image, ImageDraw, _ = _pil()

    glow = orb_image(state, phase, level, size=size, unread=unread)
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circle = Image.new("L", (size * SUPERSAMPLE, size * SUPERSAMPLE), 0)
    ImageDraw.Draw(circle).ellipse(
        [2 * SUPERSAMPLE, 2 * SUPERSAMPLE,
         (size - 2) * SUPERSAMPLE, (size - 2) * SUPERSAMPLE],
        fill=255,
    )
    disc.paste(
        Image.new("RGBA", (size, size), (*background, 255)),
        (0, 0),
        circle.resize((size, size), Image.LANCZOS),
    )
    disc.alpha_composite(glow)
    return disc


def flatten_onto(image: Any, background: tuple[int, int, int]) -> Any:
    """Composite an RGBA orb onto an opaque colour. For a view that cannot
    hold alpha at all."""
    from PIL import Image

    base = Image.new("RGB", image.size, background)
    base.paste(image, (0, 0), image)
    return base


def transparent_fraction(image: Any) -> float:
    """How much of the orb's rectangle is fully transparent.

    Recorded because a layered window takes clicks on its whole rectangle: this
    is the share of the orb's area that looks like desktop and does not behave
    like it. Click-through is deliberately not built yet, so the size of the
    problem is measured rather than guessed.
    """
    import numpy as np

    alpha = np.asarray(image.convert("RGBA"))[:, :, 3]
    return float((alpha == 0).sum()) / float(alpha.size)


__all__ = [
    "ANIMATED_STATES",
    "DISC_BACKGROUND",
    "FALLOFF_INNER",
    "FALLOFF_OUTER",
    "ORB_SIZE",
    "ORB_STYLES",
    "OrbStyle",
    "flatten_onto",
    "is_animated",
    "orb_image",
    "orb_on_disc",
    "style_for",
    "transparent_fraction",
]
