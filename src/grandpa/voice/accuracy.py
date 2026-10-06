"""Word error rate against phrases the user was asked to read.

Transcription quality was being judged from anecdotes -- "it said 'The top of the
game'" -- which cannot tell a regression from a bad day, and cannot tell whether
a change helped. This measures it: ten fixed phrases, read aloud, scored word by
word against what was asked for.

WER is the standard measure: (substitutions + deletions + insertions) divided by
the number of words in the reference, after lowercasing and stripping
punctuation. 0.0 is perfect, 1.0 is as many errors as words, and above 1.0 is
possible when the model invents extra words.

The phrase list is fixed on purpose. A score is only comparable to another score
taken on the same text, so these must not drift between runs; ``--phrases`` is
there for deliberately measuring something else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Ten phrases, each chosen for a reason rather than for variety.
#:
#: * a bare word, because one spoken "hello" came back as "Hello. Hello. Hello."
#: * the user's name alone and inside a sentence, because "Hari Hara Sudhan"
#:   came back as "Hayar Asule" and a name in context decodes differently from a
#:   name in isolation
#: * commands the assistant actually routes, so the score reflects the job
#: * one long phrase, because a sentence came back as "The top of the game" and
#:   longer utterances fail differently from short ones
DEFAULT_PHRASES: tuple[str, ...] = (
    "Hello",
    "Hari Hara Sudhan",
    "Open Notepad",
    "What is the time",
    "Close the window",
    "My name is Hari Hara Sudhan",
    "Type hello in Notepad",
    "What is my voice status",
    "Remind me tomorrow at seven to call Arjun",
    "Scroll down and take a screenshot",
)


def normalise_for_scoring(text: str) -> list[str]:
    """Lowercase, drop punctuation, split on whitespace.

    Standard WER practice. Without it "Notepad." scores as an error against
    "Notepad", and the number stops being about recognition.
    """
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


@dataclass(frozen=True)
class PhraseScore:
    """One phrase, read once."""

    reference: str
    actual: str
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    reference_words: int = 0
    seconds: float = 0.0
    #: Capture metrics, so a bad score can be told from a bad recording.
    speech_rms: float = 0.0
    noise_floor: float = 0.0
    voiced_seconds: float = 0.0
    peak_dbfs: float = 0.0

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def wer(self) -> float:
        if not self.reference_words:
            return 0.0 if not normalise_for_scoring(self.actual) else 1.0
        return self.errors / self.reference_words

    @property
    def exact(self) -> bool:
        return normalise_for_scoring(self.reference) == normalise_for_scoring(
            self.actual
        )

    @property
    def signal_to_noise_db(self) -> float:
        """The number that says whether the microphone is the limit."""
        import math

        if self.speech_rms <= 0 or self.noise_floor <= 0:
            return 0.0
        return 20 * math.log10(self.speech_rms / self.noise_floor)


@dataclass
class AccuracyReport:
    """Every phrase, plus the corpus totals that are the comparable number."""

    scores: list[PhraseScore] = field(default_factory=list)
    model: str = ""
    skipped: list[str] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return sum(score.errors for score in self.scores)

    @property
    def total_words(self) -> int:
        return sum(score.reference_words for score in self.scores)

    @property
    def corpus_wer(self) -> float:
        """Errors over words across the whole run.

        Not the mean of the per-phrase rates: that would weight "Hello" as
        heavily as a nine-word sentence, so one wrong short word would swamp the
        score.
        """
        if not self.total_words:
            return 0.0
        return self.total_errors / self.total_words

    @property
    def exact_matches(self) -> int:
        return sum(1 for score in self.scores if score.exact)

    @property
    def median_snr_db(self) -> float:
        values = sorted(
            score.signal_to_noise_db
            for score in self.scores
            if score.signal_to_noise_db > 0
        )
        if not values:
            return 0.0
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2

    def verdict(self) -> str:
        """What the number means, so it is not just a number."""
        if not self.scores:
            return "Nothing was scored."
        wer = self.corpus_wer
        snr = self.median_snr_db
        if wer <= 0.10:
            quality = "Good. Recognition is working."
        elif wer <= 0.25:
            quality = "Usable, with errors. Commands will mostly route."
        elif wer <= 0.50:
            quality = "Poor. Expect to repeat yourself often."
        else:
            quality = "Failing. Most words are wrong."
        if 0 < snr < 10:
            cause = (
                f" The median signal-to-noise ratio was {snr:.1f} dB, which is "
                f"low enough to be the limit -- move closer to the microphone or "
                f"reduce background noise before changing anything else."
            )
        elif snr >= 10 and wer > 0.25:
            cause = (
                f" The median signal-to-noise ratio was {snr:.1f} dB, which is "
                f"adequate, so the recording is probably not the limit. A larger "
                f"model is the next lever: --model small.en."
            )
        else:
            cause = ""
        return quality + cause


def score_phrase(reference: str, actual: str) -> tuple[int, int, int, int]:
    """Word-level Levenshtein, returning (substitutions, deletions, insertions,
    reference length).

    Backtracked rather than counted during the forward pass, because the three
    operation types cannot be separated from the distance alone and reporting
    them separately is what makes a score diagnosable: all-insertions means the
    model padded, all-substitutions means it misheard.
    """
    ref = normalise_for_scoring(reference)
    hyp = normalise_for_scoring(actual)
    if not ref:
        return 0, 0, len(hyp), 0

    rows, cols = len(ref) + 1, len(hyp) + 1
    distance = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        distance[i][0] = i
    for j in range(cols):
        distance[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            if ref[i - 1] == hyp[j - 1]:
                distance[i][j] = distance[i - 1][j - 1]
            else:
                distance[i][j] = 1 + min(
                    distance[i - 1][j - 1], distance[i - 1][j], distance[i][j - 1]
                )

    substitutions = deletions = insertions = 0
    i, j = len(ref), len(hyp)
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and distance[i][j] == distance[i - 1][j - 1] + 1:
            substitutions += 1
            i, j = i - 1, j - 1
        elif i > 0 and distance[i][j] == distance[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return substitutions, deletions, insertions, len(ref)


__all__ = [
    "DEFAULT_PHRASES",
    "AccuracyReport",
    "PhraseScore",
    "normalise_for_scoring",
    "score_phrase",
]
