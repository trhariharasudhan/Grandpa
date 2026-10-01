"""Push-to-talk must reach a transcript without passing a second speech gate.

A live hold of 3.6s on SPACE captured audio, the upstream detector accepted it,
and then this happened:

    push_to_talk.py:223   transcript = self.transcriber.transcribe(audio)
    speech_to_text.py:47  result = self._engine.listen(
    speech_input.py:91    result = self._transcribe_audio(
    speech_input.py:220   raise VoiceRecognitionError(
                            "No speech was detected in the audio.")

There were four gates between the captured audio and the transcript, stacked,
each able to empty it, and the last two able to raise:

1. Whisper's own ``no_speech_threshold`` 0.5, ``log_prob_threshold`` -0.85 and
   ``compression_ratio_threshold`` 2.4, passed into ``model.transcribe``. Two of
   those are stricter than faster-whisper's own defaults of 0.6 and -1.0.
2. a hand-rolled post-decode filter dropping any segment with
   ``no_speech_prob > 0.45 or avg_logprob < -0.85`` -- a second, *stricter* copy
   of the first two, so a segment Whisper decided to keep is dropped anyway.
3. ``_is_hallucinated_repetition``, which empties a degenerate loop.
4. ``speech_input`` raising ``VoiceRecognitionError`` on empty text, and
   ``speech_to_text`` raising it again.

It is not webrtcvad -- ``vad_filter`` is False -- and there is no duration
minimum. It is Whisper's own no-speech estimate, plus a stricter duplicate of
it, turned into an exception.

The normal voice path goes through every one of these too, which this file
asserts, because that is the part that matters beyond push-to-talk.

These tests drive the real ``SpeechInputEngine``, ``FasterWhisperSpeechToText``
and ``PushToTalkSession`` with a stub backend standing in for Whisper, so the
gates under test are the production ones. The audio guard stays armed: no
microphone is opened and no model is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.speech._stubs import Segment, TranscriptionResult
from grandpa.speech.faster_whisper import build_transcription_options
from grandpa.voice.errors import VoiceRecognitionError
from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.push_to_talk import PushToTalkSession, hold_to_talk_vad_config
from grandpa.voice.speech_input import SpeechInputEngine
from grandpa.voice.speech_to_text import FasterWhisperSpeechToText
from grandpa.voice.vad import VoiceActivityDetector

pytestmark = pytest.mark.core

CHUNK = 0.1


# --- a stub standing in for Whisper, recording how it was called -----------------


@dataclass
class StubSegment:
    text: str
    start: float = 0.0
    end: float = 1.0
    no_speech_prob: float = 0.1
    avg_logprob: float = -0.3
    compression_ratio: float = 1.2


@dataclass
class StubInfo:
    language: str = "en"
    language_probability: float = 0.98
    duration: float = 3.6


@dataclass
class StubModel:
    segments: list[StubSegment]
    seen_options: list[dict[str, Any]] = field(default_factory=list)

    def transcribe(self, path: str, **options: Any):
        self.seen_options.append(options)
        return iter(list(self.segments)), StubInfo()


class StubBackend:
    """The real FasterWhisperBackend decode path with the model stubbed out."""

    def __init__(self, segments: list[StubSegment]) -> None:
        from grandpa.speech.faster_whisper import FasterWhisperBackend

        self.inner = FasterWhisperBackend.__new__(FasterWhisperBackend)
        self.inner._model_size = "stub"
        self.inner.last_diagnostics = None
        self.model = StubModel(segments)
        self.inner._ensure_model = lambda: self.model  # type: ignore[method-assign]

    def transcribe(self, audio: bytes, *, format: str = "wav", language=None,
                   trust_audio: bool = False) -> TranscriptionResult:
        # No file is created: the stubbed model ignores the path, and creating a
        # real temp file here means the write guard sees an unclosed handle.
        return self.inner.transcribe_file(
            "stub-never-opened.wav", language=language, trust_audio=trust_audio
        )

    @property
    def last_diagnostics(self):
        return self.inner.last_diagnostics


def _engine(segments: list[StubSegment]) -> tuple[SpeechInputEngine, StubBackend]:
    backend = StubBackend(segments)
    engine = SpeechInputEngine()
    engine._backend = backend
    return engine, backend


def _stt(segments: list[StubSegment]) -> tuple[FasterWhisperSpeechToText, StubBackend]:
    engine, backend = _engine(segments)
    return FasterWhisperSpeechToText(engine=engine), backend


def _held_for(seconds: float):
    """A clock reading 0.0 once, then ``seconds`` forever.

    The key watcher runs on its own thread and calls the clock an unpredictable
    number of times, so a scripted list of readings is consumed
    non-deterministically and a hold measures as a tap. This is deterministic
    whatever order the two threads interleave in.
    """
    calls: list[int] = []

    def clock() -> float:
        calls.append(1)
        return 0.0 if len(calls) == 1 else seconds

    return clock


def _audio(seconds: float = 3.6) -> CapturedAudio:
    return CapturedAudio(
        data=b"RIFF" + b"\x00" * 512,
        captured_frame_count=int(16_000 * seconds),
        rms_level=1200.0,
        speech_detected=True,
        finalization_reason="cancelled",
    )


#: A segment Whisper kept -- 0.47 is under its own 0.5 threshold -- that the
#: project's stricter 0.45 filter drops. The exact shape of the live failure.
KEPT_BY_WHISPER_DROPPED_BY_US = StubSegment(
    text=" open notepad", no_speech_prob=0.47, avg_logprob=-0.4
)
CLEAN = StubSegment(text=" open notepad", no_speech_prob=0.1, avg_logprob=-0.3)


# --- 1. the gate exists, and the normal path goes through it ----------------------


def test_the_normal_voice_path_drops_a_segment_whisper_kept() -> None:
    """The double-gating, demonstrated. 0.47 passes Whisper's 0.5 and fails 0.45."""
    stt, _ = _stt([KEPT_BY_WHISPER_DROPPED_BY_US])

    with pytest.raises(VoiceRecognitionError):
        stt.transcribe(_audio())


