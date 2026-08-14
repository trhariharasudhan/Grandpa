"""Unit tests for the grandpa_voice TTS backend."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from grandpa.core.registry import TTSRegistry
from grandpa.speech.grandpa_voice_tts import (
    GrandpaVoiceTTSBackend,
    GrandpaVoiceUnavailableError,
)
from grandpa.speech.kokoro_tts import KokoroTTSBackend


@pytest.fixture(autouse=True)
def registered_backends():
    if not TTSRegistry.contains("grandpa_voice"):
        TTSRegistry.register_value("grandpa_voice", GrandpaVoiceTTSBackend)
    if not TTSRegistry.contains("kokoro"):
        TTSRegistry.register_value("kokoro", KokoroTTSBackend)


def test_grandpa_voice_registration():
    """Verify backend is registered under grandpa_voice."""
    assert TTSRegistry.contains("grandpa_voice")
    backend_cls = TTSRegistry.get("grandpa_voice")
    assert backend_cls.__name__ == "GrandpaVoiceTTSBackend"
    assert TTSRegistry.contains("kokoro")


def test_available_voices():
    """Verify available voices returns grandpa."""
    backend = GrandpaVoiceTTSBackend()
    assert backend.available_voices() == ["grandpa"]


@patch("grandpa.speech.local_voice.f5_engine.LocalVoiceServiceClient")
def test_synthesize_success(mock_client_class):
    """Test successful synthesis using mocked client."""
    mock_client = mock_client_class.return_value
    mock_client.synthesize.return_value = b"fake-wav-audio"
    mock_client.health.return_value = True

    backend = GrandpaVoiceTTSBackend()
    result = backend.synthesize("hello test", voice_id="grandpa", speed=1.0)

    assert result.audio == b"fake-wav-audio"
    assert result.format == "wav"
    assert result.voice_id == "grandpa"
    assert result.metadata["backend"] == "grandpa_voice"
    assert mock_client_class.call_args.kwargs["synthesis_timeout_seconds"] == 600.0


@patch("grandpa.speech.local_voice.f5_engine.LocalVoiceServiceClient")
def test_health_check(mock_client_class):
    """Test health check online and offline states."""
    mock_client = mock_client_class.return_value

    backend = GrandpaVoiceTTSBackend()

    mock_client.health.return_value = True
    assert backend.health() is True

    mock_client.health.return_value = False
    assert backend.health() is False


@patch("grandpa.speech.local_voice.f5_engine.LocalVoiceServiceClient")
def test_synthesize_service_failure(mock_client_class):
    """Verify synthesis failure raises RuntimeError."""
    mock_client = mock_client_class.return_value
    mock_client.synthesize.side_effect = RuntimeError("connection refused")

    backend = GrandpaVoiceTTSBackend()

    with pytest.raises(
        GrandpaVoiceUnavailableError,
        match="Cloned voice synthesis is unavailable",
    ):
        backend.synthesize("hello fail")


def test_synthesize_empty_text():
    """Verify empty text returns empty audio without calling service."""
    backend = GrandpaVoiceTTSBackend()
    result = backend.synthesize("  ")
    assert result.audio == b""
