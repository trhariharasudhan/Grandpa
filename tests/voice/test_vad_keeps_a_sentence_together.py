"""A mid-sentence breath must not end the utterance, and a fragment must not
reach the model.

From a live run, three captures with the debug line on:

    1  capture 4.88s  voiced 1.40s  rms 2276.5  -> "could not understand"
    2  capture 9.19s  voiced 0.50s  rms  176.4  -> 100 words of "new, new, new"
    3  capture 4.19s  voiced 0.70s  rms  234.4  -> 100 words of "new, new, new"

Three mechanics had to be established before any threshold moved, because each
changes what those numbers mean:

* **trailing silence is consecutive, not cumulative.** A speech chunk resets it,
  so 1.2s of quiet broken by single loud chunks never finalises. With
  ``silence_seconds`` at 0.55 and a 0.1s chunk it takes six chunks -- 0.6s -- of
  uninterrupted quiet to end an utterance. That is inside an ordinary
  mid-sentence pause.
* **voiced_duration is a sum, not a span.** It counts chunks above the threshold
  wherever they fall. A 3.0s sentence of 0.3s-loud / 0.2s-quiet measures 1.80s
  voiced, so "voiced 1.40s" is not a 1.4s utterance.
* **the reported rms was the whole buffer**, which holds 0.3s of pre-roll and the
  trailing silence. Solving backwards, capture 2's speech chunks averaged ~289
  and capture 3's ~353 -- 1.6x and 2.0x the threshold. They cleared it, barely.
  Capture 1's averaged ~2949.

So captures 2 and 3 were never usable speech, and capture 1 was loud speech cut
short. The fix is therefore two separate things: keep the sentence together, and
refuse to transcribe what is both short and quiet.

Levels here are the ones the live run measured, not ideal ones, and the sentences
are bursty -- loud syllables with quiet gaps -- because continuous tone would not
exercise the thing that broke.
"""

from __future__ import annotations

import pytest

from grandpa.voice.cli_session import (
    MIN_TRANSCRIBE_SPEECH_RMS,
    MIN_TRANSCRIBE_VOICED_SECONDS,
    _too_thin_to_transcribe,
)
from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector

pytestmark = pytest.mark.core

CHUNK = 0.1

# --- measured in the live run ----------------------------------------------------
LOUD_SPEECH = 2949.0  # capture 1's implied speech level
THIN_SPEECH = 289.0  # capture 2's
FLOOR = 60.0

SHIPPED = VoiceActivityConfig(
    minimum_rms=180.0,
    minimum_speech_seconds=0.25,
    silence_seconds=0.80,
    maximum_utterance_seconds=12.0,
)

#: 2.8s of bursty speech with a 0.6s breath in the middle -- the pause length that
#: used to cut a sentence in half.
SENTENCE = (
    [LOUD_SPEECH] * 6
    + [FLOOR] * 6
    + [LOUD_SPEECH] * 8
    + [FLOOR] * 3
    + [LOUD_SPEECH] * 5
)


def _run(
    config: VoiceActivityConfig, levels: list[float]
) -> tuple[float, VoiceActivityDetector]:
    """Returns the span at which the utterance finalised, or the whole length."""
    detector = VoiceActivityDetector(config)
    for index, level in enumerate(levels):
        if detector.observe(level, CHUNK):
            return (index + 1) * CHUNK, detector
    return len(levels) * CHUNK, detector


# --- 1. the sentence survives -----------------------------------------------------


def test_a_breath_in_the_middle_no_longer_ends_the_sentence() -> None:
    span, detector = _run(SHIPPED, SENTENCE)

    assert span == pytest.approx(len(SENTENCE) * CHUNK, abs=0.01), (
        f"the sentence was cut at {span:.1f}s of {len(SENTENCE) * CHUNK:.1f}s"
    )
    assert detector.finalization_reason != "silence_timeout"


def test_the_old_value_cut_it_in_half_and_this_is_why_it_changed() -> None:
    """The measurement the new default rests on, kept executable."""
    old = VoiceActivityConfig(
        minimum_rms=180.0,
        minimum_speech_seconds=0.25,
        silence_seconds=0.55,
        maximum_utterance_seconds=12.0,
    )

    span, _ = _run(old, SENTENCE)

    assert span < len(SENTENCE) * CHUNK, (
        "0.55 no longer truncates the sentence, so the reason for 0.80 has "
        "changed and this file needs rereading"
    )
    assert span == pytest.approx(1.2, abs=0.01)


@pytest.mark.parametrize("silence_seconds", [0.70, 0.80, 1.00])
def test_every_value_at_or_above_the_measured_minimum_holds_it_together(
    silence_seconds: float,
) -> None:
    config = VoiceActivityConfig(
        minimum_rms=180.0,
        minimum_speech_seconds=0.25,
        silence_seconds=silence_seconds,
        maximum_utterance_seconds=12.0,
    )

    span, _ = _run(config, SENTENCE)

    assert span == pytest.approx(len(SENTENCE) * CHUNK, abs=0.01)