def test_and_it_raises_rather_than_returning_empty() -> None:
    """Which is how a traceback reached the top level of a CLI command."""
    stt, _ = _stt([])

    with pytest.raises(VoiceRecognitionError):
        stt.transcribe(_audio())


def test_the_normal_path_still_applies_every_threshold() -> None:
    """Unchanged by this commit, asserted so a future relaxation is deliberate."""
    options = build_transcription_options("en")

    assert options["no_speech_threshold"] == 0.5
    assert options["log_prob_threshold"] == -0.85
    assert options["compression_ratio_threshold"] == 2.4
    assert options["vad_filter"] is False, "it is not webrtcvad"


# --- 2. trusted audio passes through none of it -----------------------------------


def test_trusted_audio_keeps_the_segment_the_filter_would_drop() -> None:
    stt, _ = _stt([KEPT_BY_WHISPER_DROPPED_BY_US])

    outcome = stt.transcribe_trusted(_audio())

    assert outcome.text == "open notepad"
    assert outcome.reason == ""
    assert outcome.segments_dropped == 0


def test_trusted_audio_disables_whispers_own_suppression_too() -> None:
    """All three are Optional[float] in faster-whisper; None disables each."""
    stt, backend = _stt([CLEAN])

    stt.transcribe_trusted(_audio())

    options = backend.model.seen_options[-1]
    assert options["no_speech_threshold"] is None
    assert options["log_prob_threshold"] is None
    assert options["compression_ratio_threshold"] is None
    # The decode itself is otherwise identical.
    assert options["beam_size"] == 1
    assert options["vad_filter"] is False


def test_an_empty_trusted_transcript_is_an_answer_not_an_exception() -> None:
    stt, _ = _stt([])

    outcome = stt.transcribe_trusted(_audio())

    assert outcome.text == ""
    assert outcome.reason == "no_segments"
    assert "decoded no speech" in outcome.explanation


def test_an_empty_result_names_which_gate_emptied_it() -> None:
    """An empty transcript used to be indistinguishable from its causes."""
    stt, _ = _stt([StubSegment(text=" new" * 40, no_speech_prob=0.1)])

    outcome = stt.transcribe_trusted(_audio())

    assert outcome.text == ""
    assert outcome.reason == "repetition_filtered", (
        "the repetition filter is deliberately still in force for trusted audio"
    )
    assert "repetition loop" in outcome.explanation


