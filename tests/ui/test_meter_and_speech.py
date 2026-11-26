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


# =================================================================================
# 1. the scale, derived from this project's own measurements
# =================================================================================


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


# =================================================================================
# 3. the controller keeps the view off the capture thread
# =================================================================================


# =================================================================================
# 4. the spoken reply
# =================================================================================


# =================================================================================
# 8. reading a reply again, because the panel grew a button for it
# =================================================================================