def test_the_shipped_default_is_the_measured_one() -> None:
    """Both places, because only one of them reaches the CLI.

    VoiceActivityConfig's own default is not what runs: the session builds the
    config from voice.config, so changing only the dataclass would have fixed
    nothing a user sees.
    """
    from grandpa.voice.config import load_voice_assistant_config

    assert VoiceActivityConfig().silence_seconds == 0.80
    assert load_voice_assistant_config().silence_timeout_seconds == 0.80


def test_speech_still_finalises_once_the_speaker_really_stops() -> None:
    """Longer, not unbounded. The utterance has to end."""
    span, detector = _run(SHIPPED, SENTENCE + [FLOOR] * 15)

    assert detector.finalization_reason == "silence_timeout"
    assert span == pytest.approx(len(SENTENCE) * CHUNK + 0.9, abs=0.11), span


# --- 2. the speech window is measured separately ----------------------------------


def test_the_speech_window_rms_is_not_the_buffer_rms() -> None:
    """The number that made the log misleading.

    A capture whose speech chunks are all at 289 reports a whole-buffer rms far
    below that, because the buffer also holds pre-roll and trailing silence.
    Reading 176 against a threshold of 180 suggested speech never crossed it.
    """
    _, detector = _run(SHIPPED, [FLOOR] * 3 + [THIN_SPEECH] * 5 + [FLOOR] * 9)

    assert detector.speech_window_rms == pytest.approx(THIN_SPEECH, abs=1.0)
    assert detector.speech_active_seconds == pytest.approx(0.5, abs=0.01)
    # The floor it was compared against, reported so the threshold is explicable.
    assert detector.noise_floor < THIN_SPEECH
    assert detector.current_threshold == pytest.approx(180.0, abs=1.0)


def test_speech_window_rms_is_zero_when_nothing_cleared_the_threshold() -> None:
    _, detector = _run(SHIPPED, [FLOOR] * 20)

    assert detector.speech_window_rms == 0.0
    assert detector.speech_started is False


def test_why_speech_detected_fired_at_a_reported_rms_of_176() -> None:
    """Both halves of the explanation, as an executable statement.

    The threshold was the 180 minimum rather than the 299 computed from the
    microphone test, because that test's noise floor was 119.7 and a quiet
    moment's is far lower. And the 176 was the diluted buffer, not the speech.
    """
    _, detector = _run(SHIPPED, [FLOOR] * 3 + [THIN_SPEECH] * 5 + [FLOOR] * 9)

    assert detector.speech_started is True, "speech must have been detected"
    assert detector.current_threshold == pytest.approx(180.0, abs=1.0)
    assert THIN_SPEECH > detector.current_threshold
    # Yet the whole-buffer rms of that same capture is below the threshold.
    import math

    levels = [FLOOR] * 3 + [THIN_SPEECH] * 5 + [FLOOR] * 9
    buffer_rms = math.sqrt(sum(v * v for v in levels) / len(levels))
    assert buffer_rms < detector.current_threshold, buffer_rms


# --- 3. the pre-transcription gate -------------------------------------------------


@pytest.mark.parametrize(
    ("voiced", "speech_rms", "label"),
    [
        (0.50, 289.0, "live capture 2"),
        (0.70, 353.0, "live capture 3"),
        (0.30, 200.0, "a click"),
        (0.90, 499.0, "just inside both bounds"),
    ],
)
def test_short_and_quiet_is_not_transcribed(
    voiced: float, speech_rms: float, label: str
) -> None:
    """The captures that produced a hundred hallucinated words each."""
    assert _too_thin_to_transcribe(voiced, speech_rms) is True, label


@pytest.mark.parametrize(
    ("voiced", "speech_rms", "label"),
    [
        (1.40, 2949.0, "live capture 1 -- real speech"),
        (0.30, 2500.0, "a clipped but audible 'yes'"),
        (0.20, 3000.0, "a short loud 'stop'"),
        (1.50, 200.0, "a long quiet mumble -- let the model judge it"),
        (1.00, 499.0, "long enough, even though quiet"),
        (0.90, 500.0, "loud enough, even though short"),
    ],
)
def test_anything_short_but_loud_or_long_but_quiet_still_goes_through(
    voiced: float, speech_rms: float, label: str
) -> None:
    """Both conditions, never either alone -- which is the whole design."""
    assert _too_thin_to_transcribe(voiced, speech_rms) is False, label


def test_the_gate_thresholds_are_stated() -> None:
    assert MIN_TRANSCRIBE_VOICED_SECONDS == 1.0
    assert MIN_TRANSCRIBE_SPEECH_RMS == 500.0


def test_the_thresholds_sit_between_the_measured_bad_and_good_captures() -> None:
    """The numbers are not round guesses; they bracket the live evidence."""
    # The two captures that hallucinated.
    for voiced, speech_rms in ((0.50, 289.0), (0.70, 353.0)):
        assert voiced < MIN_TRANSCRIBE_VOICED_SECONDS
        assert speech_rms < MIN_TRANSCRIBE_SPEECH_RMS
    # The capture that was real speech.
    assert 1.40 >= MIN_TRANSCRIBE_VOICED_SECONDS
    assert 2949.0 > MIN_TRANSCRIBE_SPEECH_RMS
    # And the gate sits clear of the noise floor it has to distinguish from.
    assert MIN_TRANSCRIBE_SPEECH_RMS > 353.0 * 1.4
