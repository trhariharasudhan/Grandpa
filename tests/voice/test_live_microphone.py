"""The held-open microphone: three conditions, and what a lost device costs.

Why it exists, measured rather than assumed: opening and starting a PortAudio
stream takes 245ms on average and up to 361ms on this machine, and the stream
was opened only *after* the key press was noticed. With the 30ms poll on top,
up to 392ms of speech after the key went down was never recorded. The 0.3s
pre-roll inside ``MicrophoneCapture`` cannot help -- it buffers chunks the
stream already produced, and before the stream starts there are none.

Three conditions were set for holding it open, and each one is a section here:

    a) the pre-roll never reaches disk
    b) the orb shows the microphone is live, without an eighth state
    c) it can be turned off, and then nothing is held open

Plus the question a persistent stream raises that an on-demand one does not:
what happens when the device disappears while the session is running.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from grandpa.voice.live_capture import (
    MAX_PREROLL_CHUNKS,
    PREROLL_SECONDS,
    LiveMicrophone,
)

pytestmark = pytest.mark.core


class FakeStream:
    """A stream that hands out numbered chunks, and can be made to fail."""

    def __init__(self, rate: int = 16_000, channels: int = 1) -> None:
        self.rate = rate
        self.channels = channels
        self.started = False
        self.stopped = False
        self.closed = False
        self.reads = 0
        #: Set to raise from the next read, as an unplugged device does.
        self.fail_with: Exception | None = None
        self._tick = threading.Event()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def read(self, frames: int):
        if self.fail_with is not None:
            raise self.fail_with
        self.reads += 1
        # A ramp, so a test can tell one chunk from another.
        value = min(self.reads * 100, 30_000)
        samples = np.full(frames * self.channels, value, dtype=np.int16)
        time.sleep(0.002)
        return samples, False


class FakeDevice:
    index = 3
    name = "Fake Microphone"
    # _negotiate_capture_settings reads both of these, and a device without
    # them fails the negotiation rather than the open -- which looks like a
    # broken stream and is really a broken double.
    input_channels = 1
    default_sample_rate = 16_000.0


class FakeSelection:
    def __init__(self) -> None:
        self.device = FakeDevice()
        self.warning = ""


class FakeManager:
    def __init__(self, sounddevice) -> None:
        self.sounddevice = sounddevice

    def select(self, **_kwargs):
        return FakeSelection()


class FakeSounddevice:
    def __init__(self) -> None:
        self.streams: list[FakeStream] = []
        self.opened = 0

    def InputStream(self, **kwargs):  # noqa: N802 - mirrors sounddevice
        self.opened += 1
        stream = FakeStream(
            rate=int(kwargs.get("samplerate", 16_000)),
            channels=int(kwargs.get("channels", 1)),
        )
        self.streams.append(stream)
        return stream

    def query_devices(self, *_args, **_kwargs):
        return {
            "name": FakeDevice.name,
            "max_input_channels": 1,
            "default_samplerate": 16_000.0,
        }

    def check_input_settings(self, **_kwargs):
        return None


def a_live_mic(**kwargs) -> tuple[LiveMicrophone, FakeSounddevice]:
    sounddevice = FakeSounddevice()
    mic = LiveMicrophone(
        sounddevice=sounddevice,
        device_manager=FakeManager(sounddevice),
        **kwargs,
    )
    return mic, sounddevice


def wait_for_reads(stream: FakeStream, count: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while stream.reads < count and time.monotonic() < deadline:
        time.sleep(0.005)
    return stream.reads >= count


# --- a) the pre-roll never reaches disk --------------------------------------


def test_nothing_in_the_module_can_write_a_file() -> None:
    """Read as a syntax tree, because this is a promise about a whole file
    rather than about one code path. ``open``, ``write_bytes``, ``write_text``,
    a ``Path`` being built, ``tempfile`` -- any of them would be a way for 300
    milliseconds of someone's kitchen to end up on a disk."""
    source = Path("src/grandpa/voice/live_capture.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_calls = {
        "open", "write", "write_bytes", "write_text", "writelines",
        "mkstemp", "NamedTemporaryFile", "TemporaryFile", "dump", "dumps",
        "savez", "save", "tofile",
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in forbidden_calls:
                offenders.append(f"{name} at line {node.lineno}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            text = ast.unparse(node)
            for module in ("tempfile", "shutil", "pickle", "sqlite3"):
                if module in text:
                    offenders.append(f"{module} imported at line {node.lineno}")

    assert offenders == [], f"the live microphone can write: {offenders}"


def test_no_log_line_carries_audio() -> None:
    """A logger given the buffer would put it in a file just as surely."""
    source = Path("src/grandpa/voice/live_capture.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    logging_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"debug", "info", "warning", "error", "exception"}
    ]

    assert logging_calls == [], f"the module logs at lines {logging_calls}"


def test_the_preroll_is_bounded_in_ram_and_twice_over() -> None:
    """Bounded by seconds and by count, so a device reporting an odd rate
    cannot grow it without limit."""
    mic, sounddevice = a_live_mic()
    assert mic.start() is True
    stream = sounddevice.streams[0]
    try:
        assert wait_for_reads(stream, 12), "the reader never ran"

        held = len(mic._preroll)

        assert held <= mic.preroll_chunks()
        assert held <= MAX_PREROLL_CHUNKS
        assert mic._preroll.maxlen == mic.preroll_chunks()
        assert mic.preroll_chunks() * mic.chunk_seconds <= PREROLL_SECONDS + 1e-9
    finally:
        mic.close()


def test_closing_empties_the_buffer() -> None:
    """Nothing is kept once the session ends."""
    mic, sounddevice = a_live_mic()
    mic.start()
    wait_for_reads(sounddevice.streams[0], 3)

    mic.close()

    assert not mic._preroll
    assert mic._recording is None


def test_capturing_writes_nothing_anywhere(tmp_path: Path) -> None:
    """The behavioural half of (a): a whole utterance, and the scratch
    directory is still empty afterwards. The suite's write guard would also
    refuse a write outside it, so this covers both."""
    before = set(tmp_path.rglob("*"))
    mic, sounddevice = a_live_mic()
    mic.start()
    wait_for_reads(sounddevice.streams[0], 3)

    stop = threading.Event()
    threading.Timer(0.12, stop.set).start()
    audio = mic.capture(stop_event=stop)
    mic.close()

    assert audio.data, "nothing was captured, so nothing was proved"
    assert set(tmp_path.rglob("*")) == before


# --- the pre-roll is actually used ------------------------------------------


def test_the_utterance_begins_with_the_preroll() -> None:
    """The whole point. Without this the first word is still missing; the
    stream merely happens to be open."""
    mic, sounddevice = a_live_mic()
    mic.start()
    stream = sounddevice.streams[0]
    try:
        assert wait_for_reads(stream, 4), "the reader never ran"

        stop = threading.Event()
        threading.Timer(0.15, stop.set).start()
        audio = mic.capture(stop_event=stop)

        assert mic.last_preroll_chunks > 0, "the utterance started from silence"
        assert audio.chunks_read > mic.last_preroll_chunks, (
            "nothing was recorded after the key went down"
        )
        assert audio.captured_frame_count > 0
    finally:
        mic.close()


def test_the_preroll_is_cleared_between_utterances() -> None:
    """Otherwise the second hold would open with the tail of the first."""
    mic, sounddevice = a_live_mic()
    mic.start()
    wait_for_reads(sounddevice.streams[0], 4)
    try:
        stop = threading.Event()
        threading.Timer(0.12, stop.set).start()
        mic.capture(stop_event=stop)

        assert not mic._preroll
    finally:
        mic.close()


def test_the_level_callback_still_fires_per_chunk() -> None:
    """The meter and the waveform read the same numbers they always did."""
    levels: list[float] = []
    mic, sounddevice = a_live_mic(on_level=levels.append)
    mic.start()
    try:
        # Waiting on the reads races the callback, which happens after the
        # read; wait on the thing being asserted instead.
        deadline = time.monotonic() + 2.0
        while len(levels) < 5 and time.monotonic() < deadline:
            time.sleep(0.005)

        assert len(levels) >= 5
        assert all(value >= 0.0 for value in levels)
    finally:
        mic.close()


def test_a_meter_that_raises_does_not_stop_the_reader() -> None:
    def explode(_level: float) -> None:
        raise RuntimeError("the meter is broken")

    mic, sounddevice = a_live_mic(on_level=explode)
    mic.start()
    try:
        assert wait_for_reads(sounddevice.streams[0], 4)
        assert mic.live is True
    finally:
        mic.close()


# --- b) the orb shows ONE ring, and the fact is reported in words -----------
#
# Round 4 asked for the microphone's state on the orb without an eighth state,
# and got a small concentric ring. Measured on screen at the 48px orb, that is
# not a mark on a ring -- it is a second ring: two lit peaks, radius 5 and
# radius 15 physical pixels, the inner one 80% as bright as the outer. The
# requirement is withdrawn. The orb draws one ring; the fact is still reported,
# in words, in the two places below.


def _radial_bands(alpha, share: float = 0.5):
    """Connected bands of lit pixels, by distance from the centre.

    One ring is one band. Returns a list of ``(inner, outer)`` radii in pixels.

    **Maximum over angles, not mean.** A mean counts angular variation as
    radial structure: the arc animations light part of the circle so the mean
    dips where the ring is dark, and the waveform displaces the edge per angle
    so the mean smears over several radii. Measured, a mean-and-local-maxima
    counter reported four rings for thinking, which has one. A maximum cannot
    be dimmed by an arc and is merely widened by a waveform.

    *share* of the brightest radius is the threshold; a halo shoulder sits well
    under half and a second ring sits well over it. The mark that was removed
    measured 221 against the ring's 255 with a trough of 40 between them.
    """
    alpha = np.asarray(alpha, dtype=np.float32)
    size = alpha.shape[0]
    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    distance = np.hypot(xs - centre, ys - centre)
    edges = np.arange(0.0, size / 2.0, 0.5)
    peak_at = np.array([
        alpha[(distance >= edge) & (distance < edge + 0.5)].max(initial=0.0)
        for edge in edges
    ])
    if peak_at.max() <= 0:
        return []
    lit = peak_at >= peak_at.max() * share
    bands, start = [], None
    for i, on in enumerate(lit):
        if on and start is None:
            start = i
        elif not on and start is not None:
            bands.append((float(edges[start]), float(edges[i - 1])))
            start = None
    if start is not None:
        bands.append((float(edges[start]), float(edges[-1])))
    return bands


def test_the_orb_draws_exactly_one_ring() -> None:
    """The reported fault: "the orb draws TWO rings".

    Every still state, because a peak that only appears mid-animation is still
    a second ring to look at. The animated ones are checked below with their
    own phases.
    """
    from grandpa.ui.orb_image import ORB_STYLES, orb_image

    faults = []
    for state in ORB_STYLES:
        bands = _radial_bands(np.asarray(orb_image(state, 0.0, 0.0))[:, :, 3])
        if len(bands) != 1:
            faults.append(f"{state}: {len(bands)} bands at {bands}")

    assert faults == [], "; ".join(faults)


def test_the_counter_would_notice_a_second_ring() -> None:
    """The mutation, because a counter that cannot fail proves nothing.

    A ring drawn back in where the microphone mark used to be, at the
    brightness it used to have, has to be counted.
    """
    from grandpa.ui import orb_image as module
    from grandpa.ui.orb_image import ORB_SIZE, orb_image

    alpha = np.asarray(orb_image("idle", 0.0, 0.0))[:, :, 3].astype(np.float32)
    assert len(_radial_bands(alpha)) == 1, "the orb already has two"

    radius, _turns = module._fields(ORB_SIZE)
    mark = module._ring(radius, 0.085, 0.0396, 0.45, tight=True) * 0.75
    with_mark = np.clip(alpha + mark * module._taper(ORB_SIZE) * 255.0, 0, 255)

    assert len(_radial_bands(with_mark)) == 2, _radial_bands(with_mark)


def test_one_ring_at_every_phase_of_every_animation() -> None:
    """The waves and the ripple travel outward on purpose and are excluded by
    name: a ring leaving the ring is the animation, not a second ring."""
    from grandpa.ui.orb_image import ORB_STYLES, orb_image, style_for

    travelling = {"waves", "ripple"}
    faults = []
    for state in ORB_STYLES:
        if style_for(state).animation in travelling:
            continue
        for step in range(8):
            alpha = np.asarray(orb_image(state, step / 8.0, 0.4))[:, :, 3]
            bands = _radial_bands(alpha)
            if len(bands) != 1:
                faults.append(
                    f"{state} at phase {step / 8.0}: {len(bands)} rings {bands}"
                )

    assert faults == [], "; ".join(faults)


def test_the_renderer_takes_no_microphone_flag_any_more() -> None:
    """A parameter that changes no pixel is a promise the drawing does not
    keep. It was removed with the mark rather than left accepting a value."""
    import inspect

    from grandpa.ui.orb_image import orb_image, orb_on_disc

    for function in (orb_image, orb_on_disc):
        assert "mic_live" not in inspect.signature(function).parameters


def test_the_orb_view_is_not_told_about_the_microphone_either() -> None:
    from grandpa.ui.orb_view import OrbView

    assert not hasattr(OrbView(), "set_mic_live")
    assert not hasattr(OrbView(), "mic_live")


def test_the_status_line_still_says_the_microphone_is_held_open() -> None:
    """Where the signal lives now. It is the reason removing the mark did not
    remove the fact."""
    from grandpa.ui.bubble import BubbleController

    class Panel:
        def set_status_line(self, text):
            self.status = text

    controller = BubbleController(view=Panel(), bridge=object(), orb=None)

    controller.note_mic_live(True)
    assert controller.mic_live is True
    assert "mic held open" in controller.status_line()

    controller.note_mic_live(False)
    assert "mic held open" not in controller.status_line()


def test_the_command_says_it_on_startup_too() -> None:
    """The other place, and the one a user sees before the panel is open."""
    from pathlib import Path

    source = Path("src/grandpa/cli/bubble_cmd.py").read_text(encoding="utf-8")

    assert "controller.mic_live" in source
    assert "Microphone held open" in source


def test_the_corners_stay_transparent() -> None:
    from grandpa.ui.orb_image import ORB_STYLES, orb_image

    for state in ORB_STYLES:
        alpha = np.asarray(orb_image(state, 0.5, 1.0))[:, :, 3]
        corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]

        assert max(corners) <= 2, f"{state}: {corners}"


# --- c) it can be turned off -------------------------------------------------


def test_the_config_key_exists_and_defaults_to_held_open() -> None:
    from grandpa.core.config import VoiceConfig

    assert VoiceConfig().live_microphone is True


def test_the_config_key_is_settable_through_config_set() -> None:
    """The project's own rule: a documented setting that config set cannot
    reach is not a setting. Checked by field, which is what config set
    validates against."""
    from dataclasses import fields

    from grandpa.core.config import VoiceConfig

    assert "live_microphone" in {field.name for field in fields(VoiceConfig)}


@pytest.mark.parametrize(
    "flag,configured,expected",
    [
        (False, True, True),
        (False, False, False),
        (True, True, False),
        (True, False, False),
    ],
)
def test_the_flag_wins_over_the_config_key(
    monkeypatch, flag: bool, configured: bool, expected: bool
) -> None:
    """Both exist on purpose: the key sets it once, the flag rules it out for
    one run without editing anything."""
    from grandpa.cli import bubble_cmd
    from grandpa.core import config as config_module

    class Voice:
        live_microphone = configured

    class Config:
        voice = Voice()

    monkeypatch.setattr(config_module, "load_config", lambda *a, **k: Config())

    assert bubble_cmd._live_microphone_wanted(flag) is expected


def test_an_unreadable_config_keeps_the_better_default(monkeypatch) -> None:
    from grandpa.cli import bubble_cmd
    from grandpa.core import config as config_module

    def explode(*_args, **_kwargs):
        raise OSError("no config")

    monkeypatch.setattr(config_module, "load_config", explode)

    assert bubble_cmd._live_microphone_wanted(False) is True


def test_with_it_off_no_stream_is_opened() -> None:
    """The proof that turning it off returns to today's behaviour: nothing is
    constructed, so nothing is held."""
    mic, sounddevice = a_live_mic()

    assert sounddevice.opened == 0
    assert mic.live is False

    # And the command's own switch is what decides whether it is even built.
    source = Path("src/grandpa/cli/bubble_cmd.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    guarded = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and isinstance(node.test.func, ast.Name)
        and node.test.func.id == "_live_microphone_wanted"
    ]

    assert len(guarded) == 1, "the live stream is not behind the switch"


def test_the_flag_is_offered_on_the_command() -> None:
    from grandpa.cli.bubble_cmd import bubble

    names = {
        option
        for parameter in bubble.params
        for option in getattr(parameter, "opts", [])
    }

    assert "--no-live-mic" in names


# --- what a lost device costs ------------------------------------------------


def test_a_device_that_disappears_marks_the_stream_dead() -> None:
    """A persistent stream makes an unplugged headset a LIVE failure rather
    than a startup one, so the reader has to notice and say so."""
    mic, sounddevice = a_live_mic()
    mic.start()
    stream = sounddevice.streams[0]
    assert wait_for_reads(stream, 3)
    try:
        stream.fail_with = OSError("device disconnected")

        deadline = time.monotonic() + 2.0
        while mic.live and time.monotonic() < deadline:
            time.sleep(0.01)

        assert mic.live is False, "the reader did not notice the device leaving"
        assert "device disconnected" in mic.last_error
    finally:
        mic.close()


def test_a_hold_after_the_device_left_refuses_rather_than_hangs() -> None:
    """The failure mode worth ruling out: capture() waits on the stop event,
    so a dead stream must be refused before the wait rather than after it."""
    mic, sounddevice = a_live_mic()
    mic.start()
    stream = sounddevice.streams[0]
    wait_for_reads(stream, 3)
    stream.fail_with = OSError("device disconnected")
    deadline = time.monotonic() + 2.0
    while mic.live and time.monotonic() < deadline:
        time.sleep(0.01)

    start = time.perf_counter()
    audio = mic.capture(stop_event=threading.Event())
    elapsed = time.perf_counter() - start
    mic.close()

    assert elapsed < 0.5, f"a dead stream blocked the hold for {elapsed:.2f}s"
    assert audio.finalization_reason == "stream_unavailable"
    assert audio.data == b""


def test_a_device_that_cannot_be_opened_at_all_is_reported_not_raised() -> None:
    """Startup must not die of a missing microphone: the bubble falls back to
    opening on demand and says so."""
    mic = LiveMicrophone(sounddevice=object())

    assert mic.start() is False
    assert mic.last_error
    assert mic.live is False


def test_closing_twice_is_harmless() -> None:
    mic, sounddevice = a_live_mic()
    mic.start()
    mic.close()
    mic.close()

    assert sounddevice.streams[0].closed is True
    assert mic.live is False


def test_starting_twice_opens_one_stream() -> None:
    mic, sounddevice = a_live_mic()
    try:
        assert mic.start() is True
        assert mic.start() is True

        assert sounddevice.opened == 1
    finally:
        mic.close()


def test_it_satisfies_the_contract_the_hold_path_calls() -> None:
    """PushToTalkSession calls capture(stop_event=...) and nothing else, which
    is why this drops into the controller's capture slot untouched."""
    import inspect

    from grandpa.voice.microphone import MicrophoneCapture

    live = inspect.signature(LiveMicrophone.capture).parameters
    demand = inspect.signature(MicrophoneCapture.capture).parameters

    assert set(demand) <= set(live), f"missing {set(demand) - set(live)}"
    assert "stop_event" in live
