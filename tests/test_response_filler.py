"""The filler backstop: what it strips, and what it must never touch.

Reported: "Let me know if you need anything else!" closing every single turn,
and "How can I assist you today?" after a question had already been asked.

The prompt is told not to write these. This is the second layer, the shape the
emoji work used -- an instruction the model usually follows, plus a strip for
the turns where it does not. The risk of a strip is that it eats an answer, so
the KEEP cases below are the more important half of this file.
"""

from __future__ import annotations

import pytest

from grandpa.response_cleanup import clean_assistant_response, strip_closing_filler

STRIP = [
    (
        "the reported closing, verbatim",
        "Your download speed is 90 Mbps. Let me know if you need anything else!",
        "Your download speed is 90 Mbps.",
    ),
    (
        "the reported closing, the variant from the measured run",
        "These tools give an idea of your performance. "
        "Let me know if you need help interpreting the results!",
        "These tools give an idea of your performance.",
    ),
    (
        "the reported opener, after a question was already asked",
        "How can I assist you today? Docker packages software into containers.",
        "Docker packages software into containers.",
    ),
    (
        "feel free to ask",
        "RAM is volatile. Feel free to ask if you want more detail.",
        "RAM is volatile.",
    ),
    (
        "hope this helps",
        "Press F2 to rename. I hope this helps!",
        "Press F2 to rename.",
    ),
    (
        "anything else",
        "The file is renamed. Is there anything else you would like to know?",
        "The file is renamed.",
    ),
    (
        "flattery",
        "Great question! Docker uses the host kernel.",
        "Docker uses the host kernel.",
    ),
    (
        "two of them stacked",
        "Done. Hope this helps! Let me know if you have any other questions.",
        "Done.",
    ),
]

# The half that matters more. Each of these contains a phrase that looks like
# filler but carries the answer, or is the whole message.
KEEP = [
    (
        "a sentence that happens to contain 'let me know' as content",
        "The installer will let me know when it finishes, but it does not log it.",
    ),
    (
        "'in summary' carries the point and is not stripped here",
        "ROM is permanent. In summary, RAM is temporary and ROM is not.",
    ),
    (
        "a question back to the user that is a real clarifying question",
        "Which drive did you mean, C or D?",
    ),
    (
        "an answer that is only an offer, where stripping leaves silence",
        "Let me know which file you meant.",
    ),
    (
        "the greeting reply to a greeting, which a real test caught",
        # The user typed "hi". "How can I assist you today?" is the message
        # here, not filler trailing an answer -- the complaint was about it
        # arriving AFTER a question had been asked.
        "Hello! How can I assist you today?",
    ),
    (
        "a greeting plus an offer and nothing else",
        "Sure! Let me know if you need anything else.",
    ),
    (
        "help as the subject of the answer",
        "If you need any help with Docker, the official docs cover installation.",
    ),
]


@pytest.mark.parametrize(("label", "text", "expected"), STRIP)
def test_closing_filler_is_removed(label: str, text: str, expected: str) -> None:
    assert strip_closing_filler(text).strip() == expected, label


@pytest.mark.parametrize(("label", "text"), KEEP)
def test_content_is_never_removed(label: str, text: str) -> None:
    result = strip_closing_filler(text).strip()

    assert result, f"{label}: stripped to nothing"
    # Every case here must come back whole. Some are returned untouched
    # because stripping would leave only a greeting or nothing at all; the
    # rest because they never matched in the first place.
    assert result == text.strip(), label


def test_the_backstop_runs_inside_the_real_cleanup() -> None:
    """Wired in, not just importable.

    A helper that is never called is the easiest kind of fix to believe in, so
    this goes through clean_assistant_response rather than the helper.
    """
    cleaned = clean_assistant_response(
        "Your speed is 90 Mbps. Let me know if you need anything else!"
    )

    assert cleaned == "Your speed is 90 Mbps."


def test_a_clean_reply_is_unchanged() -> None:
    text = "Docker packages software into containers. Images come from a Dockerfile."

    assert strip_closing_filler(text) == text
