"""F5-TTS engine adapter implementation."""

from __future__ import annotations

from grandpa.speech.local_voice.engine import LocalVoiceEngine
from grandpa.speech.local_voice.service_client import (
    DEFAULT_SYNTHESIS_TIMEOUT_SECONDS,
    LocalVoiceServiceClient,
)


class F5VoiceEngine(LocalVoiceEngine):
    """Adapter for the standalone F5-TTS local voice service."""

    def __init__(
        self,
        service_url: str = "http://127.0.0.1:8765",
        *,
        synthesis_timeout_seconds: float = DEFAULT_SYNTHESIS_TIMEOUT_SECONDS,
    ) -> None:
        self.client = LocalVoiceServiceClient(
            service_url=service_url,
            synthesis_timeout_seconds=synthesis_timeout_seconds,
        )

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "grandpa",
        speed: float = 1.0,
    ) -> bytes:
        return self.client.synthesize(text, voice=voice_id, speed=speed)

    def health(self) -> bool:
        return self.client.health()
