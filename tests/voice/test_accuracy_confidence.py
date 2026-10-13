"""A word error rate from 16 words cannot settle much, and must say so.

Reported: two runs of the same model on the same phrases gave 0.562 and 0.750.
At 16 reference words one word moves the rate by 1/16 = 0.0625, so that
difference is three words -- and nothing in the output said it was noise.

The arithmetic this file pins:

    16 words   one word = 0.0625           two runs must differ by 0.44
    32 words   (two runs pooled)           ...by 0.33
   160 words   (ten runs pooled)           ...by 0.15
   193 words   what a 0.10 difference needs

So the fix is not a bigger number per run -- it is an interval beside the
number, a history so short runs accumulate, and a plain statement of what the
current sample can resolve.
"""

from __future__ import annotations

import pytest

from grandpa.voice.accuracy_stats import (
    difference_is_meaningful,
    load_history,
    models_in,
    one_word_is,
    pooled,
    record_run,
    resolvable_difference,
    wer_interval,
    words_needed,
)

pytestmark = pytest.mark.core

#: The default run: three phrases of the shipped corpus.
WORDS = 16


# --- the resolution floor ---------------------------------------------------------


def test_one_word_is_one_over_n() -> None:
    assert one_word_is(16) == pytest.approx(0.0625)
    assert one_word_is(160) == pytest.approx(0.00625)


def test_the_reported_runs_are_three_words_apart() -> None:
    """0.562 vs 0.750 at 16 words is 9 errors vs 12. Three words."""
    assert round(0.562 * WORDS) == 9
    assert round(0.750 * WORDS) == 12


# --- the interval -----------------------------------------------------------------


def test_the_interval_at_sixteen_words_is_about_a_fifth_of_the_scale() -> None:
    interval = wer_interval(8, 16)

    assert interval.half_width == pytest.approx(0.22, abs=0.02)


def test_wilson_not_the_normal_approximation() -> None:
    """At N=16 the textbook interval runs off the end of the scale.

    p +- 1.96*sqrt(p(1-p)/n) for 1 error in 16 gives a negative lower bound,
    which is not a possible word error rate.
    """
    import math

    rate = 1 / 16
    naive_low = rate - 1.96 * math.sqrt(rate * (1 - rate) / 16)
    assert naive_low < 0, "the naive interval should be the broken one here"

    interval = wer_interval(1, 16)
    assert interval.low >= 0.0
    assert interval.high <= 1.0


def test_a_rate_above_one_gets_no_interval() -> None:
    """Insertions are unbounded, so WER can exceed 1 and stop being a proportion.

    The user's base.en run was 1.500 -- 24 errors in 16 words. Returning a
    binomial interval for that would be inventing one.
    """
    interval = wer_interval(24, 16)

    assert interval.rate == pytest.approx(1.5)
    assert interval.unavailable
    assert "above 1.0" in interval.unavailable
    assert "insert" in interval.unavailable


def test_nothing_scored_has_no_interval() -> None:
    interval = wer_interval(0, 0)

    assert interval.unavailable == "nothing was scored"


def test_the_interval_narrows_as_the_sample_grows() -> None:
    widths = [wer_interval(round(0.5 * n), n).half_width for n in (16, 32, 160, 320)]

    assert widths == sorted(widths, reverse=True), "more words must mean less doubt"
    assert widths[0] > 0.2
    assert widths[-1] < 0.12


# --- what the sample can settle ---------------------------------------------------


def test_sixteen_words_cannot_settle_the_reported_difference() -> None:
    """The headline arithmetic: 0.44 is needed, 0.19 was observed."""
    assert resolvable_difference(16) == pytest.approx(0.44, abs=0.02)
    assert abs(0.750 - 0.562) < resolvable_difference(16)


def test_words_needed_for_a_ten_point_difference() -> None:
    """So the answer to "how much would I have to read" is a number."""
    assert words_needed(0.10) == pytest.approx(193, abs=2)
    assert words_needed(0.05) == pytest.approx(769, abs=5)
    assert words_needed(0.30) < words_needed(0.10)


# --- comparing two models ---------------------------------------------------------


def test_the_two_small_en_runs_are_inside_the_noise() -> None:
    """The reported pair. Same model, same phrases, 0.562 then 0.750."""
    first = wer_interval(9, 16)
    second = wer_interval(12, 16)

    meaningful, why = difference_is_meaningful(first, second)

    assert meaningful is False
    assert "overlap" in why
    assert "reference words" in why, "it should say how many words would settle it"


