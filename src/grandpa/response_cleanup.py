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

#: Codepoint ranges stripped from anything shown to a person.
#:
#: Grandpa is text only. A system-prompt instruction is layer one and is not
#: reliable -- a model that ignores it still puts a smiley on the end of every
#: reply -- so this is layer two, and it runs at render time where nothing can
#: get past it.
#:
#: Ranges, not a hand-written list of characters, so a new emoji in a future
#: Unicode release is covered without anyone editing anything.
#:
#: STRIPPED:
#:   1F000-1FAFF  the pictographic planes entire -- emoticons, pictographs,
#:                transport, supplemental, extended-A, and the regional
#:                indicators at 1F1E6-1F1FF that make flags
#:   FE0F         variation selector-16, the "render the previous character as
#:                an emoji" marker. Meaningless once its base is gone, and
#:                harmless to remove elsewhere
#:   2B00-2BFF    misc symbols and arrows, which is where the star and the
#:                large coloured arrows live. This repo uses none of it
#:   the default-emoji-presentation members of 2600-27BF -- the subranges
#:                below. Unicode's own property, written as ranges rather than
#:                as a list of glyphs
#:
#: DELIBERATELY LEFT ALONE, each because this repo uses it as furniture and
#: none of it is an emoji:
#:   2500-257F    box drawing, 570 uses -- every table and panel border
#:   2580-259F    block elements, 168 uses -- the GRANDPA logo is built of
#:                U+2588
#:   2800-28FF    Braille, 10 uses -- the spinner frames are Braille cells,
#:                not emoji
#:   2190-21FF    arrows, 31 uses of U+2192 in help text
#:   2000-206F    general punctuation, 336 uses -- en and em dashes, the
#:                typographic apostrophe, the bullet, the ellipsis
#:   25A0-25FF    geometric shapes, 3 uses
#:   200D         the zero-width joiner. It joins emoji sequences, and it is
#:                also load-bearing in Devanagari and Tamil, which this
#:                product supports. Stripping it would corrupt a Hindi or
#:                Tamil name, so it stays and the pictographs around it go
#:   the non-emoji members of 2600-27BF: U+2696, U+26A0, U+2713, U+2715 are
#:                used as plain scales/warning/tick/cross marks
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0xFE0F, 0xFE0F),
    (0x2B00, 0x2BFF),
    # Default-emoji-presentation inside Misc Symbols and Dingbats.
    (0x231A, 0x231B),
    (0x23E9, 0x23EC),
    (0x23F0, 0x23F0),
    (0x23F3, 0x23F3),
    (0x25FD, 0x25FE),
    (0x2614, 0x2615),
    (0x2648, 0x2653),
    (0x267F, 0x267F),
    (0x2693, 0x2693),
    (0x26A1, 0x26A1),
    (0x26AA, 0x26AB),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26CE, 0x26CE),
    (0x26D4, 0x26D4),
    (0x26EA, 0x26EA),
    (0x26F2, 0x26F3),
    (0x26F5, 0x26F5),
    (0x26FA, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2705, 0x2705),
    (0x270A, 0x270B),
    (0x2728, 0x2728),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2795, 0x2797),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    # Emoji whose DEFAULT presentation is text, so they carry no FE0F and the
    # subranges above miss them -- a bare U+2764 heart survived the first
    # version of this and is still an emoji to the person reading it. These
    # are Unicode's Emoji property, as ranges, minus the four this repo uses
    # as furniture: U+2696 scales, U+26A0 warning, U+2713 tick, U+2715 cross.
    (0x2600, 0x2604),
    (0x260E, 0x260E),
    (0x2611, 0x2611),
    (0x2618, 0x2618),
    (0x261D, 0x261D),
    (0x2620, 0x2620),
    (0x2622, 0x2623),
    (0x2626, 0x2626),
    (0x262A, 0x262A),
    (0x262E, 0x262F),
    (0x2638, 0x263A),
    (0x2640, 0x2640),
    (0x2642, 0x2642),
    (0x265F, 0x2660),
    (0x2663, 0x2663),
    (0x2665, 0x2666),
    (0x2668, 0x2668),
    (0x267B, 0x267B),
    (0x267E, 0x267E),
    (0x2692, 0x2692),
    (0x2694, 0x2695),
    (0x2697, 0x2699),
    (0x269B, 0x269C),
    (0x26A7, 0x26A7),
    (0x26B0, 0x26B1),
    (0x26C8, 0x26C8),
    (0x26CF, 0x26CF),
    (0x26D1, 0x26D1),
    (0x26D3, 0x26D3),
    (0x26E9, 0x26E9),
    (0x26F0, 0x26F1),
    (0x26F4, 0x26F4),
    (0x26F7, 0x26F9),
    (0x2702, 0x2702),
    (0x2708, 0x2709),
    (0x270C, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x2763, 0x2764),
    (0x27A1, 0x27A1),
)

_EMOJI_RE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _EMOJI_RANGES) + "]"
)


def strip_emoji(text: str) -> str:
    """Remove emoji, leaving the furniture alone.

    See :data:`_EMOJI_RANGES` for exactly what goes and what stays. Spacing is
    tidied afterwards, because an emoji is usually preceded by a space that
    would otherwise be left dangling at the end of a sentence.
    """
    without = _EMOJI_RE.sub("", text)
    if without == text:
        return text
    # " Hello there 🙂" -> "Hello there", not "Hello there ".
    without = re.sub(r"[ \t]+([,.!?;:])", r"\1", without)
    without = re.sub(r"[ \t]{2,}", " ", without)
    return "\n".join(line.rstrip() for line in without.split("\n"))


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
    cleaned = strip_emoji(cleaned)
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
    if "\n" in message or "Traceback" in message or 'File "' in message:
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
        if (
            reasoning_heavy
            and stripped
            and any(pattern.search(stripped) for pattern in _REASONING_LINE_PATTERNS)
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
