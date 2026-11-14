"""The two TTS defaults are one.

``load_config().tts.backend`` said ``kokoro`` while ``grandpa voice`` (and
``grandpa doctor``) resolved ``pyttsx3``. Both now read ``DEFAULT_TTS_BACKEND``
and the voice path follows ``[tts] backend`` from config.toml.
"""

from __future__ import annotations

import pytest

from grandpa.core import config as core_config
from grandpa.core.config import DEFAULT_TTS_BACKEND, GrandpaConfig
from grandpa.voice import config as voice_config


def test_default_is_pyttsx3():
    assert DEFAULT_TTS_BACKEND == "pyttsx3"
    assert GrandpaConfig().tts.backend == DEFAULT_TTS_BACKEND
    assert voice_config.VoiceAssistantConfig().tts_engine == DEFAULT_TTS_BACKEND


def test_voice_assistant_and_core_config_agree(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GRANDPA_VOICE_TTS_ENGINE", raising=False)
    monkeypatch.setattr(voice_config, "load_config", lambda: GrandpaConfig())
    loaded = voice_config.load_voice_assistant_config()
    assert loaded.tts_engine == GrandpaConfig().tts.backend == "pyttsx3"


def test_voice_follows_configured_tts_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GRANDPA_VOICE_TTS_ENGINE", raising=False)
    cfg = GrandpaConfig()
    cfg.tts.backend = "kokoro"
    monkeypatch.setattr(voice_config, "load_config", lambda: cfg)
    assert voice_config.load_voice_assistant_config().tts_engine == "kokoro"


def test_env_override_still_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GRANDPA_VOICE_TTS_ENGINE", "grandpa_voice")
    monkeypatch.setattr(voice_config, "load_config", lambda: GrandpaConfig())
    assert voice_config.load_voice_assistant_config().tts_engine == "grandpa_voice"


def test_toml_without_tts_section_uses_default(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[engine]\ndefault = "ollama"\n', encoding="utf-8")
    assert core_config.load_config(path).tts.backend == DEFAULT_TTS_BACKEND
