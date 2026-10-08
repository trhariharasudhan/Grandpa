"""The level meter and the spoken reply.

Both exist because the bubble worked but did not say enough: it recorded with no
sign that it was hearing anything, and it answered in text only.

They land together because they share one consequence. ``capture()`` blocks
until the key comes up and ``speak()`` blocks until the sentence ends, and the
poller called both from the tkinter callback -- so the window was frozen for the
whole hold and could not have animated anything. The hold and the reply now run
on a worker and view updates are queued back, which is what the ``dispatch``
seam below is for.

Nothing here opens a microphone, a speaker or a window: the recorder's
``sounddevice`` module is injected (the shape
``tests/voice/test_capture_never_sits_silent.py`` established), the speaker is a
double, and the view is a recorder.
"""

from __future__ import annotations

import threading
from array import array
from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.ui.bubble import (
    METER_BARS,
    METER_CEILING_RMS,
    METER_FLOOR_RMS,
    BubbleController,
    BubbleState,
    normalise_level,
)

pytestmark = pytest.mark.core


# --- doubles ----------------------------------------------------------------------


@dataclass
class Transcript:
    text: str = "what is the time"
    reason: str = ""
    explanation: str = ""


@dataclass
class Reply:
    text: str = "It is just past four."
    status: str = "ok"
    failed: bool = False


@dataclass
class Bridge:
    speech_ready: bool = True
    reply: Any = field(default_factory=Reply)
    transcriber: Any = field(
        default_factory=lambda: type("T", (), {"model": "base.en"})()
    )
    sent: list[str] = field(default_factory=list)

    def warm(self) -> tuple[bool, str]:
        return True, "ready"

    def transcribe(self, audio: Any) -> Transcript:
        return Transcript()

    def send(self, text: str) -> Any:
        self.sent.append(text)
        return self.reply


@dataclass
class SpeechResult:
    status: str = "completed"


@dataclass
class Speaker:
    """Stands in for SpeechOutputEngine. Opens nothing."""

    spoken: list[str] = field(default_factory=list)
    stops: int = 0
    raises: BaseException | None = None
    result: Any = field(default_factory=SpeechResult)
    #: State observed at the moment speak() was entered.
    state_while_speaking: Any = None
    controller: Any = None

    def speak(self, text: str) -> Any:
        if self.controller is not None:
            self.state_while_speaking = self.controller.state
        if self.raises is not None:
            raise self.raises
        self.spoken.append(text)
        return self.result

    def stop(self) -> dict[str, str]:
        self.stops += 1
        return {"status": "stopped"}


@dataclass
class View:
    states: list[str] = field(default_factory=list)
    status_lines: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    levels: list[tuple[float, ...]] = field(default_factory=list)
    cleared: int = 0

    def show(self, *, position, topmost) -> None:
        pass

    def set_state(self, state: str, label: str) -> None:
        self.states.append(state)

    def set_status_line(self, text: str) -> None:
        self.status_lines.append(text)

    def set_reply(self, text: str) -> None:
        self.replies.append(text)

    def set_transcript(self, text: str) -> None:
        self.transcripts.append(text)

    def set_levels(self, levels: tuple[float, ...]) -> None:
        self.levels.append(tuple(levels))

    def clear_entry(self) -> None:
        self.cleared += 1

    def position(self) -> tuple[int, int]:
        return (0, 0)

    def close(self) -> None:
        pass


class HostileView(View):
    """Fails if touched. Proves a call did not reach the view at all."""

    def set_levels(self, levels: tuple[float, ...]) -> None:
        raise AssertionError("the view was touched from the capture thread")

    def set_state(self, state: str, label: str) -> None:
        raise AssertionError("the view was touched from the capture thread")

    def set_status_line(self, text: str) -> None:
        raise AssertionError("the view was touched from the capture thread")


#: "no speaker at all", told apart from "the default double".
_DEFAULT = object()


def _ready(**kwargs) -> tuple[BubbleController, View, Bridge, Speaker]:
    view = kwargs.pop("view", None) or View()
    bridge = kwargs.pop("bridge", None) or Bridge()
    speaker = kwargs.pop("speaker", _DEFAULT)
    if speaker is _DEFAULT:
        speaker = Speaker()
    controller = BubbleController(
        view=view, bridge=bridge, speaker=speaker, sleep=lambda _s: None, **kwargs
    )
    if isinstance(speaker, Speaker):
        speaker.controller = controller
    controller.state = BubbleState.IDLE
    return controller, view, bridge, speaker


