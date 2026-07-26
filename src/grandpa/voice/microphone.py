"""Microphone capture adapter for the offline voice assistant."""

from __future__ import annotations

import io
import threading
import wave
from dataclasses import dataclass

from grandpa.jarvis.voice_input import (
    _import_sounddevice,
    _select_input_device,
    calculate_pcm16_rms,
)
from grandpa.voice.diagnostics import VoiceDeviceInfo, list_input_devices


@dataclass(frozen=True)
class CapturedAudio:
    """A single in-memory microphone capture."""

    data: bytes
    format: str = "wav"
    rms_level: float = 0.0
    device_name: str = ""


class MicrophoneCapture:
    """Capture short push-to-talk phrases without keeping the microphone open."""

    def __init__(
        self,
        *,
        duration_seconds: float = 5.0,
        sample_rate: int = 16_000,
        device: int | None = None,
        chunk_seconds: float = 0.1,
    ) -> None:
        self.duration_seconds = duration_seconds
        self.sample_rate = sample_rate
        self.device = device
        self.chunk_seconds = chunk_seconds
        self._stream = None

    def capture(self, stop_event: threading.Event | None = None) -> CapturedAudio:
        """Capture a short WAV phrase, checking ``stop_event`` every chunk."""

        stop = stop_event or threading.Event()
        sounddevice = _import_sounddevice()
        selected_device, device_info, _warning = _select_input_device(
            sounddevice, self.device
        )
        sample_rate = int(self.sample_rate)
        channels = max(1, min(1, int(device_info.get("max_input_channels") or 1)))
        chunk_frames = max(1, int(sample_rate * self.chunk_seconds))
        max_frames = max(1, int(sample_rate * self.duration_seconds))
        captured_frames = 0
        chunks: list[bytes] = []

        try:
            self._stream = sounddevice.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                device=selected_device,
            )
            with self._stream as stream:
                while not stop.is_set() and captured_frames < max_frames:
                    frames_to_read = min(chunk_frames, max_frames - captured_frames)
                    recording, _overflowed = stream.read(frames_to_read)
                    frames = recording.tobytes()
                    chunks.append(frames)
                    captured_frames += _captured_frame_count(recording, frames_to_read)
        finally:
            self.close()

        audio_frames = b"".join(chunks)
        return CapturedAudio(
            data=_wav_bytes(audio_frames, channels=channels, sample_rate=sample_rate),
            format="wav",
            rms_level=calculate_pcm16_rms(audio_frames),
            device_name=str(device_info.get("name") or "Input device"),
        )

    def close(self) -> None:
        """Close any active PortAudio stream best-effort."""

        stream = self._stream
        self._stream = None
        if stream is None:
            return
        for method_name in ("stop", "close"):
            method = getattr(stream, method_name, None)
            if method is None:
                continue
            try:
                method()
            except Exception:
                pass

    def reset(self) -> None:
        """Discard the prior phrase stream before opening a fresh capture."""

        self.close()


def _wav_bytes(frames: bytes, *, channels: int, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return buffer.getvalue()


def _captured_frame_count(recording, fallback: int) -> int:
    try:
        return int(len(recording))
    except Exception:
        return fallback


def available_microphones() -> tuple[VoiceDeviceInfo, ...]:
    """Return input devices suitable for voice capture."""

    return list_input_devices()


__all__ = ["CapturedAudio", "MicrophoneCapture", "available_microphones"]
