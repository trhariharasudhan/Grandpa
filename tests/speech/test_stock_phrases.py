"""Whisper's silence phrases are not commands (Captain's test, line 17)."""

from __future__ import annotations

import pytest

from grandpa.speech.faster_whisper import is_stock_whisper_phrase
from grandpa.speech.vocabulary import build_initial_prompt


@pytest.mark.parametrize(
    "text",
    [
        "You can find the link in the description box below.",
        "Thanks for watching!",
        "Thank you for watching and see you next time.",
        "Please like and subscribe.",
        "you",
        "Thank you.",
    ],
)
def test_silence_phrases_are_dropped(text: str) -> None:
    assert is_stock_whisper_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "Hey Grandpa.",
        "Thank you Grandpa",
        "search YouTube for subscribe button tutorials",
        "open the link in the description",
        "What time is it?",
    ],
)
def test_real_requests_are_kept(text: str) -> None:
    assert not is_stock_whisper_phrase(text)


def test_command_words_bias_the_decoder() -> None:
    prompt = build_initial_prompt()
    for word in ("volume", "brightness", "weather", "lock", "shut down", "YouTube", "Bengaluru"):
        assert word in prompt
