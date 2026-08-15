"""Minimal localhost HTTP service for optional F5-TTS inference."""

from __future__ import annotations

import argparse
import importlib.util
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from grandpa.voice_service.post_processing import (
    CharacterVoiceSettings,
    FFmpegCharacterVoiceProcessor,
    validate_character_voice_settings,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_REFERENCE_TEXT = ""
DEFAULT_F5_MODEL = "F5TTS_v1_Base"
DEFAULT_NFE_STEP = 8
DEFAULT_CPU_THREADS = 4
DEFAULT_CFG_STRENGTH = 0.0
MAX_TEXT_LENGTH = 2000
MIN_SPEED = 0.5
MAX_SPEED = 2.0

logger = logging.getLogger(__name__)


class SynthesizeRequest(BaseModel):
    """Bounded public request contract; model paths remain server-owned."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    voice_id: str = Field(default="grandpa", pattern=r"^grandpa$")
    speed: float = Field(default=1.0, ge=MIN_SPEED, le=MAX_SPEED)


class VoiceServiceRuntime:
    """Own model readiness and synthesis without exposing filesystem inputs."""

    def __init__(
        self,
        *,
        reference_audio: str | None = None,
        reference_text: str | None = None,
        nfe_step: int = DEFAULT_NFE_STEP,
        cpu_threads: int = DEFAULT_CPU_THREADS,
        cfg_strength: float = DEFAULT_CFG_STRENGTH,
        character_voice_settings: CharacterVoiceSettings | None = None,
        ffmpeg_path: str = "",
        model_loader: Callable[[], Any] | None = None,
        audio_encoder: Callable[[Any, int], bytes] | None = None,
        cpu_thread_configurer: Callable[[int], None] | None = None,
        character_processor: FFmpegCharacterVoiceProcessor | None = None,
    ) -> None:
        self.reference_audio = reference_audio or os.getenv(
            "GRANDPA_VOICE_REFERENCE_AUDIO", ""
        )
        self.reference_text = reference_text or os.getenv(
            "GRANDPA_VOICE_REFERENCE_TEXT", DEFAULT_REFERENCE_TEXT
        )
        self.nfe_step = nfe_step
        self.cpu_threads = cpu_threads
        self.cfg_strength = cfg_strength
        self.character_voice_settings = (
            character_voice_settings or CharacterVoiceSettings()
        )
        validate_character_voice_settings(self.character_voice_settings)
        self._model_loader = model_loader or _load_f5_model
        self._audio_encoder = audio_encoder or _encode_wav
        self._cpu_thread_configurer = cpu_thread_configurer or _configure_cpu_threads
        self._character_processor = (
            character_processor
            or FFmpegCharacterVoiceProcessor(
                self.character_voice_settings,
                ffmpeg_path=ffmpeg_path,
            )
        )
        self.last_raw_audio = b""
        self.model: Any | None = None
        self.ready = False
        self.reason = "not_initialized"

    def initialize(self) -> None:
        """Load the configured model only when the service process starts."""
        if (
            importlib.util.find_spec("f5_tts") is None
            and self._model_loader is _load_f5_model
        ):
            self.reason = "dependency_not_installed"
            return
        reference = (
            Path(self.reference_audio).expanduser() if self.reference_audio else None
        )
        if reference is None or not reference.is_file():
            self.reason = "reference_voice_invalid"
            return
        if not self.reference_text.strip():
            self.reason = "reference_text_invalid"
            return
        try:
            self._cpu_thread_configurer(self.cpu_threads)
            self.model = self._model_loader()
        except Exception:
            logger.exception("F5-TTS model initialization failed")
            self.reason = "model_not_ready"
            return
        self.ready = self.model is not None
        self.reason = "ready" if self.ready else "model_not_ready"

    def health_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "engine": "f5",
            "reason": self.reason,
            "voice_id": "grandpa",
        }

    def synthesize(self, request: SynthesizeRequest) -> bytes:
        if not self.ready or self.model is None:
            raise RuntimeError(self.reason)
        reference = Path(self.reference_audio).expanduser().resolve(strict=True)
        generated = self.model.infer(
            ref_file=str(reference),
            ref_text=self.reference_text,
            gen_text=request.text.strip(),
            speed=request.speed,
            nfe_step=self.nfe_step,
            cfg_strength=self.cfg_strength,
        )
        wav, sample_rate = generated[0], int(generated[1])
        raw_audio = self._audio_encoder(wav, sample_rate)
        self.last_raw_audio = raw_audio
        return self._character_processor.process(raw_audio)


def create_app(runtime: VoiceServiceRuntime | None = None) -> FastAPI:
    """Build the two-endpoint localhost voice service."""
    service_runtime = runtime or VoiceServiceRuntime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service_runtime.initialize()
        yield

    app = FastAPI(
        title="Grandpa Local Voice Service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.voice_runtime = service_runtime

    @app.get("/health")
    def health() -> dict[str, object]:
        return service_runtime.health_payload()

    @app.post("/synthesize")
    def synthesize(request: SynthesizeRequest) -> Response:
        if not service_runtime.ready:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "voice_service_unavailable",
                    "reason": service_runtime.reason,
                },
            )
        try:
            audio = service_runtime.synthesize(request)
        except Exception as exc:
            logger.exception("Local cloned-voice synthesis failed")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "voice_synthesis_failed",
                    "reason": exc.__class__.__name__,
                },
            ) from exc
        return Response(content=audio, media_type="audio/wav")

    return app


def _load_f5_model() -> Any:
    from f5_tts.api import F5TTS

    cache_dir = os.getenv("GRANDPA_VOICE_MODEL_CACHE", "").strip()
    return F5TTS(
        model=DEFAULT_F5_MODEL,
        device="cpu",
        hf_cache_dir=cache_dir or None,
    )


def _configure_cpu_threads(thread_count: int) -> None:
    import torch

    torch.set_num_threads(thread_count)


def _encode_wav(wav: Any, sample_rate: int) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grandpa local F5-TTS service")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if args.host == "0.0.0.0":
        logger.warning("Voice service explicitly configured for all interfaces")

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port)


app = create_app()


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_CFG_STRENGTH",
    "DEFAULT_CPU_THREADS",
    "DEFAULT_F5_MODEL",
    "DEFAULT_NFE_STEP",
    "MAX_TEXT_LENGTH",
    "SynthesizeRequest",
    "VoiceServiceRuntime",
    "app",
    "create_app",
    "main",
]
