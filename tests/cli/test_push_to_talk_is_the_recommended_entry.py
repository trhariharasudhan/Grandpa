"""A new user must be pointed at the command that works.

Push-to-talk transcribed and routed real speech on the reporting machine twice
over, on the same microphone and in the same session where hands-free voice
answered "I could not understand" three times. Until hands-free is reliable, the
documentation and the command's own help should say which to reach for.

Asserted rather than left to a reader, because this is exactly the sort of
guidance that rots the moment someone edits the surrounding prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.cli.voice_cmd import voice

pytestmark = pytest.mark.core


def _readme() -> str:
    import grandpa

    path = Path(grandpa.__file__).parents[2] / "README.md"
    assert path.exists(), path
    return path.read_text(encoding="utf-8")


def test_the_readme_names_push_to_talk() -> None:
    readme = _readme()

    assert "voice push-to-talk" in readme


def test_the_readme_recommends_it_before_hands_free() -> None:
    """Order on the page is the recommendation a skimming reader takes."""
    readme = _readme()
    section = readme[readme.index("## Voice Assistant") :]

    push_to_talk_at = section.index("voice push-to-talk")
    hands_free_at = section.index("Hands-free mode")

    assert push_to_talk_at < hands_free_at, (
        "hands-free is introduced before push-to-talk, so a reader meets the "
        "unreliable path first"
    )


def test_the_readme_says_how_to_tell_the_two_faults_apart() -> None:
    """The diagnostic that saved four rounds: does push-to-talk work?"""
    readme = _readme()

    assert "could not understand" in readme
    assert "detection is at fault" in readme


def test_the_voice_help_points_at_push_to_talk() -> None:
    help_text = voice.callback.__doc__ or ""

    assert "push-to-talk" in help_text
    assert "push-to-talk" in help_text.split("\n")[2], (
        "the pointer must be in the first lines, not buried below"
    )


def test_the_voice_help_explains_why_hands_free_can_fail() -> None:
    help_text = voice.callback.__doc__ or ""

    assert "noise floor" in help_text or "threshold" in help_text
    assert "could not understand" in help_text


def test_push_to_talks_own_help_says_there_is_no_detection() -> None:
    help_text = voice.commands["push-to-talk"].callback.__doc__ or ""

    assert "No voice activity detection" in help_text


def test_the_vocabulary_setting_is_documented_where_a_user_looks() -> None:
    readme = _readme()

    assert "vocabulary" in readme
    assert "GRANDPA_VOICE_VOCABULARY" in readme
    assert "Harry" in readme, "the symptom is what a user searches for"