def test_small_en_pooled_beats_base_en() -> None:
    """The question asked: is small.en actually better, or is that noise too?

    small.en pooled over both runs is 21 errors in 32 words. base.en was 24 in
    16. The gap is 0.84 against a half-width of 0.16, so the difference is real
    even though neither single run could settle anything on its own.
    """
    small = wer_interval(9 + 12, 32)
    base = wer_interval(24, 16)

    assert small.rate == pytest.approx(0.656, abs=0.001)
    meaningful, why = difference_is_meaningful(base, small)

    assert meaningful is True
    assert "not noise" in why


def test_a_gap_inside_both_intervals_is_reported_as_noise() -> None:
    meaningful, why = difference_is_meaningful(
        wer_interval(8, 32), wer_interval(9, 32)
    )

    assert meaningful is False
    assert "overlap" in why


def test_a_clear_gap_at_a_decent_sample_is_reported_as_real() -> None:
    meaningful, why = difference_is_meaningful(
        wer_interval(10, 200), wer_interval(100, 200)
    )

    assert meaningful is True
    assert "do not overlap" in why


# --- the history, which is how the sample grows -----------------------------------


def test_a_run_is_recorded_and_read_back(tmp_path) -> None:
    path = tmp_path / "history.jsonl"

    assert record_run("small.en", 9, 16, 3, path=path) is True
    runs = load_history(path)

    assert len(runs) == 1
    assert runs[0]["model"] == "small.en"
    assert runs[0]["errors"] == 9
    assert runs[0]["words"] == 16


def test_runs_pool_by_summing_errors_and_words(tmp_path) -> None:
    """Not by averaging the rates: a four-word run must not weigh as much as
    a forty-word one."""
    path = tmp_path / "history.jsonl"
    record_run("small.en", 9, 16, 3, path=path)
    record_run("small.en", 12, 16, 3, path=path)

    interval = pooled(load_history(path), "small.en")

    assert interval.words == 32
    assert interval.rate == pytest.approx(21 / 32)


def test_pooling_narrows_what_can_be_settled(tmp_path) -> None:
    """The reason a history exists at all."""
    path = tmp_path / "history.jsonl"
    for _ in range(10):
        record_run("small.en", 9, 16, 3, path=path)

    interval = pooled(load_history(path), "small.en")

    assert interval.words == 160
    assert resolvable_difference(interval.words) < resolvable_difference(16)
    assert resolvable_difference(interval.words) == pytest.approx(0.15, abs=0.02)


def test_models_are_kept_apart(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    record_run("base.en", 24, 16, 3, path=path)
    record_run("small.en", 9, 16, 3, path=path)
    runs = load_history(path)

    assert models_in(runs) == ["base.en", "small.en"]
    assert pooled(runs, "base.en").words == 16
    assert pooled(runs, "small.en").rate == pytest.approx(9 / 16)


def test_a_corrupt_history_line_is_skipped(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    record_run("small.en", 9, 16, 3, path=path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    record_run("small.en", 12, 16, 3, path=path)

    assert len(load_history(path)) == 2


def test_an_unwritable_history_does_not_fail_the_measurement(tmp_path) -> None:
    """A lost history is a lost convenience, not a lost measurement."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")

    assert record_run("small.en", 9, 16, 3, path=blocker / "h.jsonl") is False


def test_no_history_reads_as_empty_rather_than_raising(tmp_path) -> None:
    assert load_history(tmp_path / "never-written.jsonl") == []


def test_the_history_lives_under_grandpa_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    from grandpa.voice.accuracy_stats import history_path

    assert history_path().is_relative_to(tmp_path)


# --- the printed report -----------------------------------------------------------


def test_the_interval_prints_beside_the_rate() -> None:
    assert "95% CI" in str(wer_interval(8, 16))


def test_a_rate_without_an_interval_prints_compactly() -> None:
    """The reason goes on its own line; inline it buried the number."""
    text = str(wer_interval(24, 16))

    assert text.startswith("1.500")
    assert len(text) < 50
    assert "insert" not in text


def test_the_report_states_what_the_sample_can_settle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    from grandpa.cli.voice_cmd import _print_accuracy_report
    from grandpa.voice.accuracy import AccuracyReport, PhraseScore

    report = AccuracyReport(
        model="small.en",
        requested=3,
        scores=[
            PhraseScore(
                reference=" ".join(["w"] * 16),
                actual="x",
                substitutions=9,
                deletions=0,
                insertions=0,
                reference_words=16,
                seconds=1.0,
            )
        ],
    )

    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_accuracy_report(report, as_json=False)
    out = buffer.getvalue()

    assert "95% CI" in out
    assert "one word error = 1/16" in out
    assert "must differ by 0.44" in out
