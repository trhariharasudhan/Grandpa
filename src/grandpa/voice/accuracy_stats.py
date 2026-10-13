"""How much a word error rate can actually tell you, and how to grow the sample.

Reported: two runs of the same model on the same phrases gave WER 0.562 and
0.750, and at 16 reference words one word moves the rate by 1/16 = 0.0625, so a
difference of 0.19 is three words. There is no way to tell that from noise by
looking at it.

**The arithmetic.** Treat each reference word as a trial that either produces an
error or does not. That is the standard approximation for a word error rate, and
it gives a binomial confidence interval on ``E/N``. The Wilson form is used
rather than the textbook ``p +- 1.96*sqrt(p(1-p)/n)``, because at N=16 the
normal approximation runs off the end of the scale and reports bounds below 0 or
above 1.

Two consequences worth stating plainly:

* **One word is 1/N.** At 16 words that is 0.0625, so the smallest difference
  the measurement can even represent is six points of WER.
* **The interval is far wider than that.** At N=16 and p around 0.6 the 95%
  interval spans roughly +-0.23, so two runs have to differ by about half the
  scale before the difference means anything.

**Where the model breaks.** WER can exceed 1.0, because insertions are counted
and there is no upper bound on how many words a decoder can invent. A rate above
1 is not a proportion, so no binomial interval applies to it. The functions
below say so instead of returning a number that looks like one.

**Growing the sample without reading more phrases.** A run of three phrases is
16 words and cannot settle anything; ten runs of three phrases is 160 words and
can settle a difference of about 0.15. So each run is appended to a history and
the pooled estimate is reported beside the single-run one. The user reads three
phrases, which takes under a minute, and the sample grows every time.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

#: 95% two-sided. 1.96 is the normal quantile the Wilson interval uses.
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    """A confidence interval on a word error rate, or a stated refusal."""

    rate: float
    low: float
    high: float
    words: int
    #: Set when no interval is meaningful, with the reason.
    unavailable: str = ""

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2.0

    def __str__(self) -> str:
        """Short enough to sit beside the number it describes.

        The full reason lives in :attr:`unavailable` and the caller prints it on
        its own line; inline it buried the rate it was about.
        """
        if self.unavailable:
            return f"{self.rate:.3f}  (no confidence interval)"
        return f"{self.rate:.3f}  95% CI [{self.low:.3f}, {self.high:.3f}]"


def wer_interval(errors: int, words: int) -> Interval:
    """A Wilson 95% interval on ``errors / words``.

    Wilson rather than the normal approximation because at the sample sizes
    this command produces -- 16 words -- the normal interval reports bounds
    outside [0, 1] and is simply wrong.
    """
    words = int(words)
    errors = int(errors)
    if words <= 0:
        return Interval(0.0, 0.0, 0.0, 0, unavailable="nothing was scored")
    rate = errors / words
    if errors > words:
        # Insertions can exceed the reference length, so the rate is not a
        # proportion and no binomial interval describes it.
        return Interval(
            rate, rate, rate, words,
            unavailable=(
                f"{errors} errors in {words} words is above 1.0, which happens "
                f"when the decoder inserts words. A rate above 1 is not a "
                f"proportion, so no confidence interval applies"
            ),
        )
    z = Z_95
    centre = (rate + z * z / (2 * words)) / (1 + z * z / words)
    spread = (
        z
        / (1 + z * z / words)
        * math.sqrt(rate * (1 - rate) / words + z * z / (4 * words * words))
    )
    return Interval(rate, max(0.0, centre - spread), min(1.0, centre + spread), words)


def one_word_is(words: int) -> float:
    """How much a single word error moves the rate. The resolution floor."""
    return 1.0 / words if words > 0 else float("inf")


def resolvable_difference(words: int, rate: float = 0.5) -> float:
    """The smallest WER gap two samples of this size could distinguish.

    Twice the interval's half-width, because both numbers carry one. Returned
    at the worst case ``rate=0.5`` by default, which is where the interval is
    widest and so where the honest answer lives.
    """
    if words <= 0:
        return float("inf")
    interval = wer_interval(int(round(rate * words)), words)
    if interval.unavailable:
        return float("inf")
    return 2.0 * interval.half_width


def words_needed(difference: float, rate: float = 0.5) -> int:
    """Reference words required to resolve *difference* at 95%.

    From the two-sample normal form, ``n >= 2 z^2 p(1-p) / d^2``. Reported so
    the answer to "how much would I have to read" is a number rather than a
    shrug.
    """
    if difference <= 0:
        return 0
    return int(math.ceil(2 * Z_95 * Z_95 * rate * (1 - rate) / (difference * difference)))


def difference_is_meaningful(first: Interval, second: Interval) -> tuple[bool, str]:
    """Do two intervals separate? With the reason either way.

    Non-overlap is a conservative test -- it is stricter than a proper
    two-sample test -- and it is the one a person can check by eye against the
    printed bounds, which matters more here than the last few percent of power.
    """
    if first.unavailable or second.unavailable:
        reason = first.unavailable or second.unavailable
        gap = abs(first.rate - second.rate)
        # Both rates are still comparable as magnitudes even when one has no
        # interval; say how the gap compares with the interval that does exist.
        usable = second if first.unavailable else first
        if not usable.unavailable and gap > 2 * usable.half_width:
            return True, (
                f"no interval for one of them ({reason}), but the gap of "
                f"{gap:.3f} is more than twice the other's half-width "
                f"({usable.half_width:.3f}), so the difference is not noise"
            )
        return False, f"no interval for one of them ({reason})"
    if first.high < second.low or second.high < first.low:
        return True, (
            f"the intervals do not overlap: "
            f"[{first.low:.3f}, {first.high:.3f}] vs "
            f"[{second.low:.3f}, {second.high:.3f}]"
        )
    needed = words_needed(abs(first.rate - second.rate) or 0.05)
    return False, (
        f"the intervals overlap: [{first.low:.3f}, {first.high:.3f}] vs "
        f"[{second.low:.3f}, {second.high:.3f}]. A gap of "
        f"{abs(first.rate - second.rate):.3f} needs about {needed} reference "
        f"words per model to call; you have {first.words} and {second.words}"
    )


# =====================================================================
# The history, so repeated short runs accumulate into one sample
# =====================================================================


def history_path() -> Path:
    """Under GRANDPA_HOME, resolved at call time."""
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "diagnostics" / "accuracy-history.jsonl"


def record_run(
    model: str, errors: int, words: int, phrases: int, *, path: Path | None = None
) -> bool:
    """Append one run. Never raises: a lost history must not fail a measurement."""
    target = path or history_path()
    entry = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": str(model or ""),
        "errors": int(errors),
        "words": int(words),
        "phrases": int(phrases),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return True
    except Exception:  # noqa: BLE001 - history is a convenience, not the measurement
        return False


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    """Every recorded run. A corrupt line is skipped, not fatal."""
    target = path or history_path()
    runs: list[dict[str, Any]] = []
    try:
        text = target.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - no history yet is not an error
        return runs
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(entry, dict) and entry.get("words"):
            runs.append(entry)
    return runs


def pooled(runs: list[dict[str, Any]], model: str | None = None) -> Interval:
    """One interval over every run, which is the point of keeping a history.

    Errors and words are summed rather than the rates averaged: a run that
    scored four words should not weigh as much as one that scored forty.
    """
    chosen = [
        run
        for run in runs
        if model is None or str(run.get("model", "")) == model
    ]
    errors = sum(int(run.get("errors", 0)) for run in chosen)
    words = sum(int(run.get("words", 0)) for run in chosen)
    return wer_interval(errors, words)


def models_in(runs: list[dict[str, Any]]) -> list[str]:
    return sorted({str(run.get("model", "")) for run in runs if run.get("model")})


__all__ = [
    "Interval",
    "Z_95",
    "difference_is_meaningful",
    "history_path",
    "load_history",
    "models_in",
    "one_word_is",
    "pooled",
    "record_run",
    "resolvable_difference",
    "wer_interval",
    "words_needed",
]
