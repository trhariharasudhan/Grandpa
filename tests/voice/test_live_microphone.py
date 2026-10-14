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


# --- b) the orb shows it, without an eighth state ---------------------------


def test_the_mark_is_an_overlay_on_every_state_not_a_state() -> None:
    """Standby is neutral white and standby is exactly when the stream is held
    open, so a state would have had to be invented for something true during
    all of them. A mark can be true during all of them."""
    from grandpa.ui.bubble import BubbleState
    from grandpa.ui.orb_image import ORB_STYLES, orb_image

    assert "mic_live" not in ORB_STYLES
    assert not any(state == "mic_live" for state in BubbleState)

    for state in ORB_STYLES:
        plain = np.asarray(orb_image(state, 0.25, 0.0))
        marked = np.asarray(orb_image(state, 0.25, 0.0, mic_live=True))

        assert not np.array_equal(plain, marked), f"{state} shows no mark"


def test_the_mark_sits_inside_the_ring_and_leaves_it_alone() -> None:
    """A second concentric ring, well inside the main one, so it adds
    information rather than changing the state's own shape."""
    from grandpa.ui.orb_image import ORB_SIZE, PIP_RADIUS, RING_RADIUS, orb_image
    from grandpa.ui import orb_image as module

    radius, _turns = module._fields(ORB_SIZE)
    plain = np.asarray(orb_image("idle", 0.0, 0.0))[:, :, 3].astype(float)
    marked = np.asarray(orb_image("idle", 0.0, 0.0, mic_live=True))[:, :, 3].astype(float)
    added = marked - plain

    assert PIP_RADIUS < RING_RADIUS - 0.05, "the mark is not inside the ring"
    inner = radius < (RING_RADIUS - 0.05)
    assert added[inner].sum() > 0, "nothing was added inside"
    # Stated per pixel, not as a total: alpha is an integer, so a single pixel
    # differing by one rounding step contributes 1 and a sum threshold is a
    # pixel count in disguise. With the full halo stack this was 1.72 per
    # pixel; tight it is under a hundredth.
    outer = radius > (RING_RADIUS + 0.02)
    assert float(np.abs(added[outer]).mean()) < 0.05, "the mark reaches the ring"
    assert float(np.abs(added[outer]).max()) <= 2.0


def test_the_corners_stay_transparent_with_the_mark_on() -> None:
    from grandpa.ui.orb_image import ORB_STYLES, orb_image

    for state in ORB_STYLES:
        alpha = np.asarray(orb_image(state, 0.5, 1.0, mic_live=True))[:, :, 3]
        corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]

        assert max(corners) <= 2, f"{state}: {corners}"


def test_the_controller_pushes_the_mark_to_the_orb() -> None:
    from grandpa.ui.bubble import BubbleController

    class Orb:
        def __init__(self) -> None:
            self.live: list[bool] = []

        def set_mic_live(self, live):
            self.live.append(bool(live))

        def set_state(self, state, *, unread):
            pass

    class Panel:
        def set_status_line(self, text):
            self.status = text

    orb = Orb()
    controller = BubbleController(view=Panel(), bridge=object(), orb=orb)

    controller.note_mic_live(True)

    assert orb.live == [True]
    assert controller.mic_live is True
    assert "mic held open" in controller.status_line()

    controller.note_mic_live(False)

    assert orb.live == [True, False]
    assert "mic held open" not in controller.status_line()


def test_the_view_rebuilds_its_frames_when_the_mark_changes() -> None:
    """The frame cache is keyed on the look, and the mark is part of it."""
    from grandpa.ui.orb_view import OrbView

    view = OrbView()
    view.state = "idle"
    view._frames = {0: object()}
    view._frames_key = ("idle", False, False, "layered", 64)

    view.set_mic_live(True)

    assert view.mic_live is True
    assert view._frames == {}


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
