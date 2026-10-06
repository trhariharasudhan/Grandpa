"""Two live accuracy runs produced unusable numbers. Four separate causes.

    Run 1, base.en:  model.bin downloaded 145 MB over 19s DURING the first
                     prompt; "Hello" heard as "Go, go."; phrases 2 and 3 heard
                     nothing; final WER 1.167 on 3 scored phrases.
    Run 2, small.en: 484 MB downloaded during the prompt; "Hello" returned a
                     40x repetition of the user's own name; 92 errors, 91 of
                     them insertions; final WER 92.000 on 1 phrase.

Neither number described recognition. This file pins each cause separately.
"""

from __future__ import annotations

import pytest

from grandpa.speech.faster_whisper import (
    _MIN_UNIQUE_RATIO,
    _MIN_VARIETY_WORDS,
    _is_hallucinated_repetition,
    build_transcription_options,
)
from grandpa.voice.accuracy import (
    CAPTURE_FAILURES,
    MODEL_DOWNLOAD_MB,
    AccuracyReport,
    CaptureFailure,
    PhraseScore,
    quiet_model_downloads,
    score_phrase,
    warm_transcriber,
)

pytestmark = pytest.mark.core

NAME = "Hari Hara Sudhan"


def _score(reference: str, actual: str) -> PhraseScore:
    substitutions, deletions, insertions, words = score_phrase(reference, actual)
    return PhraseScore(
        reference=reference,
        actual=actual,
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        reference_words=words,
    )


# --- BUG 1: the model must be loaded before the first prompt ----------------------


def test_the_command_warms_the_model_before_showing_a_phrase() -> None:
    """Checked on the source, because the ordering is the whole bug.

    The model was fetched and loaded lazily on the first transcription, which
    happened after "Hold SPACE and read it" was printed -- so the first phrase
    was spoken into a transcriber that did not exist yet, and HuggingFace drew
    progress bars over the prompt while the user was reading it.
    """
    import inspect

    from grandpa.cli import voice_cmd

    source = inspect.getsource(voice_cmd.accuracy_test.callback)
    warm_at = source.index("warm_transcriber(")
    prompt_at = source.index("Read this:")

    assert warm_at < prompt_at, (
        "the model is still loaded after the first phrase is shown"
    )
    assert "quiet_model_downloads()" in source
    assert source.index("quiet_model_downloads()") < warm_at


def test_the_wait_is_named_with_a_size_before_it_starts() -> None:
    import inspect

    from grandpa.cli import voice_cmd

    source = inspect.getsource(voice_cmd.accuracy_test.callback)

    assert "MODEL_DOWNLOAD_MB" in source
    assert "Nothing is recorded until this finishes" in source
    # And it distinguishes a download from a load, because "about 484 MB" is
    # alarming when the file is already on disk.
    assert "model_is_cached" in source
    assert "already downloaded" in source
    assert MODEL_DOWNLOAD_MB["base.en"] == 145, "the size the user saw downloaded"
    assert MODEL_DOWNLOAD_MB["small.en"] == 484


def test_progress_bars_are_disabled_by_the_documented_switch() -> None:
    import os

    quiet_model_downloads()

    assert os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS") == "1"


def test_warming_reports_failure_instead_of_raising() -> None:
    """A missing model must be a sentence, not a traceback mid-prompt."""

    class Exploding:
        class _engine:
            @staticmethod
            def _get_backend():
                raise RuntimeError("model not found")

    ready, detail = warm_transcriber(Exploding())

    assert ready is False
    assert "model not found" in detail


def test_warming_a_transcriber_without_a_local_model_is_not_an_error() -> None:
    ready, detail = warm_transcriber(object())

    assert ready is False
    assert "no local model" in detail


# --- BUG 2: trusted audio must not free-run on the prompt -------------------------


def test_trusted_audio_keeps_a_no_speech_guard() -> None:
    """Fully open let a silent hold invent text seeded by the prompt.

    Measured on no-evidence clips: fully open, base.en returned 'The' and
    small.en "I'm going to show you how to do it."; at 0.80 with the rescue,
    both returned nothing. Real speech degraded to the reported conditions was
    kept by every candidate from 0.99 down to 0.60.
    """
    options = build_transcription_options("en", trust_audio=True)

    assert options["no_speech_threshold"] == 0.80
    assert options["log_prob_threshold"] == -1.0


def test_it_is_still_looser_than_the_automatic_path() -> None:
    """The reason the thresholds were opened at all must survive."""
    trusted = build_transcription_options("en", trust_audio=True)
    automatic = build_transcription_options("en")

    assert trusted["no_speech_threshold"] > automatic["no_speech_threshold"]


# --- BUG 3: the repetition filter missed non-tiling loops -------------------------


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("7-word unit x12", ", ".join(["My name is Hari Hara Sudhan Hari"] * 12)),
        (
            "8-word unit x10",
            ", ".join(["Hari Hara Sudhan Hari Hara Sudhan Hari Hara"] * 10),
        ),
        ("stray word every 7th", " ".join((["hari", "hara", "sudhan"] * 2 + ["the"]) * 13)),
        (
            "irregular insertions",
            " ".join((["hari", "hara", "sudhan"] * 3 + ["and", "the"]) * 8),
        ),
        ("the reported shape", ", ".join([NAME] * 30) + ", Hari Hara"),
    ],
)
def test_loops_that_do_not_tile_are_now_caught(label: str, text: str) -> None:
    """The period test chunks at a fixed stride, so these were invisible to it.

    All of them have three to six distinct words in eighty-odd, which is not a
    borderline call.
    """
    assert _is_hallucinated_repetition(text) is True, label


