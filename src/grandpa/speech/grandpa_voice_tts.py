"""Local cloned voice backend for Grandpa."""

from __future__ import annotations

import logging
from typing import List

from grandpa.core.config import load_config
from grandpa.core.registry import TTSRegistry
from grandpa.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)


class GrandpaVoiceUnavailableError(RuntimeError):
    """Controlled error used by the local fallback cascade."""


@TTSRegistry.register("grandpa_voice")
class GrandpaVoiceTTSBackend(TTSBackend):
    """Grandpa local cloned-voice TTS backend."""

    backend_id = "grandpa_voice"

    def __init__(
        self,
        *,
        model_path: str = "",
        device: str = "cpu",
    ) -> None:
        self._model_path = model_path
        self._device = device
        self._engine = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return

        config = load_config()
        # Fallback values if the config structure has not been updated yet
        grandpa_voice_config = getattr(config, "grandpa_voice", None)
        engine_type = getattr(grandpa_voice_config, "engine", "f5")
        service_url = getattr(
            grandpa_voice_config, "service_url", "http://127.0.0.1:8765"
        )
        synthesis_timeout_seconds = getattr(
            grandpa_voice_config, "synthesis_timeout_seconds", 600.0
        )

        if engine_type == "f5":
            from grandpa.speech.local_voice.f5_engine import F5VoiceEngine

            self._engine = F5VoiceEngine(
                service_url=service_url,
                synthesis_timeout_seconds=synthesis_timeout_seconds,
            )
        else:
            raise GrandpaVoiceUnavailableError(
                f"Unsupported local voice engine type: {engine_type}"
            )

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "grandpa",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        self._ensure_engine()
        if not text.strip():
            return TTSResult(audio=b"", format=output_format, voice_id=voice_id)

        try:
            # The LocalVoiceEngine returns raw WAV bytes.
            wav_bytes = self._engine.synthesize(text, voice_id=voice_id, speed=speed)
            return TTSResult(
                audio=wav_bytes,
                format=output_format,
                voice_id=voice_id,
                sample_rate=24000,  # F5-TTS standard sample rate
                duration_seconds=0.0,  # Determined dynamically if played back
                metadata={"backend": "grandpa_voice"},
            )
        except Exception as exc:
            logger.error("Synthesis failed in GrandpaVoiceTTSBackend: %s", exc)
            raise GrandpaVoiceUnavailableError(
                "Cloned voice synthesis is unavailable."
            ) from exc

    def available_voices(self) -> List[str]:
        return ["grandpa"]

    def health(self) -> bool:
        try:
            self._ensure_engine()
            return self._engine.health()
        except Exception:
            return False


__all__ = ["GrandpaVoiceTTSBackend", "GrandpaVoiceUnavailableError"]