def test_the_repetition_filter_is_the_only_gate_trusted_audio_keeps() -> None:
    """It judges a decoder failure, not whether the audio contained speech."""
    stt, _ = _stt([StubSegment(text=" open notepad please", no_speech_prob=0.99,
                               avg_logprob=-3.0)])

    outcome = stt.transcribe_trusted(_audio())

    assert outcome.text == "open notepad please", (
        "no confidence number may refuse audio the user explicitly recorded"
    )


# --- 3. end to end: the detector accepts it and a transcript comes back -----------


def test_push_to_talk_reaches_a_transcript_end_to_end() -> None:
    """Synthetic audio the upstream detector accepts, through the real stack.

    The detector is the one push-to-talk ships with, the transcriber is the
    production ``FasterWhisperSpeechToText`` over the production decode path,
    and the only stub is the model itself. Nothing between the hold and the
    transcript can refuse the audio.
    """
    # First: the upstream detector accepts this audio, including digital silence.
    detector = VoiceActivityDetector(hold_to_talk_vad_config())
    for level in (0.0, 900.0, 40.0, 1500.0, 0.0):
        assert detector.observe(level, CHUNK) is False
    assert detector.speech_started is True

    # Then: the same audio reaches a transcript, through the segment the normal
    # path would have dropped.
    stt, _ = _stt([KEPT_BY_WHISPER_DROPPED_BY_US])

    responses: list[str] = []
    lines: list[str] = []

    class Capture:
        last_warning = None
        device = 9

        def capture(self, stop_event=None, on_speech_start=None):
            if stop_event is not None:
                stop_event.wait(timeout=5.0)
            return _audio()

        def close(self) -> None:
            pass

    class Probe:
        def __init__(self) -> None:
            self.script = [True, True, False]

        def is_down(self, key: str) -> bool:
            return self.script.pop(0) if self.script else False

    class Responder:
        def handle_user_input(self, text: str):
            responses.append(text)

            @dataclass
            class R:
                text: str

            return R("Opening Notepad.")

    session = PushToTalkSession(
        capture=Capture(),
        transcriber=stt,
        probe=Probe(),
        responder=Responder(),
        echo=lines.append,
        sleep=lambda _s: None,
        clock=_held_for(3.6),
    )

    result = session.run_once()

    assert result is not None
    assert result.transcript == "open notepad", lines
    assert responses == ["open notepad"], "the transcript must reach the responder"
    assert not any("could not understand" in line.lower() for line in lines)


def test_a_genuinely_empty_hold_says_so_plainly_and_does_not_raise() -> None:
    """The user's instruction: say so plainly, do not raise."""
    stt, _ = _stt([])
    lines: list[str] = []

    class Capture:
        last_warning = None
        device = 9

        def capture(self, stop_event=None, on_speech_start=None):
            if stop_event is not None:
                stop_event.wait(timeout=5.0)
            return _audio()

        def close(self) -> None:
            pass

    class Probe:
        def __init__(self) -> None:
            self.script = [True, False]

        def is_down(self, key: str) -> bool:
            return self.script.pop(0) if self.script else False

    session = PushToTalkSession(
        capture=Capture(),
        transcriber=stt,
        probe=Probe(),
        echo=lines.append,
        sleep=lambda _s: None,
        clock=_held_for(3.6),
    )

    result = session.run_once()

    assert result is not None
    assert result.reason == "empty_transcript"
    assert any("Nothing recognisable" in line for line in lines)
    assert any("decoded no speech" in line for line in lines), lines


def test_a_transcriber_that_still_raises_is_caught_not_propagated() -> None:
    """Another backend, or a double, must not produce a traceback either."""
    lines: list[str] = []

    class Raising:
        def transcribe(self, audio):
            raise VoiceRecognitionError()

    class Capture:
        last_warning = None
        device = 9

        def capture(self, stop_event=None, on_speech_start=None):
            if stop_event is not None:
                stop_event.wait(timeout=5.0)
            return _audio()

        def close(self) -> None:
            pass

    class Probe:
        def __init__(self) -> None:
            self.script = [True, False]

        def is_down(self, key: str) -> bool:
            return self.script.pop(0) if self.script else False

    session = PushToTalkSession(
        capture=Capture(),
        transcriber=Raising(),
        probe=Probe(),
        echo=lines.append,
        sleep=lambda _s: None,
        clock=_held_for(3.6),
    )

    result = session.run_once()

    assert result is not None
    assert result.reason == "empty_transcript"
    assert any("could not understand" in line.lower() for line in lines)
