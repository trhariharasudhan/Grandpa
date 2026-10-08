"""Measure what memory actually recalls, as a number.

Recall was unmeasured in the same way transcription was before
``grandpa voice accuracy-test``: there were pass/fail assertions that a known
query finds a known document, which is not the same as knowing how often
recall works on a question phrased the way a person would phrase it.

**Two numbers, not one.** The default backend is SQLite FTS5 with BM25
ranking, which matches *keywords*. So a question that reuses the words of the
stored fact and a question that means the same thing in different words are
different problems, and averaging them hides the only thing worth knowing. Each
fact therefore gets two queries:

* **direct** -- shares the fact's distinctive words ("what is my sister's
  name"). A keyword index should get these, and a failure here is a real defect.
* **paraphrase** -- deliberately avoids them ("who is my sibling"). A keyword
  index is expected to struggle, and the score says how much.

A blended average of the two would move for either reason and tell you
nothing about which.

**It runs against a throwaway database.** Measuring recall must not inject
twelve invented facts into the user's real memory, which is what an in-place
measurement would do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Facts of the kind a person actually asks a local assistant to remember.
#: Each has a distinctive subject so that a correct answer is unambiguous.
FACTS: tuple[tuple[str, str], ...] = (
    ("sister", "My sister's name is Priya and she lives in Chennai"),
    ("drink", "I prefer tea over coffee in the morning"),
    ("wifi", "The office wifi network is called GuestNet"),
    ("car", "My car is a blue Hyundai i20 registered in 2021"),
    ("allergy", "I am allergic to peanuts"),
    ("manager", "My manager is called Ravi and we meet on Tuesdays"),
    ("spare-key", "The spare key is under the flowerpot by the back door"),
    ("blood", "My blood group is B positive"),
    ("train", "I take the 7:40 train to work every weekday"),
    ("anniversary", "Our wedding anniversary is on the 14th of March"),
    ("dentist", "The dentist is Doctor Mehta on Anna Salai"),
    ("laptop", "I bought the laptop in November 2024"),
)

#: ``(fact_key, kind, query)``. The paraphrases avoid the stored wording on
#: purpose -- that is the measurement, not an unfair test.
QUERIES: tuple[tuple[str, str, str], ...] = (
    ("sister", "direct", "what is my sister's name"),
    ("sister", "paraphrase", "who is my sibling"),
    ("drink", "direct", "do I prefer tea or coffee"),
    ("drink", "paraphrase", "what do I like to drink when I wake up"),
    ("wifi", "direct", "what is the office wifi network called"),
    ("wifi", "paraphrase", "how do I get online at work"),
    ("car", "direct", "what car do I have"),
    ("car", "paraphrase", "what vehicle do I drive"),
    ("allergy", "direct", "what am I allergic to"),
    ("allergy", "paraphrase", "which foods must I avoid"),
    ("manager", "direct", "who is my manager"),
    ("manager", "paraphrase", "who do I report to at work"),
    ("spare-key", "direct", "where is the spare key"),
    ("spare-key", "paraphrase", "how do I get in if I am locked out"),
    ("blood", "direct", "what is my blood group"),
    ("blood", "paraphrase", "which blood type am I"),
    ("train", "direct", "what train do I take to work"),
    ("train", "paraphrase", "how do I commute in the morning"),
    ("anniversary", "direct", "when is our wedding anniversary"),
    ("anniversary", "paraphrase", "what date did we get married"),
    ("dentist", "direct", "who is my dentist"),
    ("dentist", "paraphrase", "which doctor looks after my teeth"),
    ("laptop", "direct", "when did I buy the laptop"),
    ("laptop", "paraphrase", "how old is my computer"),
)


@dataclass
class QueryOutcome:
    """One question, and where the right fact came back."""

    key: str
    kind: str
    query: str
    #: 1-based position of the expected fact, or 0 when it was not returned.
    rank: int = 0
    returned: int = 0
    top_text: str = ""

    @property
    def hit_at_1(self) -> bool:
        return self.rank == 1

    @property
    def hit_at_3(self) -> bool:
        return 1 <= self.rank <= 3

    @property
    def reciprocal_rank(self) -> float:
        return 1.0 / self.rank if self.rank else 0.0


@dataclass
class RecallReport:
    """Every query, plus the per-kind totals that are the comparable numbers."""

    backend: str = ""
    outcomes: list[QueryOutcome] = field(default_factory=list)
    stored: int = 0

    def of_kind(self, kind: str) -> list[QueryOutcome]:
        return [item for item in self.outcomes if item.kind == kind]

    def recall_at_1(self, kind: str | None = None) -> float | None:
        items = self.outcomes if kind is None else self.of_kind(kind)
        if not items:
            return None
        return sum(1 for item in items if item.hit_at_1) / len(items)

    def recall_at_3(self, kind: str | None = None) -> float | None:
        items = self.outcomes if kind is None else self.of_kind(kind)
        if not items:
            return None
        return sum(1 for item in items if item.hit_at_3) / len(items)

    def mrr(self, kind: str | None = None) -> float | None:
        """Mean reciprocal rank: rewards being first, credits being close."""
        items = self.outcomes if kind is None else self.of_kind(kind)
        if not items:
            return None
        return sum(item.reciprocal_rank for item in items) / len(items)

    def empty_results(self, kind: str | None = None) -> int:
        items = self.outcomes if kind is None else self.of_kind(kind)
        return sum(1 for item in items if item.returned == 0)

    def misses(self, kind: str | None = None) -> list[QueryOutcome]:
        items = self.outcomes if kind is None else self.of_kind(kind)
        return [item for item in items if not item.hit_at_3]

    def verdict(self) -> str:
        """What the numbers mean, so the output is not just numbers."""
        direct = self.recall_at_1("direct")
        paraphrase = self.recall_at_1("paraphrase")
        if direct is None:
            return "Nothing was measured."
        lines: list[str] = []
        if direct >= 0.9:
            lines.append(
                "Keyword recall is working: a question that reuses the words of "
                "a stored fact finds it."
            )
        elif direct >= 0.6:
            lines.append(
                "Keyword recall is unreliable. A question reusing the stored "
                "wording fails about "
                f"{(1 - direct) * 100:.0f}% of the time, which is a defect "
                "rather than a limitation."
            )
        else:
            lines.append(
                "Keyword recall is broken. Most questions fail even when they "
                "reuse the stored wording."
            )
        if paraphrase is not None:
            if paraphrase >= 0.7:
                lines.append(
                    "Paraphrases mostly work too, which is more than a keyword "
                    "index normally manages."
                )
            elif paraphrase >= 0.3:
                lines.append(
                    f"Paraphrases find the fact {paraphrase * 100:.0f}% of the "
                    "time. Asking in different words often fails, which is the "
                    "expected shape for a keyword index and the thing an "
                    "embedding backend would change."
                )
            else:
                lines.append(
                    f"Paraphrases almost never work ({paraphrase * 100:.0f}%). "
                    "Memory answers the words it was given, not the question "
                    "that was meant. Anything asked in fresh wording is lost."
                )
        return " ".join(lines)


def run_recall_test(backend: Any, *, top_k: int = 5) -> RecallReport:
    """Store the corpus, ask every question, and score where the fact landed.

    *backend* is anything with ``store(content, source=...)`` and
    ``retrieve(query, top_k=...)`` -- the same two methods ``grandpa memory
    search`` uses, so this measures the real path rather than a parallel one.
    """
    report = RecallReport(backend=type(backend).__name__)
    for key, content in FACTS:
        backend.store(content, source=f"recall-test/{key}")
        report.stored += 1

    expected = dict(FACTS)
    for key, kind, query in QUERIES:
        outcome = QueryOutcome(key=key, kind=kind, query=query)
        try:
            results = backend.retrieve(query, top_k=top_k) or []
        except Exception:  # noqa: BLE001 - a backend that raises scores zero
            results = []
        outcome.returned = len(results)
        wanted = expected[key]
        for position, result in enumerate(results, start=1):
            text = str(getattr(result, "content", "") or "")
            if position == 1:
                outcome.top_text = text
            if text.strip() == wanted.strip():
                outcome.rank = position
                break
        report.outcomes.append(outcome)
    return report


__all__ = [
    "FACTS",
    "QUERIES",
    "QueryOutcome",
    "RecallReport",
    "run_recall_test",
]
