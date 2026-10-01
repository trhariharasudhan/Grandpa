"""Speech above the threshold must be detected as speech.

The live log reported, across seven consecutive captures:

    max_rms 640.9 .. 2994.6   threshold 180.0   reason=no_speech_timeout

Every one of those says the loudest chunk was between 3.5x and 16x the level a
chunk had to reach, and every one ended by giving up on hearing anything. Two
separate mechanisms produced that, and this file pins both.

**Onset required consecutive chunks.** ``_speech_seconds`` accumulated while
chunks were above the threshold and was set back to zero by any chunk that was
not, so 0.25s of speech meant three unbroken 0.1s chunks. Ordinary speech does
not supply them: the gap between syllables, the stop before a plosive and the
attack of the first word each dip below for a chunk at a time. Measured before
the fix, against a threshold of 180 with loud chunks at 3000:

    1 consecutive chunk          -> not started
    2 consecutive chunks         -> not started
    3 consecutive chunks         -> started
    alternating loud/quiet x40   -> NEVER started, max_rms 3000
    2 loud 1 quiet, repeated x13 -> NEVER started, max_rms 3000

**max_rms is not the compared value.** It is the loudest single chunk over the
whole capture, and the detector never compares it to anything. Reporting it
beside the threshold invited exactly the reading the user made -- that something
loud enough had been heard and rejected. What is compared is each chunk's own
RMS, and what is required is a quantity of such chunks.

**The floor could absorb speech.** Every sub-threshold chunk fed the noise
estimate, so a speech chunk below ``floor x 2.5`` raised the floor, which raised
the threshold, which made the next speech chunk likelier to be called noise.
The live log walked 180.0 -> 188.9 -> 226.1 -> 291.8 -> 419.9 -> 476.9 -> 500.4
in one session.

Levels here are the ones the live log measured.
"""

from __future__ import annotations

import pytest

from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector

pytestmark = pytest.mark.core

CHUNK = 0.1

# --- straight from the live log ---------------------------------------------------
QUIETEST_SPEECH = 640.9
LOUDEST_SPEECH = 2994.6
LIVE_THRESHOLD = 180.0
ROOM_NOISE = 100.0

SHIPPED = VoiceActivityConfig(
    minimum_rms=LIVE_THRESHOLD,
    minimum_speech_seconds=0.25,
    silence_seconds=0.80,
    maximum_utterance_seconds=12.0,
    silence_before_speech_seconds=8.0,
)


def _run(levels: list[float], config: VoiceActivityConfig = SHIPPED):
    detector = VoiceActivityDetector(config)
    onset_chunk = None
    for index, level in enumerate(levels):
        detector.observe(level, CHUNK)
        if detector.speech_started and onset_chunk is None:
            onset_chunk = index + 1
    return detector, onset_chunk


# --- 1. the shapes the live log produced must now be heard -------------------------


@pytest.mark.parametrize(
    ("label", "pattern"),
    [
        ("alternating loud/quiet", [LOUDEST_SPEECH, ROOM_NOISE] * 20),
        ("2 loud, 1 quiet, repeated", ([LOUDEST_SPEECH] * 2 + [ROOM_NOISE]) * 13),
        ("3 loud, 1 quiet, repeated", ([LOUDEST_SPEECH] * 3 + [ROOM_NOISE]) * 10),
        ("the quietest live speech", ([QUIETEST_SPEECH] * 2 + [ROOM_NOISE]) * 13),
        ("the loudest live speech", ([LOUDEST_SPEECH] * 2 + [ROOM_NOISE]) * 13),
    ],
)
def test_bursty_speech_above_the_threshold_is_heard(
    label: str, pattern: list[float]
) -> None:
    """None of these started before the fix, every max_rms far above threshold."""
    detector, onset_chunk = _run(pattern[:81])

    assert detector.speech_started is True, (
        f"{label}: max_rms {detector.max_rms:.1f} against threshold "
        f"{detector.current_threshold:.1f} and still no speech"
    )
    assert detector.finalization_reason != "no_speech_timeout"
    assert onset_chunk is not None and onset_chunk <= 6, onset_chunk


def test_the_old_consecutive_rule_is_what_broke_it() -> None:
    """Kept executable: a zero-length window restores the old behaviour.

    With no window to accumulate in, each chunk stands alone and 0.25s can
    never be reached, which is the degenerate end of the rule that required
    three unbroken chunks.
    """
    consecutive_only = VoiceActivityConfig(
        minimum_rms=LIVE_THRESHOLD,
        minimum_speech_seconds=0.25,
        onset_window_seconds=0.0,
        silence_seconds=0.80,
        maximum_utterance_seconds=12.0,
        silence_before_speech_seconds=8.0,
    )

    detector, _ = _run([LOUDEST_SPEECH, ROOM_NOISE] * 20, consecutive_only)

    assert detector.speech_started is False
    assert detector.max_rms == pytest.approx(LOUDEST_SPEECH)


def test_continuous_speech_still_starts_promptly() -> None:
    """The easy case must not have regressed."""
    detector, onset_chunk = _run([LOUDEST_SPEECH] * 20)

    assert detector.speech_started is True
    assert onset_chunk == 3, "0.25s of speech is still three 0.1s chunks"
    assert detector.speech_onset_seconds == pytest.approx(0.0, abs=0.01)


# --- 2. and the things that are not speech must still be refused -------------------


@pytest.mark.parametrize(
    ("label", "pattern"),
    [
        ("a single click", [ROOM_NOISE] * 5 + [LOUDEST_SPEECH] + [ROOM_NOISE] * 20),
        ("two clicks a second apart", ([LOUDEST_SPEECH] + [ROOM_NOISE] * 10) * 4),
        ("silence", [50.0] * 40),
        ("steady noise just under the threshold", [LIVE_THRESHOLD - 1] * 40),
    ],
)
def test_what_is_not_speech_is_still_not_speech(
    label: str, pattern: list[float]
) -> None:
    detector, _ = _run(pattern[:81])

    assert detector.speech_started is False, label


