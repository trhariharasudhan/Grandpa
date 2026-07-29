"""Microphone capture adapter for the offline voice assistant."""

from __future__ import annotations

import io
import math
import threading
import wave
from array import array
from dataclasses import dataclass

from grandpa.voice.device_manager import (
    MicrophoneDevice,
    MicrophoneDeviceManager,
    import_sounddevice,
)
from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector


@dataclass(frozen=True)
class CapturedAudio:
    """A single in-memory microphone capture."""

    data: bytes
    format: str = "wav"
    rms_level: float = 0.0
    device_name: str = ""
    device_index: int | None = None
    captured_frame_count: int = 0
    speech_detected: bool = False


class MicrophoneCapture:
    """Capture short push-to-talk phrases without keeping the microphone open."""

    def __init__(
        self,
        *,
        duration_seconds: float = 5.0,
        sample_rate: int = 16_000,
        device: int | None = None,
        device_name: str | None = None,
        chunk_seconds: float = 0.1,
        recovery_attempts: int = 2,
        vad_config: VoiceActivityConfig | None = None,
        device_manager: MicrophoneDeviceManager | None = None,
    ) -> None:
        self.duration_seconds = duration_seconds
        self.sample_rate = sample_rate
        self.device = device
        self.device_name = device_name
        self.chunk_seconds = chunk_seconds
        self.recovery_attempts = max(0, recovery_attempts)
        self.vad_config = vad_config or VoiceActivityConfig(
            maximum_utterance_seconds=max(1.0, duration_seconds)
        )
        self.device_manager = device_manager
        self.last_warning: str | None = None
        self.last_device: MicrophoneDevice | None = None
        self.last_error: str | None = None
        self._stream = None

    def capture(self, stop_event: threading.Event | None = None) -> CapturedAudio:
        """Capture a short WAV phrase, checking ``stop_event`` every chunk."""

        stop = stop_event or threading.Event()
        sounddevice = import_sounddevice()
        manager = self.device_manager or MicrophoneDeviceManager(sounddevice)
        self.device_manager = manager
        selection = manager.select(
            requested_index=self.device,
            requested_name=self.device_name,
            allow_fallback=self.device is None and self.device_name is None,
        )
        self.last_warning = selection.warning
        attempts = 0
        while True:
            try:
                return self._capture_from_device(sounddevice, selection.device, stop)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                self.close()
                self.last_error = f"{type(exc).__name__}: {exc}"
                if attempts >= self.recovery_attempts or self.device is not None:
                    from grandpa.voice.errors import MicrophoneUnavailableError

                    raise MicrophoneUnavailableError(
                        "The microphone became unavailable during capture. "
                        "Check the device connection and try again.",
                        detail=self.last_error,
                    ) from exc
                attempts += 1
                selection = manager.recover(selection.device, exc)
                self.last_warning = selection.warning

    def _capture_from_device(
        self,
        sounddevice,
        selected: MicrophoneDevice,
        stop: threading.Event,
    ) -> CapturedAudio:
        sample_rate = int(self.sample_rate)
        channels = 1
        chunk_frames = max(1, int(sample_rate * self.chunk_seconds))
        max_frames = max(1, int(sample_rate * self.duration_seconds))
        captured_frames = 0
        chunks: list[bytes] = []
        detector = VoiceActivityDetector(self.vad_config)

        try:
            self._stream = sounddevice.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                device=selected.index,
            )
            with self._stream as stream:
                while not stop.is_set() and captured_frames < max_frames:
                    frames_to_read = min(chunk_frames, max_frames - captured_frames)
                    recording, _overflowed = stream.read(frames_to_read)
                    frames = recording.tobytes()
                    chunks.append(frames)
                    frame_count = _captured_frame_count(recording, frames_to_read)
                    captured_frames += frame_count
                    if detector.observe(
                        calculate_pcm16_rms(frames),
                        frame_count / sample_rate,
                    ):
                        break
        finally:
            self.close()

        audio_frames = b"".join(chunks)
        self.last_device = selected
        return CapturedAudio(
            data=_wav_bytes(audio_frames, channels=channels, sample_rate=sample_rate),
            format="wav",
            rms_level=calculate_pcm16_rms(audio_frames),
            device_name=selected.name,
            device_index=selected.index,
            captured_frame_count=captured_frames,
            speech_detected=detector.speech_started,
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

    def recover(self) -> bool:
        """Allow the session to retry after a recoverable device error."""

        self.close()
        return self.device is None


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


def calculate_pcm16_rms(frames: bytes) -> float:
    if not frames:
        return 0.0
    samples = array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def available_microphones():
    """Return input devices suitable for voice capture."""

    manager = MicrophoneDeviceManager(import_sounddevice())
    return manager.enumerate()


__all__ = [
    "CapturedAudio",
    "MicrophoneCapture",
    "available_microphones",
    "calculate_pcm16_rms",
]
