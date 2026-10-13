"""The fallback, and proof that the thing which chooses it can actually fire.

A fallback nobody can trigger is a promise, not a fallback. So this file does
three separate jobs, and the third is the one that matters:

1. the failure is *detected* -- a refused Win32 call is noticed rather than
   assumed to have worked, including against the real API with a handle it
   cannot possibly accept;
2. the fallback then *engages* and produces a usable orb, asserted on the image
   it produced rather than on the fact that a method was called;
3. the detection is **mutation-proved**: the same assertions are run against a
   chooser with the return-value check removed, and they must fail. Otherwise
   this file would pass just as happily against code that never checks
   anything.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from grandpa.ui.layered import (
    AC_SRC_ALPHA,
    DiscPainter,
    LayeredPainter,
    PainterChoice,
    premultiplied_bgra,
)
from grandpa.ui.orb_image import orb_image

pytestmark = pytest.mark.core


def a_layered(call, hwnd: int = 1234) -> LayeredPainter:
    """A painter whose window is taken as already carrying the layered style.

    Whether the style was really set is its own question with its own tests
    below; these are about what the painter does with the *result* of the blit,
    and a fake handle cannot be given a real window style.
    """
    painter = LayeredPainter(hwnd=hwnd, update_layered_window=call)
    painter._prepared.add(hwnd)
    return painter


def a_choice(*, call, drawn: list) -> PainterChoice:
    return PainterChoice(
        primary=a_layered(call),
        fallback=DiscPainter(show=lambda image, x, y: drawn.append((image, x, y))),
    )


# --- 1. the refusal is detected ---------------------------------------------


def test_a_refused_call_is_noticed_rather_than_assumed_to_have_worked() -> None:
    """UpdateLayeredWindow reports by return value. Dropping it is the whole
    failure mode this guards: the orb would be invisible and nothing would say
    so."""
    painter = a_layered(lambda *_a: 0)

    assert painter.paint(orb_image("idle"), 10, 10) is False
    assert "UpdateLayeredWindow" in painter.last_error


def test_a_raising_call_is_also_a_refusal() -> None:
    """A ctypes ArgumentError is the realistic shape of this -- the 64-bit
    handle trap in layered.py's docstring raised rather than returned."""

    def explode(*_args):
        raise OverflowError("int too long to convert")

    painter = a_layered(explode)

    assert painter.paint(orb_image("idle"), 0, 0) is False
    assert "OverflowError" in painter.last_error


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real Win32 API")
@pytest.mark.parametrize("hwnd", [0, 1, 0xDEAD])
def test_the_real_api_refusing_a_bad_handle_is_detected(hwnd: int) -> None:
    """Not a stub: the actual Win32 calls, with window handles they cannot
    accept. If the detection only worked against injected failures it would be
    testing the injection."""
    painter = LayeredPainter(hwnd=hwnd)

    assert painter.paint(orb_image("idle"), 0, 0) is False
    assert painter.last_error, "the real refusal left no reason"


def test_the_handle_is_read_at_paint_time_not_captured_once() -> None:
    """The bug this exists for: tk re-creates a borderless toplevel's window
    when it maps it, so a handle read during setup is stale by the first frame
    -- and the blit to the stale window *succeeded*, which is precisely the
    failure the return-value check was supposed to catch.
    """
    handles = [111, 222, 333]
    painted: list[int] = []

    def call(hwnd, *_rest):
        painted.append(hwnd)
        return 1

    painter = LayeredPainter(
        hwnd=lambda: handles[len(painted)], update_layered_window=call
    )
    painter._prepared.update(handles)  # the style question is covered below
    for _ in range(3):
        painter.paint(orb_image("idle"), 0, 0)

    assert painted == handles, "the painter reused a handle it was given once"


def test_a_window_that_will_not_take_the_layered_style_is_a_refusal() -> None:
    """Verified rather than assumed. Without the style bit the blit is
    meaningless, and that is how the orb was nowhere while every call said it
    had worked."""
    painter = LayeredPainter(hwnd=0, update_layered_window=lambda *_a: 1)

    assert painter.prepare() is False
    assert painter.paint(orb_image("idle"), 0, 0) is False
    assert "handle" in painter.last_error


def test_the_style_is_set_once_per_window_not_once_per_frame() -> None:
    """At 20fps a redundant pair of Win32 calls per frame is pure waste."""
    prepared: list[int] = []
    painter = LayeredPainter(hwnd=lambda: 777, update_layered_window=lambda *_a: 1)

    def pretend(hwnd=None):
        prepared.append(777)
        painter._prepared.add(777)
        return True

    painter.prepare = pretend  # type: ignore[method-assign]

    for _ in range(4):
        painter.paint(orb_image("idle"), 0, 0)

    assert len(prepared) == 1


# --- 2. the fallback engages, and what it produces is an orb ----------------


def test_the_first_refusal_switches_to_the_fallback() -> None:
    drawn: list = []
    choice = a_choice(call=lambda *_a: 0, drawn=drawn)

    assert choice.mode == "layered"
    assert choice.paint(orb_image("idle"), 7, 9) is True
    assert choice.mode == "disc"
    assert choice.demoted is True
    assert len(drawn) == 1


