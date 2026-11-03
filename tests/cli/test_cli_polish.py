"""No emoji, a clock the model never answers, and colours that were measured.

Three defects:

* Every reply ended with an emoji. A system-prompt instruction is layer one
  and is not reliable, so there is a render-time strip behind it.
* "what is time ?" asked at 2:24 pm was answered "3:45 pm" by a model with no
  clock. The deterministic layer existed and its regexes missed the plainest
  phrasings; the HTTP route had no such layer at all.
* The numbered list markers were cyan, so structure looked like content and
  competed with the text beside it.
"""

from __future__ import annotations

import inspect
import re

import pytest

from grandpa.cli import theme
from grandpa.core.runtime_context import (
    answer_datetime,
    get_runtime_context,
    handle_datetime_intent,
    parse_datetime_intent,
)
from grandpa.response_cleanup import (
    _EMOJI_RE,
    clean_assistant_response,
    strip_emoji,
)

GROUNDS = ("#0c0c0c", "#1e1e1e", "#181818")


def _contrast(one: str, two: str) -> float:
    def channel(value: float) -> float:
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(colour: str) -> float:
        raw = colour.lstrip("#")
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    a, b = luminance(one), luminance(two)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _worst(colour: str) -> float:
    return min(_contrast(colour, ground) for ground in GROUNDS)


# --- emoji ------------------------------------------------------------------

EMOJI_REPLIES = [
    "Hello there! \U0001f642",
    "Nice to meet you \U0001f44b\U0001f3fc",
    "Great ✅ done ❌ now",
    "Congrats \U0001f389✨ ⭐",
    "Family: ❤️",
    "Flag \U0001f1ee\U0001f1f3 here",
    "Love ♥ it",
    "Peace ✌",
    "Heavy tick ✔ heavy cross ✖",
    "Smiley ☺",
]

FURNITURE = [
    "Box ─═║ and block ██",  # tables and the logo
    "Spinner ⠋⠙⠹",  # Braille, not emoji
    "Arrow a → b",
    "Dash — bullet • ellipsis …",
    "Warning ⚠ scales ⚖ tick ✓ cross ✕",
    "Tamil தமிழ் and ZWJ क‍ष",
]


@pytest.mark.parametrize("reply", EMOJI_REPLIES)
def test_the_strip_removes_emoji(reply: str) -> None:
    cleaned = strip_emoji(reply)

    assert _EMOJI_RE.search(cleaned) is None, f"survived: {cleaned!r}"
    # The words have to survive; a strip that eats the sentence is worse.
    # Characters, not whole words -- "Family:" carries a colon.
    assert any(character.isalpha() for character in cleaned)


@pytest.mark.parametrize("line", FURNITURE)
def test_the_strip_leaves_the_furniture_alone(line: str) -> None:
    """Box drawing, the logo's block, Braille spinner frames, arrows, the
    typographic punctuation, the four symbols this repo uses as symbols, and
    the zero-width joiner that Indic scripts need."""
    assert strip_emoji(line) == line


def test_the_zero_width_joiner_is_never_stripped() -> None:
    """It joins emoji sequences and it is load-bearing in Devanagari and
    Tamil. Stripping it would corrupt a Hindi or Tamil name, so the
    pictographs around it go and it stays."""
    assert "‍" in strip_emoji("क‍ष \U0001f642")


def test_a_bare_text_presentation_emoji_is_caught() -> None:
    """U+2764 defaults to TEXT presentation, so it carries no U+FE0F.

    The first version of the ranges removed the variation selector and left
    the heart, which is still an emoji to the person reading it.
    """
    assert strip_emoji("Family: ❤️") == "Family:"
    assert strip_emoji("Family: ❤") == "Family:"


def test_the_strip_runs_inside_the_shared_cleanup() -> None:
    """clean_assistant_response is the chokepoint every path already uses --
    chat, voice, the adapter and the panel -- so the strip is there rather
    than at each caller."""
    assert clean_assistant_response("Hi there! \U0001f642") == "Hi there!"