def test_the_variety_rule_needs_enough_words_to_mean_anything() -> None:
    """"no no no" is three words and is real speech."""
    assert _MIN_VARIETY_WORDS == 20
    assert _is_hallucinated_repetition("no no no") is False
    assert _is_hallucinated_repetition("open notepad open notepad open notepad") is (
        False
    )


def test_the_threshold_sits_between_the_measured_populations() -> None:
    """The usable band is narrow and 0.25 was outside it.

    Counting only texts of 20+ words: the highest ratio among loops is 0.111
    and the lowest among real speech is 0.233 -- a ten-word sentence said three
    times, which the existing corpus treats as real. 0.25 discarded that, so it
    was replaced with 0.16, the geometric middle of the band.
    """
    assert _MIN_UNIQUE_RATIO == 0.16
    assert 0.111 < _MIN_UNIQUE_RATIO <= 0.233


def test_a_sentence_said_three_times_is_not_a_loop() -> None:
    """The case that moved the threshold off 0.25.

    Thirty words with seven distinct ones scores 0.233. A person repeating
    themselves is not a decoder failure, and the existing corpus already keeps
    shorter triple-repeats.
    """
    repeated = " ".join(["add milk and bread and eggs and butter and cheese"] * 3)

    assert _is_hallucinated_repetition(repeated) is False


def test_a_varied_list_is_kept() -> None:
    """Real speech can repeat a word heavily without repeating a phrase."""
    shopping = (
        "add milk and bread and eggs and butter and cheese and ham and jam "
        "and tea and coffee"
    )

    assert _is_hallucinated_repetition(shopping) is False


# --- BUG 4: a failed recording is not a word error --------------------------------


def test_capture_failures_are_not_scored() -> None:
    """Two failed holds became full word errors and produced WER 1.167."""
    report = AccuracyReport(
        requested=10,
        scores=[_score("Hello", "Hello")],
        failures=[
            CaptureFailure(reference="Hari Hara Sudhan", reason="no_audio"),
            CaptureFailure(reference="Open Notepad", reason="no_audio"),
        ],
    )

    assert report.total_words == 1
    assert report.total_errors == 0
    assert report.corpus_wer == 0.0


def test_the_failure_reasons_are_the_ones_the_session_reports() -> None:
    from grandpa.voice.push_to_talk import PushToTalkSession  # noqa: F401

    assert CAPTURE_FAILURES == {"no_audio", "too_short", "cancelled"}


def test_each_failure_says_what_to_do() -> None:
    assert "doctor" in CaptureFailure(reference="x", reason="no_audio").advice
    assert "hold it down" in CaptureFailure(reference="x", reason="too_short").advice
    assert CaptureFailure(reference="x", reason="weird").advice


def test_an_empty_transcript_is_still_scored_because_it_is_a_real_result() -> None:
    """Audio captured and nothing recognised is a recognition failure.

    Distinct from the microphone delivering nothing, which is not.
    """
    score = _score("Open Notepad", "")

    assert score.deletions == 2
    assert score.wer == 1.0


# --- the run must say when its number is not comparable ---------------------------


def test_the_live_run_shape_is_flagged_as_not_comparable() -> None:
    """One scored phrase of ten requested, with two recording failures."""
    report = AccuracyReport(
        requested=10,
        scores=[_score("Hello", "Go, go.")],
        failures=[
            CaptureFailure(reference="Hari Hara Sudhan", reason="no_audio"),
            CaptureFailure(reference="Open Notepad", reason="no_audio"),
        ],
    )

    assert report.is_representative is False


def test_a_complete_run_is_comparable() -> None:
    report = AccuracyReport(
        requested=10,
        scores=[_score(f"phrase {n}", f"phrase {n}") for n in range(10)],
    )

    assert report.is_representative is True


def test_a_deliberately_short_run_is_comparable() -> None:
    """--count 3 is a legitimate request, and three of three is complete.

    An absolute floor of five scored phrases rejected this, which would have
    made --count useless.
    """
    report = AccuracyReport(
        requested=3,
        scores=[_score(f"phrase {n}", f"phrase {n}") for n in range(3)],
    )

    assert report.is_representative is True


def test_failures_outnumbering_scores_is_never_comparable() -> None:
    report = AccuracyReport(
        requested=2,
        scores=[_score("Hello", "Hello")],
        failures=[CaptureFailure(reference="x", reason="no_audio")],
    )

    assert report.is_representative is False


def test_a_quality_verdict_is_still_given_for_a_short_run() -> None:
    """Comparability and quality are separate questions.

    Conflating them meant a deliberate --count 3 run got no verdict at all.
    """
    report = AccuracyReport(requested=1, scores=[_score("Hello", "Hello")])

    assert "Good" in report.verdict()


def test_an_all_failures_run_says_it_measured_nothing() -> None:
    report = AccuracyReport(
        requested=10,
        failures=[CaptureFailure(reference="Hello", reason="no_audio")],
    )

    verdict = report.verdict()
    assert "Nothing was scored" in verdict
    assert "says nothing about" in verdict
    assert report.is_representative is False
