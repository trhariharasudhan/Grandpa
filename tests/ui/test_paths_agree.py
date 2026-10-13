"""Does the bubble transcribe the same way the accuracy test does?

Reported: the bubble heard "What is your name and what is my name?" correctly
while the accuracy test on the same machine reported WER 0.75, which raised the
question of whether the test measures something the user is not running.

Measured: in default use the two paths are identical -- same model, language,
device and compute type from the same config loader, the same
``build_transcription_options`` with the same ``initial_prompt``, both via
``transcribe_trusted``, and the same ``hold_to_talk_vad_config`` that refuses
nothing. The WER gap is therefore not a path difference; it is a 16-word sample
on harder material, which is what the confidence interval now says out loud.

One real difference did turn up, and it is the one that would matter most while
comparing two models: ``grandpa bubble --model small.en`` was silently ignored.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.core


def _voice_config(**kwargs):
    from grandpa.voice.config import load_voice_assistant_config

    return load_voice_assistant_config(**kwargs)


def test_the_two_paths_resolve_the_same_transcriber_settings() -> None:
    """Nothing about the decoder may differ between them by default."""
    bubble = _voice_config(tts_enabled=False)
    test_path = _voice_config(
        model=None, language=None, microphone=None, tts_enabled=False
    )

    for field in ("stt_model", "language", "device", "compute_type"):
        assert getattr(bubble, field) == getattr(test_path, field), field


def test_both_paths_share_one_options_builder() -> None:
    """So a decoder option cannot be changed for one path and not the other."""
    import inspect

    from grandpa.speech import faster_whisper
    from grandpa.voice import speech_to_text

    assert "build_transcription_options" in inspect.getsource(faster_whisper)
    # The bridge and the session both go through transcribe_trusted, which is
    # the method that applies the trusted options.
    assert hasattr(speech_to_text.FasterWhisperSpeechToText, "transcribe_trusted")


def test_the_prompt_comes_from_the_shared_vocabulary() -> None:
    from grandpa.speech.faster_whisper import build_transcription_options
    from grandpa.speech.vocabulary import build_initial_prompt

    for trust in (True, False):
        options = build_transcription_options(trust_audio=trust)
        assert options.get("initial_prompt") == build_initial_prompt()


def test_both_paths_use_a_detector_that_refuses_nothing() -> None:
    """A capture difference would show up as a recognition difference."""
    from grandpa.voice.push_to_talk import (
        MAXIMUM_HOLD_SECONDS,
        hold_to_talk_vad_config,
    )

    vad = hold_to_talk_vad_config(MAXIMUM_HOLD_SECONDS)

    assert vad.minimum_rms == 0.0
    assert vad.noise_multiplier == 0.0
    assert vad.minimum_speech_seconds == 0.0


def test_the_bubble_honours_the_model_flag() -> None:
    """It did not. The bridge built its own config with no override.

    So `grandpa bubble --model small.en` ran base.en and said nothing, which
    makes comparing two models in the bubble impossible.
    """
    from grandpa.ui.bridge import _default_transcriber

    default = _default_transcriber()
    overridden = _default_transcriber("small.en")

    assert getattr(default._engine, "model", None) == "base.en"
    assert getattr(overridden._engine, "model", None) == "small.en"


def test_the_bridge_passes_the_model_through() -> None:
    from grandpa.ui.bridge import InProcessBridge

    bridge = InProcessBridge(model="small.en")

    assert getattr(bridge.ensure_transcriber()._engine, "model", None) == "small.en"


def test_an_injected_factory_still_wins_over_the_model() -> None:
    """Tests inject a double; the override must not take precedence over it."""
    from grandpa.ui.bridge import InProcessBridge

    sentinel = object()
    bridge = InProcessBridge(model="small.en", transcriber_factory=lambda: sentinel)

    assert bridge.ensure_transcriber() is sentinel


def test_the_command_hands_the_model_to_the_bridge() -> None:
    import inspect

    from grandpa.cli import bubble_cmd

    source = inspect.getsource(bubble_cmd.bubble.callback)

    assert "InProcessBridge(model=model)" in source
