"""Local speech output abstraction for Grandpa voice mode."""

from __future__ import annotations

import importlib.util
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from grandpa.voice.errors import VoiceOutputUnavailableError

logger = logging.getLogger(__name__)

_ACTIVE_PYTTSX3_ENGINES: set[Any] = set()
_ACTIVE_PYTTSX3_LOCK = threading.RLock()


@dataclass(frozen=True)
class SpeechOutputResult:
    status: str
    engine: str
    message: str
    spoken_text: str = ""
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "engine": self.engine,
            "message": self.message,
            "spoken_text": self.spoken_text,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class SpeechOutputEngine:
    """Best-effort local TTS with stop/interrupt state."""

    voice: str = ""
    rate: int = 185
    enabled: bool = True
    _queue: deque[str] = field(default_factory=deque, init=False)
    _state: str = field(default="idle", init=False)
    _last_result: SpeechOutputResult | None = field(default=None, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _stop_requested: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            from grandpa.core.config import load_config

            config = load_config()
            # Respect configured enabled status
            self.enabled = config.tts.enabled
        except Exception:
            pass

    def speak(
        self, text: str, *, interrupt: bool = False, dry_run: bool = False
    ) -> SpeechOutputResult:
        started = time.perf_counter()
        clean_text = _short_voice_text(text)
        candidates = self.available_local_engines()
        engine = candidates[0] if candidates else "print_only"
        with self._lock:
            if interrupt:
                self._queue.clear()
                self._stop_requested = True
            if not clean_text:
                result = SpeechOutputResult(
                    "skipped",
                    engine,
                    "No speech text provided.",
                    latency_ms=_elapsed_ms(started),
                )
                self._last_result = result
                return result
            self._queue.append(clean_text)
            self._state = "speaking"
            self._stop_requested = False

        if dry_run or not self.enabled:
            with self._lock:
                self._queue.clear()
                self._state = "idle"
            result = SpeechOutputResult(
                "dry_run" if dry_run else "disabled",
                engine,
                "Speech output queued safely.",
                clean_text,
                _elapsed_ms(started),
            )
            self._last_result = result
            return result

        if engine == "print_only":
            with self._lock:
                self._queue.clear()
                self._state = "idle"
            result = SpeechOutputResult(
                "fallback",
                engine,
                "No TTS backend available; printed response only.",
                clean_text,
                _elapsed_ms(started),
            )
            self._last_result = result
            return result

        failures: list[str] = []
        for candidate in candidates:
            try:
                self._speak_with_engine(candidate, clean_text)
            except Exception as exc:
                logger.warning(
                    "Local TTS backend %s failed; trying the next local backend: %s",
                    candidate,
                    exc,
                )
                failures.append(f"{candidate}: {exc.__class__.__name__}")
                continue

            with self._lock:
                self._queue.clear()
                self._state = "idle" if not self._stop_requested else "interrupted"
            result = SpeechOutputResult(
                "completed",
                candidate,
                "Speech output spoken.",
                clean_text,
                _elapsed_ms(started),
            )
            self._last_result = result
            return result

        with self._lock:
            self._queue.clear()
            self._state = "idle"
        result = SpeechOutputResult(
            "fallback",
            "print_only",
            "Speech output failed; printed response only.",
            clean_text,
            _elapsed_ms(started),
            error="; ".join(failures) or None,
        )
        self._last_result = result
        return result

    def _speak_with_engine(self, engine: str, text: str) -> None:
        if engine in {"grandpa_voice", "kokoro"}:
            import grandpa.speech  # noqa: F401 - registers local TTS backends
            from grandpa.core.registry import TTSRegistry

            backend_cls = TTSRegistry.get(engine)
            result = backend_cls().synthesize(text)
            if not result.audio:
                raise VoiceOutputUnavailableError(detail=f"{engine} returned no audio.")
            _play_audio_bytes(result.audio, self)
            return
        if engine == "pyttsx3":
            _speak_with_pyttsx3(text, voice=self.voice, rate=self.rate)
            return
        raise VoiceOutputUnavailableError(
            detail="No supported local TTS backend is available."
        )

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_requested = True
            self._queue.clear()
            self._state = "idle"
        _stop_active_pyttsx3()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        return {"status": "stopped", "message": "Speech output stopped."}

    def best_available_engine(self) -> str:
        candidates = self.available_local_engines()
        return candidates[0] if candidates else "print_only"

    def available_local_engines(self) -> tuple[str, ...]:
        try:
            from grandpa.core.config import load_config

            config = load_config()
            configured_backend = config.tts.backend
        except Exception:
            configured_backend = ""

        import grandpa.speech  # noqa: F401 - registers local TTS backends
        from grandpa.core.registry import TTSRegistry

        if configured_backend == "grandpa_voice":
            ordered = ["grandpa_voice", "pyttsx3", "kokoro"]
        elif configured_backend == "kokoro":
            ordered = ["kokoro", "pyttsx3", "grandpa_voice"]
        elif configured_backend == "pyttsx3":
            ordered = ["pyttsx3", "grandpa_voice", "kokoro"]
        else:
            ordered = ["grandpa_voice", "kokoro", "pyttsx3"]

        available: list[str] = []
        for candidate in dict.fromkeys(ordered):
            if candidate == "pyttsx3":
                if importlib.util.find_spec("pyttsx3") is not None:
                    available.append(candidate)
                continue
            if not TTSRegistry.contains(candidate):
                continue
            try:
                backend = TTSRegistry.get(candidate)()
                if backend.health() and candidate not in available:
                    available.append(candidate)
            except Exception as exc:
                logger.warning(
                    "Local TTS health check failed for %s: %s", candidate, exc
                )
        return tuple(available)

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            queue_size = len(self._queue)
            state = self._state
            last = self._last_result.to_dict() if self._last_result else None
        engine = self.best_available_engine()
        return {
            "status": "ready" if engine != "print_only" else "text_only",
            "engine": engine,
            "enabled": self.enabled,
            "state": state,
            "queue_size": queue_size,
            "voice": self.voice or _selected_voice_name(engine),
            "rate": self.rate,
            "last_result": last,
            "interrupt_supported": True,
        }


def _speak_with_pyttsx3(text: str, *, voice: str, rate: int) -> None:
    pyttsx3 = __import__("pyttsx3")
    engine = pyttsx3.init()
    with _ACTIVE_PYTTSX3_LOCK:
        _ACTIVE_PYTTSX3_ENGINES.add(engine)
    try:
        if rate:
            engine.setProperty("rate", rate)
        if voice:
            for candidate in engine.getProperty("voices") or []:
                candidate_id = str(getattr(candidate, "id", ""))
                candidate_name = str(getattr(candidate, "name", ""))
                if (
                    voice.casefold() in candidate_id.casefold()
                    or voice.casefold() in candidate_name.casefold()
                ):
                    engine.setProperty("voice", candidate_id)
                    break
        engine.say(text)
        engine.runAndWait()
    finally:
        with _ACTIVE_PYTTSX3_LOCK:
            _ACTIVE_PYTTSX3_ENGINES.discard(engine)


def _stop_active_pyttsx3() -> None:
    with _ACTIVE_PYTTSX3_LOCK:
        engines = tuple(_ACTIVE_PYTTSX3_ENGINES)
    for engine in engines:
        try:
            engine.stop()
        except Exception:
            pass


def _speak_with_edge_tts(_text: str) -> None:
    raise VoiceOutputUnavailableError(
        detail="Edge TTS is installed but direct speaker playback is not configured yet."
    )


def _selected_voice_name(engine: str) -> str:
    if engine != "pyttsx3":
        return ""
    try:
        pyttsx3 = __import__("pyttsx3")
        tts = pyttsx3.init()
        voice_id = str(tts.getProperty("voice") or "")
        for candidate in tts.getProperty("voices") or []:
            if str(getattr(candidate, "id", "")) == voice_id:
                return str(getattr(candidate, "name", "") or voice_id)
        return voice_id
    except Exception:
        return ""


def _short_voice_text(text: str, max_chars: int = 360) -> str:
    clean = " ".join(str(text).strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "..."


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _play_audio_bytes(audio_bytes: bytes, engine: SpeechOutputEngine) -> None:
    import io
    import time

    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError as exc:
        raise VoiceOutputUnavailableError(
            detail=f"Audio playback libraries (soundfile/sounddevice) are not installed: {exc}"
        ) from exc

    try:
        data, samplerate = sf.read(io.BytesIO(audio_bytes))
        sd.play(data, samplerate)

        # Poll to support fast responsive interruption
        chunk_time = 0.05
        total_duration = len(data) / samplerate
        elapsed = 0.0
        while elapsed < total_duration:
            with engine._lock:
                if engine._stop_requested:
                    sd.stop()
                    break
            time.sleep(chunk_time)
            elapsed += chunk_time
    except Exception as exc:
        logger.error("Audio playback failed: %s", exc)
        raise RuntimeError(f"Audio playback failed: {exc}") from exc


__all__ = ["SpeechOutputEngine", "SpeechOutputResult"]
