"""Tests for Faster-Whisper speech backend."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grandpa.core.registry import SpeechRegistry
from grandpa.speech.faster_whisper import (
    FasterWhisperBackend,
    build_transcription_options,
    select_compute_type,
)
from grandpa.speech.vocabulary import build_initial_prompt


@pytest.fixture(autouse=True)
def _register_faster_whisper():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("faster-whisper"):
        SpeechRegistry.register_value("faster-whisper", FasterWhisperBackend)


def test_faster_whisper_backend_registers():
    """Backend registers itself in SpeechRegistry."""
    assert SpeechRegistry.contains("faster-whisper")


def test_faster_whisper_transcribe():
    """Transcribe returns a TranscriptionResult."""
    from grandpa.speech._stubs import TranscriptionResult

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = " Hello world"
    mock_segment.start = 0.0
    mock_segment.end = 1.2
    mock_segment.avg_logprob = -0.3

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    with patch(
        "grandpa.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        from grandpa.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend(model_size="base", device="cpu")
        result = backend.transcribe(b"fake audio bytes")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 1.5
        options = mock_model.transcribe.call_args.kwargs
        assert options == build_transcription_options(None)
        # The policy now carries a domain vocabulary prompt biasing Whisper
        # toward the app names Grandpa controls; it is no longer None.
        assert (
            options["initial_prompt"]
            == (CANONICAL_TRANSCRIPTION_OPTIONS["initial_prompt"])
        )
        assert options["condition_on_previous_text"] is False


#: The production decoding policy, pinned so drift has to be acknowledged.
#:
#: **The previous note here was wrong, and the error mattered.** It described
#: ``no_speech_threshold`` 0.6 -> 0.5 and ``log_prob_threshold`` -1.0 -> -0.85 as
#: "slightly more permissive speech gating". Both changes made it *stricter*, and
#: faster-whisper's rule is why::
#:
#:     should_skip = result.no_speech_prob > options.no_speech_threshold
#:     if (options.log_prob_threshold is not None
#:             and avg_logprob > options.log_prob_threshold):
#:         # don't skip if the logprob is high enough, despite the no_speech_prob
#:         should_skip = False
#:
#: Lowering ``no_speech_threshold`` makes *more* segments skip candidates, and
#: ``log_prob_threshold`` is the bar a segment must clear to be *rescued* -- so
#: raising it from -1.0 to -0.85 rescues fewer. Two changes believed to loosen
#: the gate both tightened it, and a user lost four rounds of voice work to it.
#:
#: Both are now faster-whisper's defaults, moved on measurement: real speech on
#: the reporting machine decoded at ``no_speech_prob`` 0.598, inside the 0.5-0.6
#: band that 0.5 puts at risk and 0.6 does not.
CANONICAL_TRANSCRIPTION_OPTIONS = {
    "beam_size": 1,
    "temperature": 0.0,
    "condition_on_previous_text": False,
    # Built from grandpa.speech.vocabulary, which the user can extend, so this
    # is composed rather than written out -- a hardcoded string here would pin
    # the default and make the setting untestable through this path.
    "initial_prompt": build_initial_prompt(),
    "vad_filter": False,
    "no_speech_threshold": 0.6,
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -1.0,
    "language": "en",
}


def test_canonical_transcription_options_are_explicit() -> None:
    assert build_transcription_options("en") == CANONICAL_TRANSCRIPTION_OPTIONS


def test_the_thresholds_are_faster_whispers_own_defaults() -> None:
    """Undercutting the library's defaults is what discarded real speech.

    Read from the installed signature rather than written down, so a library
    upgrade that moves them shows up here instead of silently diverging.
    """
    import inspect

    from faster_whisper import WhisperModel

    parameters = inspect.signature(WhisperModel.transcribe).parameters
    options = build_transcription_options("en")
    for name in ("no_speech_threshold", "log_prob_threshold",
                 "compression_ratio_threshold"):
        assert options[name] == parameters[name].default, name


def test_faster_whisper_closes_and_deletes_temp_audio_before_transcribe():
    mock_segment = MagicMock()
    mock_segment.text = " Hello"
    mock_segment.start = 0.0
    mock_segment.end = 0.5

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.9
    mock_info.duration = 0.5
    seen_paths: list[str] = []

    def fake_transcribe(path: str, **_kwargs):
        seen_paths.append(path)
        with open(path, "ab") as temp_audio:
            temp_audio.write(b"")
        return [mock_segment], mock_info

    mock_model = MagicMock()
    mock_model.transcribe.side_effect = fake_transcribe

    with patch("grandpa.speech.faster_whisper.WhisperModel", return_value=mock_model):
        backend = FasterWhisperBackend(model_size="base", device="cpu")
        result = backend.transcribe(b"fake audio bytes")

    assert result.text == "Hello"
    assert seen_paths
    assert not any(Path(path).exists() for path in seen_paths)


def test_faster_whisper_health_no_model():
    """Health returns False before model is loaded."""
    with patch(
        "grandpa.speech.faster_whisper.WhisperModel",
        new=None,
    ):
        from grandpa.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        backend._model = None
        assert backend.health() is False


def test_faster_whisper_supported_formats():
    """Backend supports standard audio formats."""
    with patch("grandpa.speech.faster_whisper.WhisperModel"):
        from grandpa.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        formats = backend.supported_formats()
        assert "wav" in formats
        assert "mp3" in formats
        assert "webm" in formats


def test_cpu_uses_non_float16_compute_type():
    assert select_compute_type("cpu", "auto") == "int8"
    assert select_compute_type("cpu", "float16") == "int8"


def test_float16_failure_retries_with_safe_compute_type():
    mock_model = MagicMock()

    with patch(
        "grandpa.speech.faster_whisper.WhisperModel",
        side_effect=[
            ValueError(
                "Requested float16 compute type, but the target device or backend do not support efficient float16 computation."
            ),
            mock_model,
        ],
    ) as whisper_model:
        backend = FasterWhisperBackend(
            model_size="base", device="cuda", compute_type="float16"
        )

        assert backend._ensure_model() is mock_model
        assert backend._compute_type == "int8"
        assert whisper_model.call_args_list[0].kwargs["compute_type"] == "float16"
        assert whisper_model.call_args_list[1].kwargs["compute_type"] == "int8"
