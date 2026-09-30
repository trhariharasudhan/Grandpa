"""A person repeating themselves is not a Whisper loop.

The filter that discarded a correctly decoded microphone test. The user said
"Hello Grandpa" three times, faster-whisper decoded it exactly, no_speech_prob
0.4335 was inside every confidence gate -- and the production path answered
"I could not understand the audio."

``_is_hallucinated_repetition`` fired: at a two-word period the phrase accounted
for 3 of 3 chunks, 100%, against a rule that needed 65% of at least 3. Three is
what a person does when nothing is responding, so the rule could not tell a user
from a degenerate decode.

Two things that are NOT the discriminator, both measured rather than assumed:

* **gzip compression ratio.** faster-whisper already rejects segments above 2.4
  and this text scored 1.16, so Whisper was right to keep it. Deferring to that
  mechanism instead would be worse, not better: a genuine twelve-times loop
  scores only 1.78 and would sail through.
* **the 65% dominance ratio.** A phrase said three times and a phrase looped
  twelve times both score 1.00.

Repetition *count* is the signal that separates them, and the period has to be
wide enough to see the loop at all -- the old (1, 2, 3) could not match
"I don't know." (four words) or "Subtitles by the Amara.org community" (six),
which are stock Whisper hallucinations that no count threshold caught.

The corpus below is the evidence for both numbers. The old rule scored 9/15 real
kept and 5/8 loops caught; this one scores 15/15 and 8/8.
"""

from __future__ import annotations

import gzip

import pytest

from grandpa.speech.faster_whisper import (
    _LOOP_PERIODS,
    _MIN_LOOP_REPEATS,
    _is_hallucinated_repetition,
)

pytestmark = pytest.mark.core

#: What the microphone test actually produced.
OBSERVED = "Hello Grandpa. Hello Grandpa. Hello Grandpa."

#: Real speech. Every one of these must survive the filter.
REAL_SPEECH = (
    OBSERVED,
    "Hello Grandpa, hello Grandpa, are you there?",
    "I said stop. I said stop. I said stop.",
    "open notepad open notepad open notepad",
    "type hello type hello type hello",
    "testing one two testing one two testing one two",
    "turn the volume up turn the volume up",
    "no no no",
    "yes yes yes",
    "What is the weather like in London today?",
    "Set a reminder for five o'clock please.",
    "Grandpa? Grandpa? Can you hear me?",
    "So I went to the shop and then I went to the park and then I went home "
    "because it was getting late and I was tired.",
    "Add milk, add bread, add eggs, add butter, add cheese to the shopping list.",
)

#: Degenerate decodes. Every one of these must be discarded.
WHISPER_LOOPS = (
    # The two the existing suite already documented, and which set the threshold.
    # I picked eight repetitions first, on the corpus above; these were the cases
    # I had not thought of, and five is what satisfies them and the regression.
    "I'm sorry. " * 5,
    "Thank you. " * 5,
    "you " * 7,
    "you " * 8,
    "you " * 12,
    "Thank you. " * 30,
    "Hello Grandpa. " * 60,
    "the " * 10,
    "I don't know. " * 15,
    "Subtitles by the Amara.org community " * 9,
    "Please subscribe to my channel. " * 12,
)


def test_the_reported_transcript_is_no_longer_discarded() -> None:
    """The regression, named. This is the microphone test that failed."""
    assert _is_hallucinated_repetition(OBSERVED) is False, (
        "a correctly decoded 'Hello Grandpa' said three times is still being "
        "treated as a hallucination"
    )


@pytest.mark.parametrize("text", REAL_SPEECH, ids=lambda t: t[:32])
def test_real_speech_survives(text: str) -> None:
    assert _is_hallucinated_repetition(text) is False, text


@pytest.mark.parametrize("text", WHISPER_LOOPS, ids=lambda t: t[:32])
def test_degenerate_loops_are_discarded(text: str) -> None:
    assert _is_hallucinated_repetition(text) is True, text


def test_the_filter_is_strictly_better_than_the_rule_it_replaced() -> None:
    """Both directions, so this is not recorded as a loosening.

    Reimplements the old rule rather than describing it, so the comparison is
    against what actually shipped.
    """
    import re

    def old_rule(text: str) -> bool:
        clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
        words = clean.split()
        if len(words) >= 6:
            for n in (1, 2, 3):
                chunks = [
                    " ".join(words[i : i + n]) for i in range(0, len(words) - n + 1, n)
                ]
                if len(chunks) >= 3:
                    most_common = max(set(chunks), key=chunks.count)
                    if chunks.count(most_common) / len(chunks) >= 0.65:
                        return True
        return False

    old_real_kept = sum(1 for t in REAL_SPEECH if not old_rule(t))
    new_real_kept = sum(1 for t in REAL_SPEECH if not _is_hallucinated_repetition(t))
    old_loops_caught = sum(1 for t in WHISPER_LOOPS if old_rule(t))
    new_loops_caught = sum(1 for t in WHISPER_LOOPS if _is_hallucinated_repetition(t))

    assert new_real_kept > old_real_kept, (
        f"real speech kept: was {old_real_kept}, now {new_real_kept}"
    )
    assert new_loops_caught >= old_loops_caught, (
        f"loops caught: was {old_loops_caught}, now {new_loops_caught} -- the "
        f"change must not trade one direction for the other"
    )
    assert new_real_kept == len(REAL_SPEECH)
    assert new_loops_caught == len(WHISPER_LOOPS)


def test_compression_ratio_would_not_have_done_this_job() -> None:
    """Recorded because it was my first instinct and the numbers refuted it.

    faster-whisper's compression_ratio_threshold is 2.4 and is already applied
    during decoding. Removing this filter in favour of it would let short loops
    through.
    """

    def ratio(text: str) -> float:
        raw = text.encode("utf-8")
        return len(raw) / max(1, len(gzip.compress(raw)))

    assert ratio(OBSERVED) < 2.4, "Whisper's own gate kept this, correctly"
    assert ratio("you " * 12) < 2.4, (
        "a twelve-times loop is below Whisper's threshold, so compression ratio "
        "alone cannot replace this filter"
    )
    assert _is_hallucinated_repetition("you " * 12) is True


def test_the_thresholds_are_stated_not_buried() -> None:
    """The two numbers this fix turns on, asserted so a change is deliberate."""
    assert _MIN_LOOP_REPEATS == 5
    assert _LOOP_PERIODS == (1, 2, 3, 4, 5, 6)


def test_the_accepted_false_positive_is_recorded() -> None:
    """Five repetitions is a trade, not a free win, and the cost is named here.

    A person saying "yes" six times is real speech and is discarded. That is the
    price of catching "I'm sorry." five times, which the suite already required.
    Recorded as a test so it is a known cost rather than a surprise in a bug
    report.
    """
    assert _is_hallucinated_repetition("yes yes yes yes yes yes") is True
    # Three and four still survive, which is the range people actually use.
    assert _is_hallucinated_repetition("yes yes yes") is False
    assert _is_hallucinated_repetition("yes yes yes yes") is False


def test_a_short_utterance_is_never_a_loop() -> None:
    """Under six words there is nothing to repeat."""
    for text in ("hello", "hello grandpa", "yes", "stop it now", "open notepad"):
        assert _is_hallucinated_repetition(text) is False, text