def test_trailing_space_is_not_left_behind() -> None:
    assert not strip_emoji("Thanks! \U0001f60a").endswith(" ")


def test_the_system_prompt_forbids_emoji() -> None:
    """Layer one. Not sufficient on its own, which is why layer two exists."""
    from grandpa.core.config import GrandpaConfig
    from grandpa.prompt.identity import GENERAL_CONVERSATION_PROMPT

    assert "emoji" in GENERAL_CONVERSATION_PROMPT.casefold()
    assert "emoji" in GrandpaConfig().agent.default_system_prompt.casefold()


def test_grandpa_does_not_emit_emoji_in_its_own_strings() -> None:
    """The strip catches what the MODEL says. These are what the product says.

    Checked over the whole package rather than the files that happened to have
    them, so a new one cannot be added quietly.
    """
    from pathlib import Path

    keep = {0x2696, 0x26A0, 0x2713, 0x2715}
    offenders: list[str] = []
    for path in sorted(Path("src/grandpa").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.split("\n"), 1):
            if line.lstrip().startswith("#"):
                continue  # a comment is not output
            found = [
                char
                for char in line
                if ord(char) not in keep and _EMOJI_RE.match(char)
            ]
            if found:
                offenders.append(f"{path}:{number} {found!r}")

    assert offenders == [], "emoji in Grandpa's own strings: " + "; ".join(offenders)


# --- the clock --------------------------------------------------------------

PLAIN_TIME = [
    "what is time ?",
    "what is time",
    "time now",
    "what is the time?",
    "whats the time",
    "what time is it",
    "time",
    "the time",
    "tell me the time please",
]

PLAIN_DATE = [
    "what's the date",
    "today date",
    "date today",
    "what is the date ?",
    "what day is it",
    "what day",
    "which day",
]


@pytest.mark.parametrize("phrasing", PLAIN_TIME)
def test_the_plain_time_phrasings_are_intercepted(phrasing: str) -> None:
    """Each of these used to reach a model with no clock.

    Asked "what is time ?" at 2:24 pm it answered 3:45 pm, which it invented.
    """
    assert parse_datetime_intent(phrasing) == "time", f"{phrasing!r} fell through"


@pytest.mark.parametrize("phrasing", PLAIN_DATE)
def test_the_plain_date_phrasings_are_intercepted(phrasing: str) -> None:
    assert parse_datetime_intent(phrasing) == "date", f"{phrasing!r} fell through"


@pytest.mark.parametrize("suffix", ["", " ", "?", " ?", "  ?  ", "!", "."])
def test_punctuation_and_trailing_space_do_not_matter(suffix: str) -> None:
    """Stripping "?" from "what is time ?" left "what is time " with a
    trailing space, and an anchored pattern missed it. Whitespace is collapsed
    after punctuation is removed, not before."""
    assert parse_datetime_intent(f"what is time{suffix}") == "time"


@pytest.mark.real_actions(
    reason="reads the system clock through the real answer_datetime; it only "
    "formats datetime.now() and touches nothing on the machine"
)
def test_the_answer_comes_from_the_system_clock() -> None:
    context = get_runtime_context()
    answer = handle_datetime_intent("what is time")

    assert answer is not None
    assert context["local_time"] in answer
    assert context["local_date"] in answer
    assert answer == answer_datetime("time")


@pytest.mark.parametrize(
    "phrasing",
    ["how many days until Christmas", "hello there", "what is the weather"],
)
def test_a_question_that_is_not_about_the_clock_still_reaches_the_model(
    phrasing: str,
) -> None:
    """The interception has to be narrow. A date-adjacent question the clock
    cannot answer must not be swallowed by it."""
    assert parse_datetime_intent(phrasing) is None


def test_chat_answers_the_clock_before_the_model() -> None:
    from grandpa.cli import chat_cmd

    source = inspect.getsource(chat_cmd.chat.callback)
    clock_at = source.index("parse_datetime_intent")
    model_at = source.index("agent.run(")

    assert clock_at < model_at, "the clock must be decided before the model is asked"
    # And the branch must stop the turn, not fall through into the model.
    assert "continue" in source[clock_at:model_at]


