"""Lightweight cleanup for assistant-facing text.

The goal is to remove obvious model artifacts without censoring useful
technical answers. Keep this module dependency-free so CLI, server, and engine
paths can all use it safely.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

DEFAULT_FALLBACK = "I couldn't produce a clean response. Please try again."
GENERATION_ERROR_MESSAGE = "Sorry, generation failed. Please try again."
LOCAL_ACTION_ERROR_MESSAGE = "I couldn't complete that local action."

_THINK_BLOCK_RE = re.compile(
    r"<\s*(think|thinking|analysis|reasoning)\s*>.*?<\s*/\s*\1\s*>\s*",
    re.IGNORECASE | re.DOTALL,
)
_BARE_END_THINK_RE = re.compile(
    r"^.*?<\s*/\s*(think|thinking|analysis|reasoning)\s*>\s*",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(
    r"</?\s*(think|thinking|analysis|reasoning)\s*>",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"[ \t\f\v]+")
_PARAGRAPH_GAP_RE = re.compile(r"\n{3,}")
_SENTENCE_RE = re.compile(r"([^.!?。！？\n]+[.!?。！？])")

_REASONING_LINE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(okay|alright),?\s+the user (asked|wants|is asking)\b",
        r"^\s*the user (asked|wants|is asking)\b",
        r"^\s*let me (think|reason|figure|draft|structure|check)\b",
        r"^\s*i should\b",
        r"^\s*i need to\b",
        r"^\s*first,?\s+i\b",
        r"^\s*make sure\b",
        r"^\s*check if\b",
        r"^\s*we need\b",
        r"^\s*hidden reasoning\b",
        r"^\s*internal reasoning\b",
        r"^\s*chain[- ]of[- ]thought\b",
    )
)
_ALWAYS_REASONING_LINE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(okay|alright),?\s+the user (asked|wants|is asking)\b",
        r"^\s*the user (asked|wants|is asking)\b",
        r"^\s*let me (think|reason|figure|draft|structure|check)\b",
        r"^\s*hidden reasoning\b",
        r"^\s*internal reasoning\b",
        r"^\s*chain[- ]of[- ]thought\b",
    )
)


def clean_assistant_response(
    text: object,
    *,
    fallback: str = DEFAULT_FALLBACK,
    max_chars: int = 8000,
) -> str:
    """Return user-facing assistant text with common model artifacts removed."""

    if text is None:
        return fallback
    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _THINK_BLOCK_RE.sub("", cleaned)
    cleaned = _BARE_END_THINK_RE.sub("", cleaned)
    cleaned = _TAG_RE.sub("", cleaned)
    cleaned = _strip_reasoning_preface(cleaned)
    cleaned = _drop_reasoning_lines(cleaned)
    cleaned = _normalise_whitespace(cleaned)
    cleaned = _collapse_duplicate_paragraphs(cleaned)
    cleaned = _collapse_duplicate_sentences(cleaned)
    cleaned = _trim_repeated_tail(cleaned)
    cleaned = _normalise_whitespace(cleaned)
    cleaned = _limit_length(cleaned, max_chars=max_chars)
    return cleaned or fallback


def clean_error_message(
    text: object,
    *,
    fallback: str = GENERATION_ERROR_MESSAGE,
) -> str:
    """Summarize an error for normal chat without exposing stack traces."""

    if text is None:
        return fallback
    message = str(text).strip()
    if not message:
        return fallback
    if "\n" in message or "Traceback" in message or "File \"" in message:
        return fallback
    message = clean_assistant_response(message, fallback=fallback, max_chars=240)
    if len(message) > 240:
        return fallback
    return message


def _normalise_whitespace(text: str) -> str:
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return _PARAGRAPH_GAP_RE.sub("\n\n", "\n".join(lines)).strip()


def _strip_reasoning_preface(text: str) -> str:
    if "</think>" not in text.lower() and not _looks_like_reasoning_heavy(text):
        return text
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) < 2:
        return text
    first_clean_index = 0
    for idx, paragraph in enumerate(paragraphs[:12]):
        if _contains_reasoning_marker(paragraph):
            first_clean_index = idx + 1
            continue
        if first_clean_index and len(paragraph.split()) >= 4:
            break
    if first_clean_index:
        return "\n\n".join(paragraphs[first_clean_index:])
    return text


def _drop_reasoning_lines(text: str) -> str:
    reasoning_heavy = _looks_like_reasoning_heavy(text)
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and any(
            pattern.search(stripped) for pattern in _ALWAYS_REASONING_LINE_PATTERNS
        ):
            continue
        if reasoning_heavy and stripped and any(
            pattern.search(stripped) for pattern in _REASONING_LINE_PATTERNS
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def _looks_like_reasoning_heavy(text: str) -> bool:
    paragraphs = _split_paragraphs(text)
    hits = 0
    for paragraph in paragraphs[:8]:
        if any(pattern.search(paragraph) for pattern in _REASONING_LINE_PATTERNS):
            hits += 1
    return hits >= 2


def _contains_reasoning_marker(text: str) -> bool:
    return any(pattern.search(text) for pattern in _REASONING_LINE_PATTERNS)


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _collapse_duplicate_paragraphs(text: str) -> str:
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return text.strip()
    kept: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        key = _dedupe_key(paragraph)
        if key in seen:
            continue
        kept.append(paragraph)
        seen.add(key)
    return "\n\n".join(kept)


def _collapse_duplicate_sentences(text: str) -> str:
    sentences = _SENTENCE_RE.findall(text)
    if len(sentences) < 2:
        return text
    result = text
    for sentence in _consecutive_duplicates(sentences):
        sentence_text = sentence.strip()
        escaped = re.escape(sentence_text)
        previous = None
        while previous != result:
            previous = result
            result = re.sub(
                rf"{escaped}\s+{escaped}",
                sentence_text,
                result,
            )
    return result.strip()


def _consecutive_duplicates(items: Iterable[str]) -> set[str]:
    duplicates: set[str] = set()
    previous = ""
    for item in items:
        key = _dedupe_key(item)
        if key and key == _dedupe_key(previous):
            duplicates.add(item)
        previous = item
    return duplicates


def _trim_repeated_tail(text: str) -> str:
    stripped = text.rstrip()
    for unit_len in range(1, 25):
        if len(stripped) < unit_len * 8:
            continue
        unit = stripped[-unit_len:]
        if not unit.strip():
            continue
        repeats = 0
        index = len(stripped)
        while index >= unit_len and stripped[index - unit_len : index] == unit:
            repeats += 1
            index -= unit_len
        if repeats >= 8:
            return stripped[:index].rstrip()
    return text


def _limit_length(text: str, *, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text.strip()
    clipped = text[:max_chars].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end > max_chars * 0.6:
        clipped = clipped[: sentence_end + 1]
    return clipped.rstrip() + "..."


def _dedupe_key(text: str) -> str:
    return re.sub(r"\W+", "", text).casefold()
