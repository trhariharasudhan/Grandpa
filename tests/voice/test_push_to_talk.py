"""A held key must beat an adaptive threshold nobody can tune.

Three rounds of fixes went into the automatic detector and a sentence still did
not get through. This path removes the detector's decision entirely: the key
down is the start of the utterance, the key up is the end, every frame between
is kept, and nothing about the audio can cause a refusal.

The audio guard stays armed throughout. The key probe and the recorder are both
injected, so no microphone is opened and no keyboard is read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.push_to_talk import (
    KEY_CODES,
    MAXIMUM_HOLD_SECONDS,
    PushToTalkSession,
    WindowsKeyProbe,
    hold_to_talk_vad_config,
)
from grandpa.voice.vad import VoiceActivityDetector

pytestmark = pytest.mark.core

CHUNK = 0.1


# --- doubles ----------------------------------------------------------------------


class ScriptedProbe:
    """Answers ``is_down`` from a script, then stays up forever."""

    def __init__(self, script: list[bool]) -> None:
        self.script = list(script)
        self.calls = 0

    def is_down(self, key: str) -> bool:
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        return False


@dataclass
class FakeCapture:
    """Records how long the stop event took to arrive. Opens nothing."""

    audio: CapturedAudio
    stop_was_set: bool = False
    device: int | None = 9

    def capture(self, stop_event: Any = None, on_speech_start: Any = None):
        # The real recorder loops until the stop event is set; waiting for it
        # here is what proves the key, not the audio, ends the capture.
        if stop_event is not None:
            self.stop_was_set = stop_event.wait(timeout=5.0)
        return self.audio

    def close(self) -> None:
        pass


@dataclass
class FakeTranscriber:
    text: str = "open notepad"
    seen: list[CapturedAudio] = field(default_factory=list)

    def transcribe(self, audio: CapturedAudio) -> str:
        self.seen.append(audio)
        return self.text


@dataclass
class FakeResponse:
    text: str


@dataclass
class FakeResponder:
    reply: str = "Opening Notepad."
    inputs: list[str] = field(default_factory=list)

    def handle_user_input(self, text: str) -> FakeResponse:
        self.inputs.append(text)
        return FakeResponse(self.reply)


@dataclass
class FakeSpeaker:
    spoken: list[str] = field(default_factory=list)

    def speak(self, text: str, stop_event: Any = None) -> None:
        self.spoken.append(text)


def _audio(frames: int = 16_000, rms: float = 1200.0) -> CapturedAudio:
    return CapturedAudio(
        data=b"RIFF" + b"\x00" * 64,
        captured_frame_count=frames,
        rms_level=rms,
        speech_detected=True,
        finalization_reason="cancelled",
    )


def _session(**overrides: Any) -> tuple[PushToTalkSession, dict[str, Any]]:
    parts: dict[str, Any] = {
        "capture": FakeCapture(_audio()),
        "transcriber": FakeTranscriber(),
        "probe": ScriptedProbe([False, True, True, False]),
        "responder": FakeResponder(),
        "speaker": FakeSpeaker(),
    }
    parts.update(overrides)
    lines: list[str] = []
    clock = iter([0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4])
    session = PushToTalkSession(
        echo=lines.append,
        sleep=lambda _seconds: None,
        clock=lambda: next(clock, 1.4),
        **parts,
    )
    parts["lines"] = lines
    return session, parts


# --- 1. the detector cannot refuse anything ----------------------------------------


def test_the_hold_config_classifies_every_chunk_as_speech() -> None:
    """Including digital silence. There is no level that can be rejected."""
    config = hold_to_talk_vad_config()
    detector = VoiceActivityDetector(config)

    assert detector.current_threshold == 0.0
    for level in (0.0, 1.0, 50.0, 179.0, 3000.0):
        assert detector.observe(level, CHUNK) is False
        assert detector.speech_started is True


def test_speech_starts_on_the_very_first_chunk_so_no_audio_is_held_back() -> None:
    """The recorder only keeps 0.3s of pre-roll before onset; onset is immediate."""
    detector = VoiceActivityDetector(hold_to_talk_vad_config())

    detector.observe(0.0, CHUNK)

    assert detector.speech_started is True
    assert detector.speech_onset_seconds == pytest.approx(0.0, abs=0.01)


def test_the_no_speech_timeout_that_ended_every_failing_capture_is_disabled() -> None:
    """Eight seconds of nothing used to end the capture with no_speech_timeout."""
    config = hold_to_talk_vad_config()
    assert config.silence_before_speech_seconds == 0.0

    detector = VoiceActivityDetector(config)
    for _ in range(int(20 / CHUNK)):
        assert detector.observe(0.0, CHUNK) is False, "20s of silence ended it"
    assert detector.finalization_reason is None


def test_trailing_silence_can_never_finalise_the_utterance() -> None:
    """A mid-sentence pause -- however long -- cannot cut the recording."""
    detector = VoiceActivityDetector(hold_to_talk_vad_config())
    for _ in range(int(30 / CHUNK)):
        assert detector.observe(0.0, CHUNK) is False
    assert detector.trailing_silence_seconds == 0.0


def test_a_stuck_key_still_cannot_record_forever() -> None:
    """The one bound that remains, and it is time, not level."""
    config = hold_to_talk_vad_config(maximum_seconds=2.0)
    detector = VoiceActivityDetector(config)

    finished = False
    for _ in range(int(10 / CHUNK)):
        if detector.observe(500.0, CHUNK):
            finished = True
            break
    assert finished is True
    assert detector.finalization_reason == "maximum_duration"


# --- 2. the key, and only the key, ends the recording ------------------------------


def test_the_capture_runs_until_the_key_comes_up() -> None:
    session, parts = _session(probe=ScriptedProbe([True, True, True, False]))

    result = session.run_once()

    assert result is not None
    assert parts["capture"].stop_was_set is True, (
        "the recorder was never told to stop, so a release does not end a capture"
    )
    assert result.reason == "key_released"


def test_waiting_for_the_press_does_not_record() -> None:
    probe = ScriptedProbe([False, False, False, True, False])
    session, parts = _session(probe=probe)

    session.run_once()

    assert probe.calls >= 4
    assert "Recording..." in parts["lines"]
    assert parts["lines"].index("Recording...") > 0


def test_on_idle_can_end_the_loop_before_any_recording() -> None:
    """Esc while waiting must not be read as a press."""
    session, parts = _session(probe=ScriptedProbe([False, False]))
    session.on_idle = lambda: True

    assert session.run_once() is None
    assert "Recording..." not in parts["lines"]
    assert parts["capture"].stop_was_set is False


# --- 3. what the transcript does and does not do -----------------------------------


def test_a_real_utterance_is_transcribed_routed_and_spoken() -> None:
    session, parts = _session()

    result = session.run_once()

    assert result is not None
    assert result.transcript == "open notepad"
    assert parts["responder"].inputs == ["open notepad"]
    assert parts["speaker"].spoken == ["Opening Notepad."]
    assert result.response == "Opening Notepad."


def test_an_empty_transcription_is_not_routed_anywhere() -> None:
    """An empty transcription is not a command and must not be read as one."""
    session, parts = _session(transcriber=FakeTranscriber(text="   "))

    result = session.run_once()

    assert result is not None
    assert result.reason == "empty_transcript"
    assert parts["responder"].inputs == []
    assert parts["speaker"].spoken == []
    assert any("Nothing recognisable" in line for line in parts["lines"])


def test_a_tap_is_not_an_utterance_and_says_so() -> None:
    """The only threshold left is on how long the key was held."""
    session, parts = _session()
    session.clock = lambda: 0.0  # pressed and released instantly

    result = session.run_once()

    assert result is not None
    assert result.reason == "too_short"
    assert parts["transcriber"].seen == []
    assert parts["responder"].inputs == []
    assert any("tap" in line for line in parts["lines"])


def test_a_hold_that_captured_no_audio_says_which_fault_it_was() -> None:
    """A dead device is a different fault from audio that is too quiet."""
    session, parts = _session(capture=FakeCapture(_audio(frames=0)))

    result = session.run_once()

    assert result is not None
    assert result.reason == "no_audio"
    assert parts["transcriber"].seen == []
    assert any("no audio" in line for line in parts["lines"])


def test_it_never_sits_silent() -> None:
    """Every path through one hold prints something the user can act on."""
    for overrides in (
        {},
        {"transcriber": FakeTranscriber(text="")},
        {"capture": FakeCapture(_audio(frames=0))},
    ):
        session, parts = _session(**overrides)
        session.run_once()
        assert parts["lines"], overrides
        assert parts["lines"][-1].strip()


def test_no_route_leaves_the_transcript_unacted_on() -> None:
    session, parts = _session(responder=None, speaker=None)

    result = session.run_once()

    assert result is not None
    assert result.transcript == "open notepad"
    assert result.response is None


def test_an_exit_phrase_ends_the_loop() -> None:
    session, parts = _session(transcriber=FakeTranscriber(text="goodbye"))
    # The probe's script is exhausted after one hold, so a second pass would
    # wait forever. This stops it -- and the exit phrase must get there first,
    # which is what makes the assertion below meaningful.
    passes: list[int] = []

    def idle() -> bool:
        passes.append(1)
        return len(passes) > 2

    session.on_idle = idle

    results = session.run()

    assert len(results) == 1
    assert results[0].transcript == "goodbye"
    assert "Goodbye." in parts["lines"]


def test_once_handles_exactly_one_hold() -> None:
    session, _ = _session()

    results = session.run(once=True)

    assert len(results) == 1


# --- 4. the key probe reads the keyboard and never writes to it --------------------


def test_the_probe_only_queries_keyboard_state() -> None:
    """GetAsyncKeyState asks what the keyboard is doing. It synthesises nothing.

    That is why this path needs no actuation consent: reading the key the user
    is physically holding is not input injection, and nothing here appears in
    the action catalogue.
    """
    calls: list[int] = []

    class FakeUser32:
        def GetAsyncKeyState(self, code: int) -> int:
            calls.append(code)
            return 0x8000 if code == KEY_CODES["space"] else 0

    probe = WindowsKeyProbe(user32=FakeUser32())

    assert probe.is_down("space") is True
    assert probe.is_down("f8") is False
    assert calls == [KEY_CODES["space"], KEY_CODES["f8"]]


def test_the_probe_ignores_the_pressed_since_last_call_bit() -> None:
    """The low bit means "was pressed at some point", which is not the question."""

    class StaleBitOnly:
        def GetAsyncKeyState(self, code: int) -> int:
            return 0x0001

    assert WindowsKeyProbe(user32=StaleBitOnly()).is_down("space") is False


def test_an_unknown_key_is_never_down() -> None:
    class AlwaysDown:
        def GetAsyncKeyState(self, code: int) -> int:
            return 0x8000

    assert WindowsKeyProbe(user32=AlwaysDown()).is_down("menu") is False


def test_the_offered_keys_do_not_type_anything_or_are_function_keys() -> None:
    """Holding the key must not flood whatever has focus with characters."""
    assert set(KEY_CODES) == {"space", "ctrl", "shift", "alt", "f8", "f9", "f10"}


# --- 5. the command exists and is reachable ----------------------------------------


def test_the_command_is_registered_under_grandpa_voice() -> None:
    """The documented push-to-talk path was browser-only, with no command."""
    from grandpa.cli.voice_cmd import voice

    assert "push-to-talk" in voice.commands


def test_the_command_records_for_the_maximum_hold_not_the_phrase_limit() -> None:
    """``duration_seconds`` caps the recorder independently of the VAD."""
    import inspect

    from grandpa.cli import voice_cmd

    source = inspect.getsource(voice_cmd.push_to_talk.callback)
    assert "duration_seconds=MAXIMUM_HOLD_SECONDS" in source
    assert "hold_to_talk_vad_config" in source
    assert MAXIMUM_HOLD_SECONDS >= 30.0