def test_the_http_route_answers_the_clock_before_the_model() -> None:
    """This route had no deterministic date layer at all."""
    from pathlib import Path

    source = Path("src/grandpa/server/routes.py").read_text(encoding="utf-8")

    assert "handle_datetime_intent" in source
    assert source.index("handle_datetime_intent") < source.index(
        "handle_memory_command(effective_user_text)"
    )


# --- the palette ------------------------------------------------------------

MEANING = [
    ("STRUCTURE", theme.STRUCTURE),
    ("ASSISTANT", theme.ASSISTANT),
    ("THINKING", theme.THINKING),
    ("WARNING", theme.WARNING),
    ("ERROR", theme.ERROR),
    ("ACTION", theme.ACTION),
    ("SUCCESS", theme.SUCCESS),
    ("VOICE", theme.VOICE),
    ("ACCENT", theme.ACCENT),
    ("INLINE_CODE", theme.INLINE_CODE),
    ("TEXT_ACCENT", theme.TEXT_ACCENT),
]


@pytest.mark.parametrize("name,colour", MEANING)
def test_meaning_carrying_colours_clear_aa(name: str, colour: str) -> None:
    """4.5:1 on every ground the CLI draws on, including the picker's."""
    assert _worst(colour) >= 4.5, f"{name} {colour} is {_worst(colour):.2f}:1"


def test_dim_structure_clears_three_to_one_and_is_quieter_than_body() -> None:
    """The list markers. Quieter than body text was the requirement, and a
    tint toward white can only make a colour brighter -- hence shade()."""
    assert _worst(theme.STRUCTURE_DIM) >= 3.0
    assert _worst(theme.STRUCTURE_DIM) < _worst(theme.STRUCTURE)


def test_the_list_markers_are_structural_not_blue() -> None:
    """The immediate complaint: the 1 2 3 4 5 of a names reply were cyan and
    fought the names beside them."""
    for key in ("markdown.item.number", "markdown.item.bullet", "markdown.list"):
        style = theme.CHAT_THEME.styles[key]
        assert style.color.triplet.hex.lower() == theme.STRUCTURE_DIM.lower(), key
        assert not style.bold, key


def test_the_ramp_runs_both_ways() -> None:
    # Case-insensitively: the bases are written in the orb's own uppercase and
    # tint/shade emit lowercase. Same colour either way.
    assert theme.tint(theme.BLUE, 0).lower() == theme.BLUE.lower()
    assert theme.tint(theme.BLUE, 100) == "#ffffff"
    assert theme.shade(theme.BLUE, 0).lower() == theme.BLUE.lower()
    assert theme.shade(theme.BLUE, 100) == "#000000"


def test_every_palette_base_is_one_of_the_orbs_seven() -> None:
    assert set(theme.PALETTE.values()) == {
        "#E5E7EB",
        "#168BFF",
        "#FFD21F",
        "#FF3B45",
        "#A855F7",
        "#22C55E",
        "#FF922B",
    }


def test_the_cli_carries_no_hex_literals_outside_the_theme() -> None:
    """A colour written anywhere else is a colour nobody can re-measure."""
    from pathlib import Path

    pattern = re.compile(r"#[0-9a-fA-F]{6}")
    offenders = []
    for path in sorted(Path("src/grandpa/cli").rglob("*.py")):
        if path.name == "theme.py":
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").split("\n"), 1
        ):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"{path}:{number}")

    assert offenders == [], f"hex literals outside theme.py: {offenders}"


def test_inline_code_is_kept_and_why() -> None:
    """Checked against the palette before being kept: Green clears 4.5:1 and
    Blue clears it, and both already mean something else -- success and
    Grandpa's label. Nothing in the seven is in the cyan range."""
    assert theme.INLINE_CODE not in set(theme.PALETTE.values())
    assert _worst(theme.INLINE_CODE) >= 4.5
    assert theme.INLINE_CODE != theme.SUCCESS
    assert theme.INLINE_CODE != theme.ASSISTANT