def test_the_window_requires_a_real_quantity_not_a_single_loud_chunk() -> None:
    """Two loud chunks inside the window are 0.2s, still under 0.25s."""
    detector, _ = _run([LOUDEST_SPEECH] * 2 + [ROOM_NOISE] * 10)

    assert detector.speech_started is False
    # Exactly one more loud chunk in the same window does start it.
    detector_three, _ = _run([LOUDEST_SPEECH] * 2 + [ROOM_NOISE] + [LOUDEST_SPEECH])
    assert detector_three.speech_started is True


def test_the_window_is_trailing_so_old_speech_does_not_count_forever() -> None:
    """Two loud chunks now plus two a long time ago is not an onset."""
    detector, _ = _run([LOUDEST_SPEECH] * 2 + [ROOM_NOISE] * 20 + [LOUDEST_SPEECH] * 2)

    assert detector.speech_started is False


# --- 3. the noise floor can no longer include speech -------------------------------


def test_the_floor_only_learns_from_audio_that_could_not_be_speech() -> None:
    """The invariant that stops the runaway.

    Nothing at or above ``minimum_rms`` feeds the floor, so everything the floor
    is made of was below the level a chunk must reach to be speech at all.
    """
    detector = VoiceActivityDetector(SHIPPED)
    # Room noise, then speech that starts below the threshold the floor implies.
    for level in [150.0] * 6 + [400.0] * 6 + [600.0] * 6:
        detector.observe(level, CHUNK)

    assert detector.noise_floor < SHIPPED.minimum_rms
    assert detector.noise_floor == pytest.approx(150.0, abs=0.1), (
        "the 400s and 600s must not have been folded into the floor"
    )
    assert detector.speech_started is True


def test_the_floor_cannot_run_away_past_its_bound() -> None:
    """400 chunks at just under minimum_rms is the worst case available."""
    detector = VoiceActivityDetector(SHIPPED)
    for _ in range(400):
        detector.observe(SHIPPED.minimum_rms - 0.1, CHUNK)

    bound = SHIPPED.minimum_rms * SHIPPED.noise_multiplier
    assert detector.noise_floor < SHIPPED.minimum_rms
    assert detector.current_threshold < bound
    # The live log exceeded this, which is how the runaway was visible.
    assert 500.4 > bound, "the observed 500.4 is above the bound this now enforces"


def test_the_cost_of_bounding_the_floor_stated_plainly() -> None:
    """What the bound gives up, kept executable so it is not forgotten.

    The floor used to chase any sub-threshold level upward without limit, which
    is how it tracked a genuinely loud room. It no longer can: constant noise
    *above* ``minimum_rms`` is now classified as speech and starts a false
    onset, where before the floor would eventually have risen past it.

    This is the right way round for the fault being fixed. Absorption cost the
    user real sentences; a false onset costs a wasted capture that the
    short-and-quiet gate and Whisper's own no-speech probability then judge, and
    ``grandpa voice push-to-talk`` avoids entirely. It is recorded here because
    a quiet room -- the one measured, floor 30.6 -- never meets it, and a loud
    one will.
    """
    detector = VoiceActivityDetector(SHIPPED)
    for _ in range(10):
        detector.observe(SHIPPED.minimum_rms + 20.0, CHUNK)

    assert detector.speech_started is True, "a false onset, and it is accepted"
    assert detector.noise_floor == 0.0, "nothing above minimum_rms taught the floor"


def test_speech_well_above_the_floor_is_still_required() -> None:
    """The multiplier is not disabled -- a loud room still needs louder speech."""
    detector = VoiceActivityDetector(SHIPPED)
    for _ in range(20):
        detector.observe(160.0, CHUNK)

    assert detector.current_threshold == pytest.approx(400.0, abs=1.0)
    for _ in range(3):
        detector.observe(300.0, CHUNK)
    assert detector.speech_started is False, "300 is below 160 x 2.5"


# --- 4. the diagnostic must not report a number the code does not use --------------


def test_max_rms_is_documented_as_a_per_chunk_maximum() -> None:
    """It is the loudest single chunk, and nothing is ever compared to it.

    A capture can carry a very high max_rms and correctly have heard no speech,
    because one loud chunk is 0.1s and the requirement is 0.25s. That is not a
    contradiction, but reporting the two side by side read as one.
    """
    detector, _ = _run([ROOM_NOISE] * 5 + [LOUDEST_SPEECH] + [ROOM_NOISE] * 5)

    assert detector.max_rms == pytest.approx(LOUDEST_SPEECH)
    assert detector.speech_started is False
    # The quantity that governs the decision, which is reported separately.
    assert detector.speech_active_seconds == pytest.approx(CHUNK, abs=0.01)
    assert detector.speech_active_seconds < SHIPPED.minimum_speech_seconds


def test_the_onset_window_default_is_what_reaches_the_cli() -> None:
    """Neither CLI site passes it, so the dataclass default is the live value.

    ``silence_seconds`` taught this lesson the hard way: the session builds its
    config from ``voice.config``, so a field that config overrides must be
    changed in both places. ``onset_window_seconds`` is not overridden, so this
    default is the one that runs -- and this test fails if that changes silently.
    """
    import inspect

    from grandpa.voice import cli_session

    assert VoiceActivityConfig().onset_window_seconds == 0.6
    assert "onset_window_seconds" not in inspect.getsource(
        cli_session.build_voice_session
    ), "build_voice_session now sets it; assert the value it sets here too"