# =================================================================================
# 1. the scale, derived from this project's own measurements
# =================================================================================


def test_the_meter_scale_is_the_measured_one() -> None:
    """Floor near the logged noise floor, ceiling near the loudest peak."""
    assert METER_FLOOR_RMS == 100.0
    assert METER_CEILING_RMS == 2500.0


@pytest.mark.parametrize(
    ("rms", "expected"),
    [
        (0.0, 0.0),
        (90.0, 0.0),  # the noise floor logged beside live captures
        (100.0, 0.0),  # the floor itself
        (2500.0, 1.0),  # the ceiling
        (2994.0, 1.0),  # the loudest max_rms in voice/vad.py, clamped
        (99999.0, 1.0),
    ],
)
def test_the_scale_clamps_at_both_ends(rms: float, expected: float) -> None:
    assert normalise_level(rms) == expected


def test_ordinary_speech_lands_in_the_middle_of_the_meter() -> None:
    """A linear scale would leave it in the bottom ninth and look like silence.

    289 is the average speech chunk from the recording that reported rms 176,
    and 200 is the detector's own minimum_rms.
    """
    assert 0.15 < normalise_level(200.0) < 0.35
    assert 0.25 < normalise_level(289.0) < 0.45
    assert 0.55 < normalise_level(900.0) < 0.80


def test_the_scale_never_raises_on_rubbish() -> None:
    assert normalise_level("junk") == 0.0  # type: ignore[arg-type]
    assert normalise_level(None) == 0.0  # type: ignore[arg-type]
    assert normalise_level(-5.0) == 0.0


# =================================================================================
# 2. the recorder emits levels, and the session did not change
# =================================================================================


class _Frames:
    def __init__(self, samples: array) -> None:
        self._samples = samples

    def tobytes(self) -> bytes:
        return self._samples.tobytes()

    def __len__(self) -> int:
        return len(self._samples)


