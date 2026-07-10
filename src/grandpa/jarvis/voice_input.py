"""User-initiated microphone input for Jarvis commands."""

from __future__ import annotations

import importlib
import io
import math
import wave
from array import array
from dataclasses import dataclass
from typing import Any, Protocol

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

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


@dataclass(frozen=True)
class AudioCaptureDiagnostics:
    requested_device_id: int | None
    requested_device_name: str | None
    selected_device_id: int | None
    device_name: str
    channels: int
    sample_rate: int
    rms_level: float
    captured_frame_count: int
    warning: str | None = None


@dataclass
class SoundDeviceMicrophoneRecorder:
    duration_seconds: float = 5.0
    sample_rate: int = 16_000
    channels: int = 1
    device: int | None = None
    device_name: str | None = None
    last_rms: float = 0.0
    last_diagnostics: AudioCaptureDiagnostics | None = None

    def record_wav(self) -> bytes:
        sounddevice = _import_sounddevice()
        selected_device, device_info, warning = _select_input_device(sounddevice, self.device, self.device_name)
        channel_count = max(1, min(self.channels, int(device_info.get("max_input_channels") or self.channels or 1)))
        sample_rate = int(self.sample_rate)
        frame_count = max(1, int(self.duration_seconds * sample_rate))
        try:
            recording = sounddevice.rec(
                frame_count,
                samplerate=sample_rate,
                channels=channel_count,
                dtype="int16",
                device=selected_device,
            )
            sounddevice.wait()
        except Exception as exc:  # pragma: no cover - hardware specific
            raise MicrophoneUnavailableError(detail=str(exc)) from exc

        frames = recording.tobytes()
        self.last_rms = calculate_pcm16_rms(frames)
        captured_frame_count = _captured_frame_count(recording, frame_count)
        self.last_diagnostics = AudioCaptureDiagnostics(
            requested_device_id=self.device,
            requested_device_name=self.device_name or _load_preferred_microphone_name(),
            selected_device_id=selected_device,
            device_name=str(device_info.get("name") or "System default input"),
            channels=channel_count,
            sample_rate=sample_rate,
            rms_level=self.last_rms,
            captured_frame_count=captured_frame_count,
            warning=warning,
        )
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channel_count)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(frames)
        return buffer.getvalue()


def listen_for_jarvis_command(
    *,
    recorder: AudioRecorder | None = None,
    speech_engine: SpeechInputEngine | None = None,
    silence_threshold: float = 250.0,
) -> JarvisVoiceTranscript:
    """Capture one push-to-talk utterance and transcribe it locally."""

    audio_recorder = recorder or SoundDeviceMicrophoneRecorder()
    audio_bytes = audio_recorder.record_wav()
    rms = float(getattr(audio_recorder, "last_rms", 0.0) or 0.0)
    if rms and rms < silence_threshold:
        raise VoiceRecognitionError("I did not hear anything. Check microphone or speak louder.", detail=f"rms={rms:.2f}")
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


def _select_input_device(sounddevice: Any, requested_device: int | None, requested_name: str | None = None) -> tuple[int | None, dict[str, Any], str | None]:
    devices = _safe_query_devices(sounddevice)
    if requested_device is not None:
        if requested_device < 0:
            raise _microphone_error(f"Invalid microphone device index: {requested_device}")
        if devices is None:
            return requested_device, {"name": f"Input device {requested_device}", "max_input_channels": 1}, None
        if requested_device >= len(devices):
            raise _microphone_error(f"Microphone device {requested_device} was not found.\n{_available_input_devices_message(devices)}")
        info = _device_dict(devices[requested_device])
        if int(info.get("max_input_channels") or 0) <= 0:
            raise _microphone_error(f"Microphone device {requested_device} has no input channels.\n{_available_input_devices_message(devices)}")
        return requested_device, info, None

    if devices is not None:
        input_devices = _input_devices(devices)
        preferred_name = _clean_device_name(requested_name) or _load_preferred_microphone_name()
        if preferred_name:
            match = _find_input_device_by_name(input_devices, preferred_name)
            if match:
                index, info = match
                return index, info, None
            if requested_name:
                raise _microphone_error(f"Microphone named '{requested_name}' was not found.\n{_available_input_devices_message(devices)}")
            fallback = _best_available_input_device(sounddevice, devices, input_devices)
            if fallback:
                index, info = fallback
                return index, info, f"Configured microphone '{preferred_name}' was not found. Using {info.get('name') or f'input device {index}'}."
            raise _microphone_error(f"Configured microphone '{preferred_name}' was not found.\n{_available_input_devices_message(devices)}")

        default_index = _default_input_device(sounddevice)
        if default_index is not None and 0 <= default_index < len(devices):
            info = _device_dict(devices[default_index])
            if int(info.get("max_input_channels") or 0) > 0:
                return default_index, info, None
        best_device = _best_available_input_device(sounddevice, devices, input_devices)
        if best_device:
            index, info = best_device
            return index, info, None
        raise _microphone_error("No usable microphone was detected.")

    return None, {"name": "System default input", "max_input_channels": 1}, None


