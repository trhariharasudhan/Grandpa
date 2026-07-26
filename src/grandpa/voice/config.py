"""Configuration helpers for the offline voice assistant CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass

from grandpa.core.config import load_config
from grandpa.voice.wake_word import DEFAULT_WAKE_PHRASES


@dataclass(frozen=True)
class VoiceAssistantConfig:
    """Runtime configuration for ``grandpa voice``."""

    stt_model: str = "base.en"
    language: str = "en"
    device: str = "cpu"
    compute_type: str = "int8"
    microphone: int | None = None
    phrase_duration_limit: float = 5.0
    tts_engine: str = "pyttsx3"
    tts_rate: int = 175
    tts_volume: float = 1.0
    tts_voice: str = ""
    tts_enabled: bool = True
    wake_word_enabled: bool = False
    wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES
    wake_response_enabled: bool = True
    wake_command_timeout_seconds: float = 10.0
    post_tts_cooldown_ms: int = 400
    echo_window_seconds: float = 3.0
    echo_similarity_threshold: float = 0.85


def load_voice_assistant_config(
    *,
    model: str | None = None,
    language: str | None = None,
    device: str | None = None,
    microphone: int | None = None,
    tts_enabled: bool | None = None,
    wake_word_enabled: bool | None = None,
    wake_phrases: tuple[str, ...] | None = None,
    wake_response_enabled: bool | None = None,
) -> VoiceAssistantConfig:
    """Load voice config from Grandpa config plus ``GRANDPA_VOICE_*`` overrides."""

    base = load_config().speech
    return VoiceAssistantConfig(
        stt_model=_first_non_empty(
            model,
            os.getenv("GRANDPA_VOICE_STT_MODEL"),
            getattr(base, "model", ""),
            "base.en",
        ),
        language=_first_non_empty(
            language,
            os.getenv("GRANDPA_VOICE_LANGUAGE"),
            getattr(base, "language", ""),
            "en",
        ),
        device=_first_non_empty(
            device,
            os.getenv("GRANDPA_VOICE_DEVICE"),
            getattr(base, "device", ""),
            "cpu",
        ),
        compute_type=_first_non_empty(
            os.getenv("GRANDPA_VOICE_COMPUTE_TYPE"),
            getattr(base, "compute_type", ""),
            "int8",
        ),
        microphone=microphone
        if microphone is not None
        else _env_int("GRANDPA_VOICE_MICROPHONE"),
        phrase_duration_limit=_env_float("GRANDPA_VOICE_PHRASE_DURATION_LIMIT", 5.0),
        tts_engine=_first_non_empty(os.getenv("GRANDPA_VOICE_TTS_ENGINE"), "pyttsx3"),
        tts_rate=_env_int("GRANDPA_VOICE_RATE", 175) or 175,
        tts_volume=_env_float("GRANDPA_VOICE_VOLUME", 1.0),
        tts_voice=_first_non_empty(os.getenv("GRANDPA_VOICE_WINDOWS_VOICE"), ""),
        tts_enabled=tts_enabled
        if tts_enabled is not None
        else _env_bool("GRANDPA_VOICE_TTS_ENABLED", True),
        wake_word_enabled=(
            wake_word_enabled
            if wake_word_enabled is not None
            else _env_bool("GRANDPA_VOICE_WAKE_WORD_ENABLED", False)
        ),
        wake_phrases=_configured_wake_phrases(wake_phrases),
        wake_response_enabled=(
            wake_response_enabled
            if wake_response_enabled is not None
            else _env_bool("GRANDPA_VOICE_WAKE_RESPONSE_ENABLED", True)
        ),
        wake_command_timeout_seconds=_env_float(
            "GRANDPA_VOICE_WAKE_COMMAND_TIMEOUT", 10.0
        ),
        post_tts_cooldown_ms=max(
            0, _env_int("GRANDPA_VOICE_POST_TTS_COOLDOWN_MS", 400) or 0
        ),
        echo_window_seconds=max(
            0.0, _env_float("GRANDPA_VOICE_ECHO_WINDOW_SECONDS", 3.0)
        ),
        echo_similarity_threshold=min(
            1.0,
            max(0.5, _env_float("GRANDPA_VOICE_ECHO_SIMILARITY_THRESHOLD", 0.85)),
        ),
    )


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _configured_wake_phrases(
    cli_phrases: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    phrases = tuple(phrase.strip() for phrase in cli_phrases or () if phrase.strip())
    if phrases:
        return phrases
    raw = os.getenv("GRANDPA_VOICE_WAKE_PHRASES", "")
    phrases = tuple(phrase.strip() for phrase in raw.split(",") if phrase.strip())
    return phrases or DEFAULT_WAKE_PHRASES


__all__ = ["VoiceAssistantConfig", "load_voice_assistant_config"]
