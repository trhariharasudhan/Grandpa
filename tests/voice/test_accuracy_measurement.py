"""A number you can compare, instead of an anecdote.

Transcription quality was being judged from reports like "it said 'The top of the
game'". That cannot distinguish a regression from a bad day, and it cannot show
whether a change helped. These tests pin the scoring, because a measurement
instrument that is itself wrong is worse than none.

No microphone is opened: the scorer is pure, and the command's capture path is
tested separately in test_push_to_talk.py.
"""

from __future__ import annotations

import pytest

from grandpa.voice.accuracy import (
    DEFAULT_PHRASES,
    AccuracyReport,
    PhraseScore,
    normalise_for_scoring,
    score_phrase,
)

pytestmark = pytest.mark.core


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


# --- 1. scoring ---------------------------------------------------------------------


def test_a_perfect_transcript_scores_zero() -> None:
    score = _score("Open Notepad", "Open Notepad")

    assert score.wer == 0.0
    assert score.exact is True
    assert score.errors == 0


def test_punctuation_and_case_are_not_errors() -> None:
    """Whisper always adds a full stop. Counting it would make the number
    meaningless."""
    score = _score("What is the time", "What is the time?")

    assert score.wer == 0.0
    assert score.exact is True


def test_one_wrong_word_is_one_substitution() -> None:
    score = _score("What is the time", "What is the guy")

    assert (score.substitutions, score.deletions, score.insertions) == (1, 0, 0)
    assert score.wer == pytest.approx(0.25)


def test_a_missed_word_is_a_deletion() -> None:
    score = _score("Open the window", "Open window")

    assert (score.substitutions, score.deletions, score.insertions) == (0, 1, 0)


def test_an_extra_word_is_an_insertion() -> None:
    score = _score("Open Notepad", "Notepad Open Notepad")

    assert (score.substitutions, score.deletions, score.insertions) == (0, 0, 1)


def test_the_repeated_hello_is_scored_as_insertions() -> None:
    """The reported failure: one spoken word came back three times.

    Scored as insertions, not substitutions, which is what makes the shape of a
    failure readable from the numbers -- padding looks different from mishearing.
    """
    score = _score("Hello", "Hello. Hello. Hello.")

    assert score.insertions == 2
    assert score.substitutions == 0
    assert score.wer == pytest.approx(2.0), "more errors than words is possible"


def test_a_hallucinated_sentence_scores_above_one() -> None:
    """'a sentence' -> 'The top of the game.' -- the number must not cap at 1."""
    score = _score("Close the window", "The top of the game")

    assert score.wer > 1.0


def test_the_name_failure_is_scored() -> None:
    score = _score("Hari Hara Sudhan", "Hayar Asule")

    assert score.errors >= 2
    assert score.exact is False


def test_an_empty_transcript_deletes_every_word() -> None:
    score = _score("Open Notepad", "")

    assert score.deletions == 2
    assert score.wer == 1.0


def test_an_empty_reference_does_not_divide_by_zero() -> None:
    assert _score("", "").wer == 0.0
    assert _score("", "something").wer == 1.0


def test_normalisation_keeps_digits_and_drops_symbols() -> None:
    assert normalise_for_scoring("Remind me at 7, please!") == [
        "remind",
        "me",
        "at",
        "7",
        "please",
    ]


# --- 2. the corpus total, which is the comparable number ---------------------------


def test_the_corpus_wer_is_errors_over_words_not_a_mean_of_rates() -> None:
    """A mean would weight "Hello" as heavily as a nine-word sentence.

    One wrong short word would then swamp the score and two runs would not be
    comparable, which is the whole point of the command.
    """
    report = AccuracyReport(
        scores=[
            _score("Hello", "Goodbye"),
            _score(
                "Remind me tomorrow at seven to call Arjun",
                "Remind me tomorrow at seven to call Arjun",
            ),
        ]
    )

    # One error across nine reference words: "Hello" plus an eight-word phrase.
    # A mean of per-phrase rates would be (1.0 + 0.0) / 2 = 0.5 instead.
    assert report.total_words == 9
    assert report.total_errors == 1
    assert report.corpus_wer == pytest.approx(1 / 9)
    assert report.corpus_wer < 0.5


