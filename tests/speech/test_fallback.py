"""Unit tests for the local-only TTS backend fallback cascade."""

from __future__ import annotations

import pytest

from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import TTSRegistry
from grandpa.speech.grandpa_voice_tts import GrandpaVoiceTTSBackend
from grandpa.speech.kokoro_tts import KokoroTTSBackend
from grandpa.voice.speech_output import SpeechOutputEngine


@pytest.fixture(autouse=True)
def registered_backends():
    if not TTSRegistry.contains("grandpa_voice"):
        TTSRegistry.register_value("grandpa_voice", GrandpaVoiceTTSBackend)
    if not TTSRegistry.contains("kokoro"):
        TTSRegistry.register_value("kokoro", KokoroTTSBackend)


def _config(backend: str = "grandpa_voice") -> GrandpaConfig:
    config = GrandpaConfig()
    config.tts.backend = backend
    config.tts.enabled = True
    return config


def test_grandpa_voice_healthy_is_selected(monkeypatch):
    monkeypatch.setattr(TTSRegistry.get("grandpa_voice"), "health", lambda self: True)
    monkeypatch.setattr(TTSRegistry.get("kokoro"), "health", lambda self: False)
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: _config())

    engine = SpeechOutputEngine()

    assert engine.best_available_engine() == "grandpa_voice"


def test_grandpa_voice_synthesis_failure_falls_back_to_pyttsx3(monkeypatch):
    grandpa_backend = TTSRegistry.get("grandpa_voice")
    monkeypatch.setattr(grandpa_backend, "health", lambda self: True)
    monkeypatch.setattr(
        grandpa_backend,
        "synthesize",
        lambda self, text: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: _config())
    monkeypatch.setattr(
        "grandpa.voice.speech_output.importlib.util.find_spec",
        lambda name: object() if name == "pyttsx3" else None,
    )
    spoken: list[str] = []
    monkeypatch.setattr(
        "grandpa.voice.speech_output._speak_with_pyttsx3",
        lambda text, **kwargs: spoken.append(text),
    )

    result = SpeechOutputEngine().speak("hello")

    assert result.status == "completed"
    assert result.engine == "pyttsx3"
    assert spoken == ["hello"]


def test_registered_backends_fail_then_pyttsx3_succeeds(monkeypatch):
    for name in ("grandpa_voice", "kokoro"):
        backend = TTSRegistry.get(name)
        monkeypatch.setattr(backend, "health", lambda self: True)
        monkeypatch.setattr(
            backend,
            "synthesize",
            lambda self, text: (_ for _ in ()).throw(RuntimeError("failed")),
        )
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: _config())
    monkeypatch.setattr(
        "grandpa.voice.speech_output.importlib.util.find_spec",
        lambda name: object() if name == "pyttsx3" else None,
    )
    spoken: list[str] = []
    monkeypatch.setattr(
        "grandpa.voice.speech_output._speak_with_pyttsx3",
        lambda text, **kwargs: spoken.append(text),
    )

    result = SpeechOutputEngine().speak("hello")

    assert result.status == "completed"
    assert result.engine == "pyttsx3"
    assert spoken == ["hello"]


def test_all_local_backends_fail_returns_text_only_without_crashing(monkeypatch):
    for name in ("grandpa_voice", "kokoro"):
        backend = TTSRegistry.get(name)
        monkeypatch.setattr(backend, "health", lambda self: True)
        monkeypatch.setattr(
            backend,
            "synthesize",
            lambda self, text: (_ for _ in ()).throw(RuntimeError("failed")),
        )
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: _config())
    monkeypatch.setattr(
        "grandpa.voice.speech_output.importlib.util.find_spec",
        lambda name: object() if name == "pyttsx3" else None,
    )
    monkeypatch.setattr(
        "grandpa.voice.speech_output._speak_with_pyttsx3",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    result = SpeechOutputEngine().speak("hello")

    assert result.status == "fallback"
    assert result.engine == "print_only"
    assert result.spoken_text == "hello"
    assert "grandpa_voice" in (result.error or "")
    assert "kokoro" in (result.error or "")
    assert "pyttsx3" in (result.error or "")


def test_edge_tts_is_not_an_automatic_offline_fallback(monkeypatch):
    for name in ("grandpa_voice", "kokoro"):
        monkeypatch.setattr(TTSRegistry.get(name), "health", lambda self: False)
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: _config("edge_tts"))
    monkeypatch.setattr(
        "grandpa.voice.speech_output.importlib.util.find_spec",
        lambda name: object() if name == "edge_tts" else None,
    )

    engine = SpeechOutputEngine()

    assert engine.available_local_engines() == ()
    assert engine.best_available_engine() == "print_only"