def test_the_fallback_path_produces_a_usable_orb() -> None:
    """Asserted on the pixels it handed over: an opaque disc with a visible
    ring at the right radius, placed where it was asked to be. "The fallback
    was called" would not distinguish this from a blank square."""
    drawn: list = []
    choice = a_choice(call=lambda *_a: 0, drawn=drawn)
    from grandpa.ui.orb_image import orb_on_disc

    choice.paint(orb_on_disc("recording", 0.0, 0.8), 120, 240)

    image, x, y = drawn[-1]
    pixels = np.asarray(image.convert("RGBA"))
    size = pixels.shape[0]
    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    radii = np.hypot(xs - centre, ys - centre) / size
    ring = (radii >= 0.26) & (radii <= 0.34)
    middle = radii < 0.12

    assert (x, y) == (120, 240)
    assert pixels[size // 2, size // 2, 3] == 255, "not an opaque disc"
    assert pixels[0, 0, 3] == 0, "the fallback filled the corners"
    assert pixels[:, :, :3][ring].mean() > pixels[:, :, :3][middle].mean() + 20


def test_the_primary_is_not_retried_every_frame_once_it_has_refused() -> None:
    """A driver that declines one frame declines the next, and flapping between
    two looks would be worse than either."""
    attempts: list[int] = []

    def refuse(*_args):
        attempts.append(1)
        return 0

    drawn: list = []
    choice = a_choice(call=refuse, drawn=drawn)
    for _ in range(5):
        choice.paint(orb_image("idle"), 0, 0)

    assert len(attempts) == 1, "the refused painter was asked again"
    assert len(drawn) == 5


def test_the_status_line_says_which_painter_is_running() -> None:
    """So a machine quietly on the fallback is visible rather than merely
    worse-looking."""
    drawn: list = []
    choice = a_choice(call=lambda *_a: 0, drawn=drawn)

    assert choice.describe() == "orb: glow"

    choice.paint(orb_image("idle"), 0, 0)

    assert choice.describe().startswith("orb: flat disc (")
    assert "UpdateLayeredWindow" in choice.describe()


def test_a_working_primary_is_left_alone() -> None:
    """The other half: a machine that can do per-pixel alpha must not be
    demoted by a detection that fires on success."""
    drawn: list = []
    choice = a_choice(call=lambda *_a: 1, drawn=drawn)

    for _ in range(3):
        assert choice.paint(orb_image("idle"), 0, 0) is True

    assert choice.mode == "layered"
    assert choice.demoted is False
    assert drawn == []
    assert choice.describe() == "orb: glow"


# --- 3. mutation-proving the detection --------------------------------------


class ChoiceThatIgnoresRefusals(PainterChoice):
    """The mutation: the return value is dropped, exactly as code that assumes
    success rather than checking it would do."""

    def paint(self, image, x, y):  # noqa: ANN001, ANN201 - mirrors the base
        self.primary.paint(image, x, y)
        return True


def test_the_detection_is_what_makes_the_fallback_engage() -> None:
    """Run the proofs above against the mutated chooser. Every one must fail.

    This is the part that stops this file from passing against code that never
    detects anything: if dropping the check changed no assertion, none of the
    assertions were about the check.
    """
    drawn: list = []
    mutated = ChoiceThatIgnoresRefusals(
        primary=a_layered(lambda *_a: 0),
        fallback=DiscPainter(show=lambda image, x, y: drawn.append(image)),
    )

    for _ in range(5):
        mutated.paint(orb_image("idle"), 0, 0)

    # What the real chooser guarantees, and the mutant does not.
    assert mutated.mode == "layered", "the mutant demoted, so it is not a mutant"
    assert mutated.demoted is False
    assert drawn == [], "the mutant reached the fallback without a detection"
    assert mutated.describe() == "orb: glow", (
        "the mutant's status line would have reported the fallback"
    )


def test_the_mutant_and_the_real_chooser_disagree_on_the_same_input() -> None:
    """Stated as a difference rather than two separate facts, so it cannot be
    satisfied by both being broken in the same direction."""
    real_drawn: list = []
    mutant_drawn: list = []
    real = PainterChoice(
        primary=a_layered(lambda *_a: 0),
        fallback=DiscPainter(show=lambda image, x, y: real_drawn.append(image)),
    )
    mutant = ChoiceThatIgnoresRefusals(
        primary=a_layered(lambda *_a: 0),
        fallback=DiscPainter(show=lambda image, x, y: mutant_drawn.append(image)),
    )

    image = orb_image("idle")
    real.paint(image, 0, 0)
    mutant.paint(image, 0, 0)

    assert (real.mode, len(real_drawn)) == ("disc", 1)
    assert (mutant.mode, len(mutant_drawn)) == ("layered", 0)
    assert real.describe() != mutant.describe()


# --- 4. the bytes the Win32 call is handed ----------------------------------


def test_the_alpha_is_premultiplied_because_the_glow_depends_on_it() -> None:
    """Without this the semi-transparent pixels composite far too bright and
    the orb gets a white core -- which looks like a design choice rather than a
    bug, so it is pinned here."""
    from PIL import Image

    source = Image.new("RGBA", (2, 1), (255, 255, 255, 128))
    raw = premultiplied_bgra(source)

    blue, green, red, alpha = raw[0], raw[1], raw[2], raw[3]

    assert alpha == 128
    assert (blue, green, red) == (128, 128, 128), "colour was not premultiplied"
    assert len(raw) == 2 * 1 * 4


def test_a_transparent_pixel_carries_no_colour_at_all() -> None:
    """Otherwise the invisible part of the glow still tints what is behind it."""
    from PIL import Image

    raw = premultiplied_bgra(Image.new("RGBA", (1, 1), (255, 0, 0, 0)))

    assert tuple(raw) == (0, 0, 0, 0)


def test_the_blend_asks_windows_to_use_the_source_alpha() -> None:
    """AC_SRC_ALPHA is what makes it per-pixel rather than one window-wide
    opacity, which is the measured difference from -transparentcolor."""
    assert AC_SRC_ALPHA == 0x01
