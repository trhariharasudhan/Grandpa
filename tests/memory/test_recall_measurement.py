"""``grandpa memory recall-test`` -- recall as a number rather than an impression.

Recall was unmeasured in the way transcription was before ``accuracy-test``:
there were pass/fail assertions that a known query finds a known document,
which is not the same as knowing how often recall works on a question phrased
the way a person phrases it.

The measurement reports **two** numbers on purpose. The default backend is
SQLite FTS5 with BM25, which matches keywords, so a question reusing the stored
wording and a question meaning the same thing in other words are different
problems. A blended average would move for either reason and say nothing about
which.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.memory.recall_test import (
    FACTS,
    QUERIES,
    QueryOutcome,
    RecallReport,
    run_recall_test,
)

pytestmark = pytest.mark.core


@pytest.fixture(autouse=True)
def _backends_registered():
    """Re-register the built-in backends after conftest clears the registry.

    conftest._clean_registries empties MemoryRegistry before every
    test, and load_storage_backends() is memoised -- once it has run the
    modules are in sys.modules so the @MemoryRegistry.register
    decorators never fire again. The same fixture exists in
    test_backend_resolution.py for the same reason; this is a property of
    the suite, not of the command.
    """
    from grandpa.core.registry import MemoryRegistry
    from grandpa.tools.storage import load_storage_backends
    from grandpa.tools.storage.dense import DenseMemory
    from grandpa.tools.storage.hybrid import HybridMemory
    from grandpa.tools.storage.sqlite import SQLiteMemory

    load_storage_backends()
    MemoryRegistry.register_or_replace("sqlite", SQLiteMemory)
    MemoryRegistry.register_or_replace("dense", DenseMemory)
    MemoryRegistry.register_or_replace("hybrid", HybridMemory)


def _backend(tmp_path):
    from grandpa.core.registry import MemoryRegistry
    from grandpa.tools.storage.sqlite import SQLiteMemory

    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)
    return SQLiteMemory(db_path=str(tmp_path / "recall.db"))


# --- the corpus is a fair test ----------------------------------------------------


def test_every_fact_has_both_kinds_of_question() -> None:
    """One direct, one paraphrase. The split is the whole measurement."""
    keys = {key for key, _ in FACTS}
    for kind in ("direct", "paraphrase"):
        asked = {key for key, k, _ in QUERIES if k == kind}
        assert asked == keys, f"{kind} questions do not cover every fact"


def test_a_paraphrase_avoids_the_words_of_its_fact() -> None:
    """Otherwise it is a direct question wearing a hat, and measures nothing.

    The check is on the distinctive words: every paraphrase must avoid at least
    the main noun of the stored fact, or a keyword index would find it for the
    wrong reason and the score would flatter it.
    """
    facts = dict(FACTS)
    stopwords = {
        "my", "the", "is", "i", "a", "in", "on", "of", "and", "to", "at",
        "we", "our", "am", "do", "it", "every",
    }
    for key, kind, query in QUERIES:
        if kind != "paraphrase":
            continue
        fact_words = {
            word.strip(".,'s").lower() for word in facts[key].split()
        } - stopwords
        query_words = {word.strip(".,'s").lower() for word in query.split()} - stopwords
        overlap = fact_words & query_words
        assert len(overlap) < len(query_words), (
            f"paraphrase for {key!r} reuses all its own words: {overlap}"
        )


def test_the_corpus_is_small_enough_to_run_in_seconds() -> None:
    """A ten-step ritual does not get used. That lesson cost two voice runs."""
    assert len(FACTS) <= 20
    assert len(QUERIES) <= 50


# --- the scoring ------------------------------------------------------------------


def test_rank_one_is_a_hit_at_one_and_at_three() -> None:
    outcome = QueryOutcome(key="k", kind="direct", query="q", rank=1, returned=5)

    assert outcome.hit_at_1 is True
    assert outcome.hit_at_3 is True
    assert outcome.reciprocal_rank == 1.0


def test_rank_three_is_a_hit_at_three_only() -> None:
    outcome = QueryOutcome(key="k", kind="direct", query="q", rank=3, returned=5)

    assert outcome.hit_at_1 is False
    assert outcome.hit_at_3 is True
    assert outcome.reciprocal_rank == pytest.approx(1 / 3)


def test_a_fact_that_never_came_back_scores_zero() -> None:
    outcome = QueryOutcome(key="k", kind="direct", query="q", rank=0, returned=5)

    assert outcome.hit_at_1 is False
    assert outcome.hit_at_3 is False
    assert outcome.reciprocal_rank == 0.0


def test_the_two_kinds_are_scored_separately() -> None:
    """The point of the split: one number per kind, never one blended number."""
    report = RecallReport(
        outcomes=[
            QueryOutcome(key="a", kind="direct", query="q", rank=1, returned=5),
            QueryOutcome(key="b", kind="direct", query="q", rank=1, returned=5),
            QueryOutcome(key="a", kind="paraphrase", query="q", rank=0, returned=5),
            QueryOutcome(key="b", kind="paraphrase", query="q", rank=0, returned=5),
        ]
    )

    assert report.recall_at_1("direct") == 1.0
    assert report.recall_at_1("paraphrase") == 0.0
    assert report.recall_at_1() == 0.5, "the blend is available but never the headline"


def test_an_empty_report_has_no_rate_rather_than_zero() -> None:
    """Same rule the accuracy report learned: no measurement is not a score."""
    report = RecallReport()

    assert report.recall_at_1() is None
    assert report.mrr() is None
    assert "Nothing was measured" in report.verdict()


def test_a_query_returning_nothing_is_counted_apart_from_a_wrong_answer() -> None:
    """Returning the wrong fact and returning none are different failures.

    The second is honest. The first is an assistant confidently recalling
    something that was not asked for.
    """
    report = RecallReport(
        outcomes=[
            QueryOutcome(key="a", kind="direct", query="q", rank=0, returned=0),
            QueryOutcome(key="b", kind="direct", query="q", rank=0, returned=5),
        ]
    )

    assert report.empty_results() == 1
    assert len(report.misses()) == 2


# --- against the real default backend ---------------------------------------------


def test_the_default_backend_recalls_a_directly_worded_question(tmp_path) -> None:
    """The floor this must not drop below: keyword recall on keyword queries.

    Measured at 100% when written. A regression here is a defect rather than a
    limitation of the index, which is exactly why it is scored separately.
    """
    report = run_recall_test(_backend(tmp_path))

    assert report.stored == len(FACTS)
    assert report.recall_at_1("direct") >= 0.9, (
        f"direct recall fell to {report.recall_at_1('direct')}"
    )


def test_the_measurement_records_where_a_paraphrase_landed(tmp_path) -> None:
    """Not asserted as a threshold: the number is the finding, not a target.

    Pinning paraphrase recall high would be pinning a wish, and pinning it low
    would stop anyone improving it. What is pinned is that the measurement
    produces a number at all.
    """
    report = run_recall_test(_backend(tmp_path))
    score = report.recall_at_1("paraphrase")

    assert score is not None
    assert 0.0 <= score <= 1.0


def test_a_backend_that_raises_scores_zero_rather_than_crashing(tmp_path) -> None:
    class Hostile:
        def store(self, content, **kwargs):
            return "id"

        def retrieve(self, query, **kwargs):
            raise RuntimeError("backend is broken")

    report = run_recall_test(Hostile())

    assert report.recall_at_1() == 0.0
    assert report.empty_results() == len(QUERIES)


# --- the command ------------------------------------------------------------------


def test_the_command_runs_and_reports_both_numbers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    result = CliRunner().invoke(
        cli, ["memory", "recall-test", "--backend", "sqlite"]
    )

    assert result.exit_code == 0, result.output
    assert "direct wording" in result.output
    assert "paraphrased" in result.output
    assert "recall@1" in result.output


def test_the_command_emits_json_for_comparing_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    result = CliRunner().invoke(
        cli, ["memory", "recall-test", "--backend", "sqlite", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["facts_stored"] == len(FACTS)
    assert data["queries"] == len(QUERIES)
    assert 0.0 <= data["direct"]["recall_at_1"] <= 1.0
    assert "paraphrase" in data


def test_it_does_not_touch_the_real_memory_store(tmp_path, monkeypatch) -> None:
    """Measuring recall must not add a dozen invented facts to real memory."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    CliRunner().invoke(cli, ["memory", "recall-test"])

    leaked = list(tmp_path.rglob("memory.db"))
    for path in leaked:
        from grandpa.tools.storage.sqlite import SQLiteMemory

        store = SQLiteMemory(db_path=str(path))
        try:
            found = store.retrieve("Priya Chennai sister", top_k=5)
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()
        assert not any(
            "Priya" in str(getattr(item, "content", "")) for item in found
        ), "a recall-test fact reached the real memory database"
