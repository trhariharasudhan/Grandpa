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
#: Re-synced with build_transcription_options() after the policy was
#: deliberately retuned for a local voice assistant: greedy decoding
#: (beam_size 5 -> 1) for latency, a domain vocabulary prompt biasing Whisper
#: toward the application names Grandpa actually controls, and slightly more
#: permissive speech gating (no_speech_threshold 0.6 -> 0.5,
#: log_prob_threshold -1.0 -> -0.85).
CANONICAL_TRANSCRIPTION_OPTIONS = {
    "beam_size": 1,
    "temperature": 0.0,
    "condition_on_previous_text": False,
    "initial_prompt": (
        "Grandpa, Notepad, Chrome, Calculator, VS Code, Explorer, Settings, Terminal."
    ),
    "vad_filter": False,
    "no_speech_threshold": 0.5,
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -0.85,
    "language": "en",
}


def test_canonical_transcription_options_are_explicit() -> None:
    assert build_transcription_options("en") == CANONICAL_TRANSCRIPTION_OPTIONS


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
