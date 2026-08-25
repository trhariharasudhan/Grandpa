"""Microphone capture adapter for the offline voice assistant."""

from __future__ import annotations

import io
import math
import threading
import wave
from array import array
from dataclasses import dataclass
from typing import Any, Callable

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
    speech_detected: bool = True
    capture_sample_rate: int = 16_000
    capture_channels: int = 1
    native_frame_count: int = 0
    speech_onset_seconds: float | None = None
    speech_active_seconds: float = 0.0
    trailing_silence_seconds: float = 0.0
    finalization_reason: str = "unknown"


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
        sounddevice: Any = None,
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
        self.sounddevice = sounddevice
        self.last_warning: str | None = None
        self.last_device: MicrophoneDevice | None = None
        self.last_error: str | None = None
        self._stream = None

    def capture(
        self,
        stop_event: threading.Event | None = None,
        on_speech_start: Callable[[], None] | None = None,
    ) -> CapturedAudio:
        """Capture one complete utterance using VAD chunk inspection."""

        stop = stop_event or threading.Event()
        if stop.is_set():
            return CapturedAudio(
                b"",
                speech_detected=False,
                finalization_reason="cancelled",
            )

        sounddevice = (
            self.sounddevice
            or getattr(self.device_manager, "sounddevice", None)
            or import_sounddevice()
        )
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
                return self._capture_from_device(
                    sounddevice,
                    selection.device,
                    stop,
                    on_speech_start=on_speech_start,
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                from grandpa.voice.errors import MicrophoneUnavailableError

                if isinstance(exc, MicrophoneUnavailableError):
                    raise
                self.close()
                self.last_error = f"{type(exc).__name__}: {exc}"
                if attempts >= self.recovery_attempts:
                    raise MicrophoneUnavailableError(
                        "The microphone became unavailable during capture. "
                        "Check the device connection and try again.",
                        detail=self.last_error,
                    ) from exc
                attempts += 1
                import time

                time.sleep(0.3)
                if self.device is None:
                    selection = manager.recover(selection.device, exc)
                    self.last_warning = selection.warning

    def _capture_from_device(
        self,
        sounddevice,
        selected: MicrophoneDevice,
        stop: threading.Event,
        on_speech_start: Callable[[], None] | None = None,
    ) -> CapturedAudio:
        sample_rate, channels = _negotiate_capture_settings(
            sounddevice,
            selected,
            requested_rate=int(self.sample_rate),
        )
        chunk_frames = max(1, int(sample_rate * self.chunk_seconds))
        max_utterance_frames = max(
            1, int(sample_rate * max(1.0, self.duration_seconds))
        )
        native_frame_count = 0
        chunks: list[bytes] = []
        pre_chunks: list[bytes] = []
        pre_chunk_limit = max(2, int(0.3 / max(0.01, self.chunk_seconds)))
        detector = VoiceActivityDetector(self.vad_config)

        try:
            self._stream = sounddevice.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                device=selected.index,
            )
            with self._stream as stream:
                while not stop.is_set():
                    recording, _overflowed = stream.read(chunk_frames)
                    frames = recording.tobytes()
                    frame_count = _captured_frame_count(recording, chunk_frames)
                    rms = calculate_pcm16_rms(_downmix_pcm16(frames, channels))

                    if not detector.speech_started:
                        pre_chunks.append(frames)
                        if len(pre_chunks) > pre_chunk_limit:
                            pre_chunks.pop(0)
                        finished = detector.observe(rms, frame_count / sample_rate)
                        if detector.speech_started:
                            if on_speech_start is not None:
                                try:
                                    on_speech_start()
                                except Exception:
                                    pass
                            chunks.extend(pre_chunks)
                            native_frame_count = sum(
                                len(c) // (channels * 2) for c in chunks
                            )
                        if finished:
                            break
                    else:
                        chunks.append(frames)
                        native_frame_count += frame_count
                        if detector.observe(rms, frame_count / sample_rate):
                            break
                        if native_frame_count >= max_utterance_frames:
                            detector._finalization_reason = "maximum_duration"
                            break
        finally:
            self.close()

        native_frames = b"".join(chunks)
        audio_frames = _normalize_pcm16_audio(
            native_frames,
            input_rate=sample_rate,
            input_channels=channels,
            output_rate=int(self.sample_rate),
        )
        canonical_frame_count = len(audio_frames) // 2
        self.last_device = selected
        return CapturedAudio(
            data=_wav_bytes(
                audio_frames,
                channels=1,
                sample_rate=int(self.sample_rate),
            ),
            format="wav",
            rms_level=calculate_pcm16_rms(audio_frames),
            device_name=selected.name,
            device_index=selected.index,
            captured_frame_count=canonical_frame_count,
            speech_detected=detector.speech_started,
            capture_sample_rate=sample_rate,
            capture_channels=channels,
            native_frame_count=native_frame_count,
            speech_onset_seconds=detector.speech_onset_seconds,
            speech_active_seconds=detector.speech_active_seconds,
            trailing_silence_seconds=detector.trailing_silence_seconds,
            finalization_reason=(
                detector.finalization_reason
                or ("cancelled" if stop.is_set() else "stream_ended")
            ),
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


def _negotiate_capture_settings(
    sounddevice,
    selected: MicrophoneDevice,
    *,
    requested_rate: int,
) -> tuple[int, int]:
    """Choose a supported physical format while preserving canonical output."""

    if selected.input_channels <= 0:
        from grandpa.voice.errors import MicrophoneUnavailableError

        raise MicrophoneUnavailableError(
            f"{selected.name} does not provide an input channel."
        )
    native_channels = max(1, min(2, selected.input_channels))
    attempts = [(requested_rate, 1)]
    default_rate = int(selected.default_sample_rate or requested_rate)
    if (default_rate, native_channels) not in attempts:
        attempts.append((default_rate, native_channels))
    if (default_rate, 1) not in attempts:
        attempts.append((default_rate, 1))

    checker = getattr(sounddevice, "check_input_settings", None)
    if not callable(checker):
        return attempts[0]
    errors: list[str] = []
    for sample_rate, channels in attempts:
        try:
            checker(
                device=selected.index,
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
            )
        except Exception as exc:
            errors.append(f"{sample_rate} Hz/{channels} channel(s): {exc}")
            continue
        return sample_rate, channels

    from grandpa.voice.errors import MicrophoneUnavailableError

    detail = "; ".join(errors)
    raise MicrophoneUnavailableError(
        (
            f"Could not open {selected.name} at the requested {requested_rate} Hz "
            f"or its default {default_rate} Hz. Check the Windows microphone format."
        ),
        detail=detail,
    )


def _normalize_pcm16_audio(
    frames: bytes,
    *,
    input_rate: int,
    input_channels: int,
    output_rate: int,
) -> bytes:
    """Downmix then resample PCM16 exactly once for the STT boundary."""

    mono = _downmix_pcm16(frames, input_channels)
    if input_rate == output_rate:
        return mono
    import audioop

    converted, _state = audioop.ratecv(
        mono,
        2,
        1,
        input_rate,
        output_rate,
        None,
    )
    return converted


def _downmix_pcm16(frames: bytes, channels: int) -> bytes:
    if channels <= 1:
        return frames
    samples = array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    usable = len(samples) - (len(samples) % channels)
    channel_samples = [
        array("h", samples[channel:usable:channels]) for channel in range(channels)
    ]
    averaged = array(
        "h",
        (
            round(sum(samples[index : index + channels]) / channels)
            for index in range(0, usable, channels)
        ),
    )
    averaged_bytes = averaged.tobytes()
    strongest = max(channel_samples, key=lambda values: _pcm16_array_rms(values))
    strongest_bytes = strongest.tobytes()
    # Some Windows microphone arrays expose phase-opposed channels. Averaging
    # them can cancel intelligible speech, so retain the strongest physical
    # channel only when its energy is materially above the standard downmix.
    if calculate_pcm16_rms(strongest_bytes) > calculate_pcm16_rms(averaged_bytes) * 1.5:
        return strongest_bytes
    return averaged_bytes


def _pcm16_array_rms(samples: array) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


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
