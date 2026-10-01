"""The advice must match the measurement it is printed next to.

A live session printed this seven times:

    I did not hear speech on Microphone Array (device 9). Levels reached
    2994 against a threshold of 180. Try speaking louder or closer.

The level was sixteen times the threshold. "Speak louder" cannot help, and a
message that contradicts the number beside it sends the user the wrong way --
which is what three rounds of threshold tuning came out of.
"""

from __future__ import annotations

import pytest

from grandpa.voice.microphone import CapturedAudio

pytestmark = pytest.mark.core


class Recorder:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def print_error(self, message: str) -> None:
        self.errors.append(message)


def _report(**fields) -> str:
    """Drive the real reporter with a hand-built capture."""
    from grandpa.voice.cli_session import VoiceSession

    session = object.__new__(VoiceSession)
    session.presenter = Recorder()
    session._last_quiet_message = None
    audio = CapturedAudio(
        data=b"",
        device_name="Microphone Array (AMD Audio Device)",
        device_index=9,
        **fields,
    )
    session._report_quiet_capture(audio)
    return session.presenter.errors[0] if session.presenter.errors else ""


def test_a_loud_capture_is_not_told_to_be_louder() -> None:
    """The live numbers, exactly."""
    message = _report(
        chunks_read=81,
        max_chunk_rms=2994.6,
        speech_threshold=180.0,
        speech_active_seconds=0.1,
        speech_detected=False,
        finalization_reason="no_speech_timeout",
    )

    assert "louder" not in message, message
    assert "loud enough" in message
    assert "2995" in message and "180" in message  # 2994.6 at :.0f
    assert "push-to-talk" in message, "the fallback must be offered here"


def test_the_quietest_live_capture_gets_the_same_treatment() -> None:
    message = _report(
        chunks_read=81,
        max_chunk_rms=640.9,
        speech_threshold=180.0,
        speech_active_seconds=0.2,
        speech_detected=False,
        finalization_reason="no_speech_timeout",
    )

    assert "loud enough" in message
    assert "0.2s" in message, "how much held up is the number that governs"


def test_a_genuinely_quiet_capture_is_still_told_to_be_louder() -> None:
    """The old advice was right for this case and must survive."""
    message = _report(
        chunks_read=81,
        max_chunk_rms=119.0,
        speech_threshold=299.0,
        speech_detected=False,
        finalization_reason="no_speech_timeout",
    )

    assert "louder" in message
    assert "119" in message and "299" in message


def test_a_dead_device_is_still_a_different_message() -> None:
    message = _report(
        chunks_read=0,
        max_chunk_rms=0.0,
        speech_threshold=180.0,
        speech_detected=False,
        finalization_reason="no_speech_timeout",
    )

    assert "no audio" in message
    assert "louder" not in message


def test_a_silent_device_is_still_a_different_message() -> None:
    message = _report(
        chunks_read=81,
        max_chunk_rms=0.0,
        speech_threshold=180.0,
        speech_detected=False,
        finalization_reason="no_speech_timeout",
    )

    assert "silence" in message
    assert "louder" not in message
