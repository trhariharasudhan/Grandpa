"""Tests for the text_to_speech tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from grandpa.core.registry import ToolRegistry
from grandpa.speech.tts import TTSResult


@pytest.fixture(autouse=True)
def _register_text_to_speech():
    """Re-register after conftest's per-test registry reset.

    Registration is an import side effect (``@ToolRegistry.register``), and
    both that decorator and ``load_builtin_tools`` run exactly once per
    process. conftest clears ToolRegistry before every test, so whether the
    entry survives depended on this test being the first to import the module
    — it failed whenever any earlier test imported it first.

    Mirrors the existing ``_register_faster_whisper`` fixture in
    tests/speech/test_faster_whisper.py.
    """
    from grandpa.tools.text_to_speech import TextToSpeechTool

    if not ToolRegistry.contains("text_to_speech"):
        ToolRegistry.register_value("text_to_speech", TextToSpeechTool)


def test_tts_tool_registered():
    from grandpa.tools.text_to_speech import TextToSpeechTool

    assert ToolRegistry.contains("text_to_speech")
    assert ToolRegistry.get("text_to_speech") is TextToSpeechTool


def test_tts_tool_is_wired_into_the_builtin_loader():
    """The registry entry is only reachable in production via this list."""
    from grandpa.tools import _BUILTINS

    assert "text_to_speech" in _BUILTINS


def test_tts_tool_execute(tmp_path):
    from grandpa.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    mock_result = TTSResult(
        audio=b"fake-audio-data",
        format="mp3",
        voice_id="Grandpa",
        duration_seconds=2.5,
    )

    with patch("grandpa.tools.text_to_speech.TTSRegistry") as mock_registry:
        mock_backend_cls = MagicMock()
        mock_backend_cls.return_value.synthesize.return_value = mock_result
        mock_registry.contains.return_value = True
        mock_registry.get.return_value = mock_backend_cls

        result = tool.execute(
            text="Good morning sir.",
            voice_id="Grandpa",
            backend="cartesia",
            output_dir=str(tmp_path),
        )

    assert result.success is True
    assert "digest.mp3" in result.content
    assert (tmp_path / "digest.mp3").exists()
    assert (tmp_path / "digest.mp3").read_bytes() == b"fake-audio-data"


def test_tts_tool_empty_text():
    from grandpa.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    result = tool.execute(text="")
    assert result.success is False