def _safe_query_devices(sounddevice: Any) -> list[Any] | None:
    try:
        devices = sounddevice.query_devices()
    except Exception:
        return None
    return list(devices)


def _default_input_device(sounddevice: Any) -> int | None:
    try:
        default = sounddevice.default.device
        value = default[0] if isinstance(default, (list, tuple)) else default
        value = int(value)
        return value if value >= 0 else None
    except Exception:
        return None


def _device_dict(device: Any) -> dict[str, Any]:
    if isinstance(device, dict):
        return device
    try:
        return dict(device)
    except Exception:
        return {
            "name": getattr(device, "name", "Input device"),
            "max_input_channels": getattr(device, "max_input_channels", 0),
        }


def _input_devices(devices: list[Any]) -> list[tuple[int, dict[str, Any]]]:
    result: list[tuple[int, dict[str, Any]]] = []
    for index, raw_info in enumerate(devices):
        info = _device_dict(raw_info)
        if int(info.get("max_input_channels") or 0) > 0:
            result.append((index, info))
    return result


def _best_available_input_device(
    sounddevice: Any,
    devices: list[Any],
    input_devices: list[tuple[int, dict[str, Any]]] | None = None,
) -> tuple[int, dict[str, Any]] | None:
    default_index = _default_input_device(sounddevice)
    if default_index is not None and 0 <= default_index < len(devices):
        info = _device_dict(devices[default_index])
        if int(info.get("max_input_channels") or 0) > 0:
            return default_index, info
    candidates = input_devices if input_devices is not None else _input_devices(devices)
    for preferred in ("microphone array", "realtek microphone", "microphone"):
        match = _find_input_device_by_name(candidates, preferred)
        if match:
            return match
    return candidates[0] if candidates else None


def _find_input_device_by_name(input_devices: list[tuple[int, dict[str, Any]]], name: str) -> tuple[int, dict[str, Any]] | None:
    normalized = _normalize_device_name(name)
    if not normalized:
        return None
    for index, info in input_devices:
        candidate = _normalize_device_name(str(info.get("name") or ""))
        if candidate == normalized:
            return index, info
    for index, info in input_devices:
        candidate = _normalize_device_name(str(info.get("name") or ""))
        if normalized in candidate:
            return index, info
    return None


def _normalize_device_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _clean_device_name(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _available_input_devices_message(devices: list[Any]) -> str:
    input_devices = _input_devices(devices)
    if not input_devices:
        return "Available input devices: none."
    lines = ["Available input devices:"]
    for index, info in input_devices:
        name = str(info.get("name") or f"Input device {index}")
        channels = int(info.get("max_input_channels") or 0)
        lines.append(f"- {index}: {name} ({channels} input channel(s))")
    return "\n".join(lines)


def _microphone_error(message: str) -> MicrophoneUnavailableError:
    return MicrophoneUnavailableError(message, detail=message)


def _load_preferred_microphone_name() -> str | None:
    try:
        from grandpa.core import config as core_config

        config_path = core_config.DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return None
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        voice_section = data.get("voice") if isinstance(data, dict) else None
        if not isinstance(voice_section, dict):
            return None
        return _clean_device_name(voice_section.get("preferred_microphone"))
    except Exception:
        return None


def save_preferred_microphone_name(name: str) -> str:
    cleaned = _clean_device_name(name)
    if not cleaned:
        raise ValueError("Microphone name cannot be empty.")
    import tomlkit

    from grandpa.core import config as core_config

    config_path = core_config.DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
    voice_section = doc.get("voice")
    if voice_section is None:
        voice_section = tomlkit.table()
        doc["voice"] = voice_section
    voice_section["preferred_microphone"] = cleaned
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return cleaned


def _captured_frame_count(recording: Any, fallback: int) -> int:
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
    total = sum(sample * sample for sample in samples)
    return math.sqrt(total / len(samples))


__all__ = [
    "AudioCaptureDiagnostics",
    "JarvisVoiceTranscript",
    "SoundDeviceMicrophoneRecorder",
    "VOICE_INPUT_INSTALL_MESSAGE",
    "calculate_pcm16_rms",
    "listen_for_jarvis_command",
    "save_preferred_microphone_name",
]