def test_exact_matches_are_counted_separately() -> None:
    report = AccuracyReport(
        scores=[
            _score("Open Notepad", "Open Notepad."),
            _score("Close the window", "Close the door"),
        ]
    )

    assert report.exact_matches == 1
    assert len(report.scores) == 2


def test_an_empty_report_is_not_a_perfect_score() -> None:
    report = AccuracyReport()

    assert report.corpus_wer == 0.0
    assert report.total_words == 0
    assert "Nothing was scored" in report.verdict()


# --- 3. the signal-to-noise reading, which says where to look ----------------------


def test_snr_is_computed_from_the_capture_metrics() -> None:
    """The number that distinguishes a bad microphone from a bad model."""
    score = PhraseScore(
        reference="Hello", actual="Hello", speech_rms=561.0, noise_floor=34.0
    )

    assert score.signal_to_noise_db == pytest.approx(24.3, abs=0.1)


def test_snr_reproduces_the_reported_range() -> None:
    """15.5 to 24.3 dB, from speech_rms 371-561 against noise_floor 34-62."""
    worst = PhraseScore(
        reference="x", actual="x", speech_rms=371.0, noise_floor=62.0
    )
    best = PhraseScore(reference="x", actual="x", speech_rms=561.0, noise_floor=34.0)

    assert worst.signal_to_noise_db == pytest.approx(15.5, abs=0.1)
    assert best.signal_to_noise_db == pytest.approx(24.3, abs=0.1)


def test_missing_metrics_report_no_snr_rather_than_a_wrong_one() -> None:
    assert PhraseScore(reference="x", actual="x").signal_to_noise_db == 0.0
    assert (
        PhraseScore(
            reference="x", actual="x", speech_rms=500.0, noise_floor=0.0
        ).signal_to_noise_db
        == 0.0
    )


# --- 4. the verdict has to point somewhere ------------------------------------------


def test_a_low_snr_is_named_as_the_thing_to_fix_first() -> None:
    report = AccuracyReport(
        scores=[
            PhraseScore(
                reference="Open Notepad",
                actual="Open the pad",
                substitutions=2,
                reference_words=2,
                speech_rms=200.0,
                noise_floor=120.0,
            )
        ]
    )

    verdict = report.verdict()
    assert "signal-to-noise" in verdict
    assert "closer" in verdict


def test_a_good_snr_with_a_bad_score_points_at_the_model() -> None:
    """The case that matters: the recording is fine and the words are wrong."""
    report = AccuracyReport(
        scores=[
            PhraseScore(
                reference="Open Notepad",
                actual="Open the pad",
                substitutions=2,
                reference_words=2,
                speech_rms=500.0,
                noise_floor=40.0,
            )
        ]
    )

    verdict = report.verdict()
    assert "small.en" in verdict
    assert "not the limit" in verdict


def test_a_good_score_is_called_good() -> None:
    report = AccuracyReport(
        scores=[_score("Open Notepad", "Open Notepad")],
    )

    assert "Good" in report.verdict()


# --- 5. the phrase list ------------------------------------------------------------


def test_there_are_ten_phrases_including_the_name() -> None:
    assert len(DEFAULT_PHRASES) == 10
    assert any("Hari Hara Sudhan" == phrase for phrase in DEFAULT_PHRASES)
    assert sum(1 for phrase in DEFAULT_PHRASES if "Hari Hara Sudhan" in phrase) == 2, (
        "the name alone and inside a sentence decode differently"
    )


def test_the_list_covers_the_reported_failure_shapes() -> None:
    assert "Hello" in DEFAULT_PHRASES, "one bare word, which came back three times"
    longest = max(DEFAULT_PHRASES, key=lambda phrase: len(phrase.split()))
    assert len(longest.split()) >= 8, "a long phrase, which fails differently"


def test_the_phrase_list_is_fixed_so_two_runs_compare() -> None:
    """A score only means something against the same text."""
    assert isinstance(DEFAULT_PHRASES, tuple)


def test_the_command_is_registered() -> None:
    from grandpa.cli.voice_cmd import voice

    assert "accuracy-test" in voice.commands
