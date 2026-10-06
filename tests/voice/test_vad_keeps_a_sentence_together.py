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


# --- 3. the pre-transcription gate, re-derived -------------------------------------
#
# REWRITTEN DELIBERATELY. This section used to assert a two-condition gate --
# voiced < 1.0s AND speech_rms < 500 -- and to assert that both numbers bracketed
# the live evidence. They did bracket the evidence available then, which came
# from a reference recording. They did not survive this user's microphone.
#
# What changed and why: the user reported real speech at 0.50s/250.0 and
# 0.50s/220.9 being refused, and real speech generally measuring 220-350 where
# the old threshold assumed 500+. Laid against the two captures the gate existed
# to stop -- 0.50s/289.0 and 0.70s/353.0 -- the sets overlap on both axes. An
# exhaustive search over voiced in 0.05s steps to 2.0s and RMS in 25.0 steps to
# 2000.0 finds ZERO pairs that refuse both bad captures and no real speech.
#
# So the loudness condition was removed rather than retuned, and what is left is
# a duration floor at the VAD's own minimum_speech_seconds. The tests below pin
# that property: nothing the user measured as speech is refused, and the two
# captures that hallucinated are now explicitly expected to get through, with the
# repetition filter named as the mechanism that handles them.


#: Every (voiced, speech_rms) the user has reported as real speech.
MEASURED_REAL_SPEECH = [
    (2.10, 262.7, "refused by the removed confidence filter"),
    (1.30, 268.3, "refused by the removed confidence filter"),
    (0.30, 728.9, "Whisper decoded ' Hello.'"),
    (0.50, 250.0, "refused by the old marginal gate"),
    (0.50, 220.9, "refused by the old marginal gate"),
    (1.40, 2949.0, "earlier live capture"),
]

#: The two captures that produced a hundred hallucinated words each.
MEASURED_HALLUCINATIONS = [
    (0.50, 289.0, "live capture 2"),
    (0.70, 353.0, "live capture 3"),
]


@pytest.mark.parametrize(
    ("voiced", "speech_rms", "label"),
    MEASURED_REAL_SPEECH,
    ids=[case[2] for case in MEASURED_REAL_SPEECH],
)
def test_nothing_the_user_measured_as_speech_is_refused(
    voiced: float, speech_rms: float, label: str
) -> None:
    """The requirement the old pair of thresholds failed."""
    assert _too_thin_to_transcribe(voiced, speech_rms) is False, label


@pytest.mark.parametrize(
    ("voiced", "speech_rms", "label"),
    MEASURED_HALLUCINATIONS,
    ids=[case[2] for case in MEASURED_HALLUCINATIONS],
)
def test_the_hallucinating_captures_now_reach_the_model_and_that_is_accepted(
    voiced: float, speech_rms: float, label: str
) -> None:
    """Stated as an expectation, not hidden as a regression.

    Nothing distinguishes these from real speech at 0.50s and 250.0, so refusing
    them means refusing that. The repetition filter caught both when they
    happened; it judges the decoder's output rather than guessing at the audio,
    which is the only one of the two mechanisms that can tell them apart.
    """
    assert _too_thin_to_transcribe(voiced, speech_rms) is False, label


def test_no_threshold_pair_could_have_separated_the_two_sets() -> None:
    """The search that justifies removing the condition, kept executable.

    If a future measurement makes the sets separable again, this fails and the
    decision above should be revisited rather than inherited.
    """
    candidates = [
        (voiced_bar, rms_bar)
        for voiced_bar in (step * 0.05 for step in range(1, 41))
        for rms_bar in (step * 25.0 for step in range(1, 81))
        if all(
            voiced < voiced_bar and rms < rms_bar
            for voiced, rms, _ in MEASURED_HALLUCINATIONS
        )
        and not any(
            voiced < voiced_bar and rms < rms_bar
            for voiced, rms, _ in MEASURED_REAL_SPEECH
        )
    ]

    assert candidates == [], (
        f"a separating threshold pair now exists ({candidates[:3]}), so the "
        f"reason the loudness condition was removed no longer holds"
    )


def test_the_overlap_is_on_both_axes() -> None:
    """Why no pair exists, stated as the two inequalities that cause it."""
    quietest_real = min(rms for _, rms, _ in MEASURED_REAL_SPEECH)
    loudest_bad = max(rms for _, rms, _ in MEASURED_HALLUCINATIONS)
    shortest_real = min(voiced for voiced, _, _ in MEASURED_REAL_SPEECH)
    longest_bad = max(voiced for voiced, _, _ in MEASURED_HALLUCINATIONS)

    assert quietest_real < loudest_bad, (quietest_real, loudest_bad)
    assert shortest_real < longest_bad, (shortest_real, longest_bad)


def test_the_remaining_floor_is_the_detectors_own_minimum() -> None:
    """Not a new number: the amount of speech the VAD itself requires."""
    assert MIN_TRANSCRIBE_VOICED_SECONDS == 0.25
    assert MIN_TRANSCRIBE_VOICED_SECONDS == SHIPPED.minimum_speech_seconds


def test_a_capture_below_the_detectors_own_minimum_is_refused() -> None:
    """Not vacuous: a cancelled or timed-out capture skips the false-start reset."""
    assert _too_thin_to_transcribe(0.1, 3000.0) is True
    assert _too_thin_to_transcribe(0.0, 0.0) is True
    assert _too_thin_to_transcribe(0.24, 5000.0) is True


def test_loudness_no_longer_affects_the_decision_at_all() -> None:
    """The signature still takes it; it must not change the answer."""
    for rms in (0.0, 180.0, 220.9, 500.0, 5000.0):
        assert _too_thin_to_transcribe(0.5, rms) is False
        assert _too_thin_to_transcribe(0.1, rms) is True