class _Stream:
    def __init__(self, amplitude: int, stop_after: int) -> None:
        self.amplitude = amplitude
        self.stop_after = stop_after
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, count: int):
        self.reads += 1
        return _Frames(array("h", [self.amplitude] * count)), False

    def close(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _FakeSoundDevice:
    def __init__(self, amplitude: int) -> None:
        self.amplitude = amplitude
        self.stream: _Stream | None = None

    def InputStream(self, **kwargs):  # noqa: N802 - mirrors sounddevice
        self.stream = _Stream(self.amplitude, 4)
        return self.stream

    def check_input_settings(self, **kwargs) -> None:
        return None


class _FixedManager:
    def __init__(self, sounddevice) -> None:
        from grandpa.voice.device_manager import MicrophoneDevice

        self.sounddevice = sounddevice
        self.device = MicrophoneDevice(
            index=9,
            name="Microphone Array (AMD Audio Device)",
            input_channels=1,
            default_sample_rate=16_000,
            host_api=0,
            driver="Windows WASAPI",
            low_input_latency=None,
            high_input_latency=None,
            is_default=False,
            is_default_communications=None,
            is_virtual=False,
            transport="built-in",
        )

    def select(self, **kwargs):
        from grandpa.voice.device_manager import MicrophoneSelection

        return MicrophoneSelection(self.device)


def _recorder(on_level, amplitude: int = 900):
    from grandpa.voice.microphone import MicrophoneCapture
    from grandpa.voice.push_to_talk import (
        MAXIMUM_HOLD_SECONDS,
        hold_to_talk_vad_config,
    )

    fake = _FakeSoundDevice(amplitude)
    recorder = MicrophoneCapture(
        duration_seconds=2.0,
        vad_config=hold_to_talk_vad_config(MAXIMUM_HOLD_SECONDS),
        sounddevice=fake,
        device_manager=_FixedManager(fake),
        on_level=on_level,
    )
    return recorder, fake


def test_the_recorder_emits_one_level_per_chunk() -> None:
    """Through the real capture loop, with the device injected."""
    seen: list[float] = []
    recorder, fake = _recorder(seen.append)
    stop = threading.Event()

    def release() -> None:
        # Let a few chunks through, then end the recording.
        while len(seen) < 3:
            pass
        stop.set()

    watcher = threading.Thread(target=release, daemon=True)
    watcher.start()
    recorder.capture(stop_event=stop)
    watcher.join(timeout=5.0)

    assert len(seen) >= 3, "no levels arrived from the capture loop"
    assert fake.stream is not None
    assert len(seen) == fake.stream.reads, "a chunk was read without a level"
    assert all(0.0 <= value <= 32768.0 for value in seen)


def test_a_failing_meter_callback_does_not_end_the_recording() -> None:
    """A meter is chrome. It must not be able to lose an utterance."""

    def explode(_rms: float) -> None:
        raise RuntimeError("meter is broken")

    recorder, _fake = _recorder(explode)
    stop = threading.Event()
    stop.set()

    audio = recorder.capture(stop_event=stop)

    assert audio is not None


def test_the_session_forwards_only_a_stop_event() -> None:
    """Why PushToTalkSession needed no change, pinned.

    The level callback is configured on the *recorder*, and the session hands
    the recorder nothing but the stop event. So there is no place in the session
    that has to learn about levels -- which is the reason it could be left
    alone for the third round running.
    """
    import inspect

    from grandpa.voice.push_to_talk import PushToTalkSession

    source = inspect.getsource(PushToTalkSession.record_while_held)

    whole = inspect.getsource(PushToTalkSession)

    assert "self.capture.capture(stop_event=stop)" in source
    assert "on_level" not in whole, "the session learned about the meter"
    assert "note_level" not in whole
    assert "meter" not in whole.lower()


def test_levels_reach_the_controller_through_the_session() -> None:
    """End to end: recorder -> session -> controller, with no session change."""
    from grandpa.voice.push_to_talk import PushToTalkSession

    controller, _view, _bridge, _speaker = _ready()
    recorder, _fake = _recorder(controller.note_level)

    class Probe:
        """Held until three chunks have been recorded, as a real hold would be."""

        def is_down(self, key: str) -> bool:
            return len(controller._levels) < 3

    session = PushToTalkSession(
        capture=recorder,
        transcriber=None,
        probe=Probe(),
        key="ctrl+win",
        echo=lambda _m: None,
        sleep=lambda _s: None,
    )

    session.record_while_held()

    assert controller.meter_levels() != (0.0,) * METER_BARS, (
        "no level reached the controller"
    )


# =================================================================================
# 3. the controller keeps the view off the capture thread
# =================================================================================


def test_note_level_never_touches_the_view() -> None:
    """It runs on whichever thread is inside capture(). tkinter forbids that."""
    controller, _view, _bridge, _speaker = _ready(view=HostileView())

    for rms in (120.0, 400.0, 2000.0):
        controller.note_level(rms)

    assert controller.meter_levels()[-1] > 0.0


def test_the_meter_is_padded_to_its_full_width() -> None:
    controller, _view, _bridge, _speaker = _ready()

    controller.note_level(900.0)

    levels = controller.meter_levels()
    assert len(levels) == METER_BARS
    assert levels[0] == 0.0, "history should start empty, not full"
    assert levels[-1] > 0.0, "the newest level belongs at the end"


def test_the_meter_only_draws_while_recording() -> None:
    controller, view, _bridge, _speaker = _ready()
    controller.note_level(900.0)

    controller.state = BubbleState.IDLE
    controller.refresh_meter()
    controller.state = BubbleState.RECORDING
    controller.refresh_meter()

    assert view.levels[0] == (), "an idle bubble must show a resting meter"
    assert len(view.levels[1]) == METER_BARS


def test_the_view_is_handed_normalised_values_not_an_rms() -> None:
    controller, view, _bridge, _speaker = _ready()
    for rms in (50.0, 300.0, 1500.0, 99999.0):
        controller.note_level(rms)
    controller.state = BubbleState.RECORDING

    controller.refresh_meter()

    assert all(0.0 <= value <= 1.0 for value in view.levels[-1])


def test_a_hold_starts_from_an_empty_meter() -> None:
    """Otherwise the last utterance's tail is still on screen for the next one."""
    controller, _view, _bridge, _speaker = _ready(probe=None, capture=None)
    controller.note_level(2000.0)
    assert controller.meter_levels()[-1] > 0.0

    controller.on_hold()  # refused -- no probe -- but the reset happens first

    assert controller.meter_levels() == (0.0,) * METER_BARS or (
        controller.state is BubbleState.ERROR
    )


def test_updates_are_queued_when_a_dispatcher_is_set() -> None:
    """The mechanism that lets a worker thread drive a tkinter view."""
    controller, view, _bridge, _speaker = _ready()
    queued: list[Any] = []
    controller.dispatch = queued.append

    controller._enter(BubbleState.RECORDING)

    assert view.states == [], "the view was touched directly"
    assert controller.state is BubbleState.RECORDING, "state must change at once"
    for update in queued:
        update()
    assert view.states == ["recording"]


# =================================================================================
# 4. the spoken reply
# =================================================================================


def test_a_reply_is_spoken_as_well_as_shown() -> None:
    controller, view, _bridge, speaker = _ready()

    controller.submit("what is the time")

    assert view.replies == ["It is just past four."], "the text must still appear"
    assert speaker.spoken == ["It is just past four."]


def test_the_text_is_on_screen_before_the_speaking_starts() -> None:
    """Speech is in addition, not instead -- and not before, either."""
    controller, view, _bridge, speaker = _ready()

    controller.submit("hello")

    assert speaker.state_while_speaking is BubbleState.SPEAKING
    assert view.replies, "the reply was spoken before it was shown"


def test_speaking_is_a_state_the_user_can_see() -> None:
    controller, view, _bridge, _speaker = _ready()

    controller.submit("hello")

    assert "speaking" in view.states
    assert view.states[-1] == "idle", "it must come back to idle afterwards"


def test_a_speech_failure_keeps_the_reply() -> None:
    """The text already arrived. Losing the audio is not losing the answer."""
    controller, view, _bridge, speaker = _ready(
        speaker=Speaker(raises=RuntimeError("no voice"))
    )

    returned = controller.submit("hello")

    assert returned == "It is just past four."
    assert view.replies == ["It is just past four."]
    assert "Could not speak" in view.status_lines[-1]
    assert controller.state is BubbleState.IDLE, "a mute reply is not an error state"


def test_a_print_only_fallback_says_the_reply_was_not_spoken() -> None:
    """The engine reports rather than raises, so the report has to be read."""
    controller, view, _bridge, _speaker = _ready(
        speaker=Speaker(result=SpeechResult(status="fallback"))
    )

    controller.submit("hello")

    assert "not spoken" in view.status_lines[-1]


def test_speech_can_be_turned_off() -> None:
    controller, view, _bridge, speaker = _ready(speak_replies=False)

    controller.submit("hello")

    assert view.replies == ["It is just past four."]
    assert speaker.spoken == []
    assert "speaking" not in view.states


def test_the_toggle_turns_it_off_and_on() -> None:
    controller, _view, _bridge, speaker = _ready()

    assert controller.toggle_speech() is False
    controller.submit("hello")
    assert speaker.spoken == []

    assert controller.toggle_speech() is True
    controller.submit("hello again")
    assert speaker.spoken == ["It is just past four."]


def test_turning_it_off_stops_a_reply_already_speaking() -> None:
    controller, _view, _bridge, speaker = _ready()
    controller.state = BubbleState.SPEAKING

    controller.toggle_speech()

    assert speaker.stops == 1
    assert controller.state is BubbleState.IDLE


def test_holding_the_key_interrupts_a_reply() -> None:
    """Mid-sentence, which is the whole point of being able to interrupt."""
    controller, _view, _bridge, speaker = _ready(probe=None, capture=None)
    controller.state = BubbleState.SPEAKING

    controller.on_hold()

    assert speaker.stops == 1, "the hold did not interrupt the reply"


def test_speaking_does_not_refuse_a_hold() -> None:
    """Unlike recording or thinking: interrupting is allowed, ignoring is not."""
    from grandpa.ui.bubble import STATES_THAT_REFUSE_A_HOLD

    assert BubbleState.SPEAKING not in STATES_THAT_REFUSE_A_HOLD


def test_a_failed_reply_is_not_spoken() -> None:
    """Reading an error is enough; hearing it read out is not better."""
    bridge = Bridge(reply=Reply(text="That did not work.", failed=True))
    controller, view, _bridge, speaker = _ready(bridge=bridge)

    controller.submit("do something impossible")

    assert view.replies == ["That did not work."]
    assert speaker.spoken == []


def test_no_speaker_at_all_is_not_an_error() -> None:
    controller, view, _bridge, _speaker = _ready(speaker=None)

    returned = controller.submit("hello")

    assert returned == "It is just past four."
    assert "speaking" not in view.states


def test_interrupting_without_a_speaker_is_harmless() -> None:
    controller, _view, _bridge, _speaker = _ready()
    controller.speaker = None

    assert controller.interrupt_speech() is False


def test_an_engine_that_cannot_stop_is_reported_as_not_stopped() -> None:
    class NoStop:
        def speak(self, text: str) -> Any:
            return SpeechResult()

    controller, _view, _bridge, _speaker = _ready()
    controller.speaker = NoStop()

    assert controller.interrupt_speech() is False
