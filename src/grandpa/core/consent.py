"""Read a spoken or typed answer to "Shall I?" -- yes, no, or something else.

Every confirmation in Grandpa (the chat engine's ``[y/N]``, a waiting plan,
the orb's staged action) answers through :func:`read_consent`, so they all
understand the same words:

* yes: "yes", "yeah", "ok", "sure", "go ahead", "do it", "confirm",
  "Yes, confirming open Chrome." (speech often adds words), and Tamil /
  Thanglish "seri", "sari", "aama", "podu", "pannu", "ok pannu";
* no: "no", "nope", "cancel", "stop", "don't", "wait", "venam", "vendam",
  "illa", "beda";
* anything else (``None``) is *not* an answer: it is a new request. Callers
  cancel what was waiting and handle the new words normally, so one missed
  "yes" can never trap the conversation behind the same question.

The decision is made on the first words only. "No, don't shut it down" is a
no; "yes but no" is a no too, because any "no" word wins over a "yes" -- for
a risky action a doubtful answer must not run it.
"""

from __future__ import annotations

import re
from typing import Literal

Consent = Literal["yes", "no"]

YES_WORDS = frozenset(
    {
        "yes", "y", "yeah", "yea", "yep", "yup", "ya", "yah", "sure", "ok", "okay",
        "k", "confirm", "confirmed", "confirming", "approve", "approved", "proceed",
        "continue", "resume", "affirmative", "absolutely", "definitely", "alright",
        # Tamil / Thanglish / Hindi / Kannada
        "seri", "sari", "sariya", "aama", "ama", "aamaa", "podu", "pannu", "haan",
        "ha", "haa", "houdu",
    }
)
YES_PHRASES = (
    "go ahead", "do it", "go for it", "please do", "of course", "that's right",
    "thats right", "you can", "carry on", "ok pannu", "seri pannu",
)
NO_WORDS = frozenset(
    {
        "no", "n", "nope", "nah", "cancel", "cancelled", "stop", "don't", "dont",
        "deny", "denied", "never", "negative", "wait", "abort", "halt", "not",
        # Tamil / Thanglish / Hindi / Kannada
        "venam", "vendam", "vendaam", "venaam", "illa", "illai", "beda", "nahi", "mat",
    }
)
NO_PHRASES = ("never mind", "nevermind", "do not", "hold on", "not now")

#: Only this many words are read: an answer is short; a long sentence that
#: happens to start with "ok" ("ok what is the weather in Salem today") is a
#: new request, not consent.
MAX_ANSWER_WORDS = 7
_LEAD = ("hey grandpa", "hi grandpa", "grandpa")


def _words(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s']", " ", str(text or "").casefold())
    words = cleaned.split()
    joined = " ".join(words)
    for lead in _LEAD:
        if joined.startswith(lead + " ") or joined == lead:
            words = words[len(lead.split()):]
            break
    return words


def read_consent(text: str) -> Consent | None:
    """``"yes"``, ``"no"`` or ``None`` (not an answer: a new request)."""
    words = _words(text)
    if not words:
        return None
    joined = " ".join(words)
    head = words[:3]
    said_no = any(w in NO_WORDS for w in words[:MAX_ANSWER_WORDS]) or any(
        joined.startswith(p) or f" {p}" in f" {joined}" for p in NO_PHRASES
    )
    starts_no = head[0] in NO_WORDS or any(joined.startswith(p) for p in NO_PHRASES)
    if starts_no:
        return "no"
    starts_yes = head[0] in YES_WORDS or any(joined.startswith(p) for p in YES_PHRASES)
    if not starts_yes:
        return None
    if said_no:
        return "no"  # "yes... no wait": doubtful, so no
    if len(words) > MAX_ANSWER_WORDS:
        return None  # a long new request that happens to start with "ok"
    return "yes"


def is_yes(text: str) -> bool:
    return read_consent(text) == "yes"


__all__ = ["Consent", "is_yes", "read_consent"]
