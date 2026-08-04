from __future__ import annotations

from grandpa.response_cleanup import clean_assistant_response, clean_error_message


def test_removes_full_think_block():
    text = (
        "<think>I should reason privately.</think>\nPython is a programming language."
    )

    assert clean_assistant_response(text) == "Python is a programming language."


def test_removes_bare_reasoning_before_end_tag():
    text = (
        "Okay, the user asked about Python.\n"
        "I should explain it simply.\n"
        "</think>\n"
        "Python is a high-level programming language."
    )

    assert (
        clean_assistant_response(text) == "Python is a high-level programming language."
    )


def test_removes_reasoning_preface_without_censoring_answer():
    text = (
        "Okay, the user asked what Python is.\n\n"
        "I should keep this concise.\n\n"
        "Python is a high-level programming language used for automation, web apps, data work, and AI."
    )

    assert clean_assistant_response(text).startswith("Python is a high-level")


def test_collapses_duplicate_paragraphs_and_sentences():
    text = "Opening Chrome.\n\nOpening Chrome.\n\nReady. Ready. Ready."

    assert clean_assistant_response(text) == "Opening Chrome.\n\nReady."


def test_trims_repeated_malformed_tail():
    text = "Python is useful." + ("文量" * 20)

    assert clean_assistant_response(text) == "Python is useful."


def test_preserves_legitimate_technical_explanation():
    text = "I should mention this in code comments only when the logic is not obvious."

    assert clean_assistant_response(text) == text


def test_error_message_hides_tracebacks():
    traceback = 'Traceback (most recent call last):\n  File "x.py", line 1'

    assert (
        clean_error_message(traceback) == "Sorry, generation failed. Please try again."
    )
