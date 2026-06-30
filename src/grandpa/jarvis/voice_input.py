"""User-initiated microphone input for Jarvis commands."""

from __future__ import annotations

import importlib
import io
import wave
from dataclasses import dataclass
from typing import Protocol

from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceRecognitionError,
)
from grandpa.voice.speech_input import SpeechInputEngine

VOICE_INPUT_INSTALL_MESSAGE = (
    "Jarvis voice input is not fully installed.\n"
    "Install local microphone/STT support, then retry:\n"
    "uv pip install sounddevice\n"
    "uv sync --extra speech"
)


class AudioRecorder(Protocol):
    def record_wav(self) -> bytes:
        """Record a short microphone sample and return WAV bytes."""


@dataclass(frozen=True)
class JarvisVoiceTranscript:
    transcript: str
    engine: str
    duration_seconds: float = 0.0
    language: str | None = None


@dataclass
class SoundDeviceMicrophoneRecorder:
    duration_seconds: float = 5.0
    sample_rate: int = 16_000
    channels: int = 1

    def record_wav(self) -> bytes:
        sounddevice = _import_sounddevice()
        frame_count = max(1, int(self.duration_seconds * self.sample_rate))
        try:
            recording = sounddevice.rec(
                frame_count,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
            )
            sounddevice.wait()
        except Exception as exc:  # pragma: no cover - hardware specific
            raise MicrophoneUnavailableError(detail=str(exc)) from exc

        frames = recording.tobytes()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(frames)
        return buffer.getvalue()


def listen_for_jarvis_command(
    *,
    recorder: AudioRecorder | None = None,
    speech_engine: SpeechInputEngine | None = None,
) -> JarvisVoiceTranscript:
    """Capture one push-to-talk utterance and transcribe it locally."""

    audio_recorder = recorder or SoundDeviceMicrophoneRecorder()
    audio_bytes = audio_recorder.record_wav()
    engine = speech_engine or SpeechInputEngine()
    result = engine.listen(audio_bytes=audio_bytes, audio_format="wav")
    transcript = result.transcript.strip()
    if not transcript:
        raise VoiceRecognitionError(detail="No speech was detected.")
    return JarvisVoiceTranscript(
        transcript=transcript,
        engine=result.engine,
        duration_seconds=result.duration_seconds,
        language=result.language,
    )


def _import_sounddevice():
    try:
        return importlib.import_module("sounddevice")
    except ImportError as exc:
        raise VoiceDependencyError(VOICE_INPUT_INSTALL_MESSAGE, detail=str(exc)) from exc


__all__ = [
    "JarvisVoiceTranscript",
    "SoundDeviceMicrophoneRecorder",
    "VOICE_INPUT_INSTALL_MESSAGE",
    "listen_for_jarvis_command",
]
