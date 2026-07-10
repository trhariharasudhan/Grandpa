"""Microphone diagnostics for Grandpa voice mode."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from grandpa.jarvis.voice_input import (
    VOICE_INPUT_INSTALL_MESSAGE,
    SoundDeviceMicrophoneRecorder,
)
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
)
from grandpa.voice.speech_input import SpeechInputEngine
from grandpa.voice.speech_output import SpeechOutputEngine


@dataclass(frozen=True)
class VoiceDeviceInfo:
    index: int
    name: str
    input_channels: int
    default: bool = False


def list_input_devices() -> tuple[VoiceDeviceInfo, ...]:
    sounddevice = _import_sounddevice()
    devices = sounddevice.query_devices()
    default_index = _default_input_device(sounddevice)
    result: list[VoiceDeviceInfo] = []
    for index, device in enumerate(devices):
        channels = int(device.get("max_input_channels") or 0)
        if channels <= 0:
            continue
        result.append(
            VoiceDeviceInfo(
                index=index,
                name=str(device.get("name") or f"Input device {index}"),
                input_channels=channels,
                default=index == default_index,
            )
        )
    return tuple(result)


def run_voice_doctor(*, duration_seconds: float = 2.0, device: int | None = None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        sounddevice = _import_sounddevice()
        checks.append(_check("sounddevice import", "pass", "sounddevice is installed."))
    except VoiceDependencyError as exc:
        checks.append(_check("sounddevice import", "warn", str(exc)))
        checks.extend(_stt_checks())
        checks.extend(_tts_checks())
        checks.append(_check("Windows microphone permission", "warn", _windows_permission_hint()))
        return checks

    try:
        devices = list_input_devices()
        if devices:
            checks.append(_check("input devices", "pass", f"{len(devices)} input device(s) found."))
        else:
            checks.append(_check("input devices", "warn", "No input devices were reported by sounddevice."))
    except Exception as exc:
        checks.append(_check("input devices", "warn", f"Could not list input devices: {exc}"))
        devices = ()

    default_index = _default_input_device(sounddevice)
    checks.append(
        _check(
            "default input device",
            "pass" if default_index is not None else "warn",
            str(default_index) if default_index is not None else "No default input device reported.",
        )
    )
    checks.append(_check("sample rate", "pass", "Using 16000 Hz for push-to-talk capture."))

    if devices:
        try:
            recorder = SoundDeviceMicrophoneRecorder(duration_seconds=duration_seconds, device=device)
            recorder.record_wav()
            status = "pass" if recorder.last_rms >= 250 else "warn"
            message = f"Recorded {duration_seconds:g}s. RMS level: {recorder.last_rms:.1f}."
            if status == "warn":
                message += " I did not hear much audio; check microphone or speak louder."
            checks.append(_check("record test", status, message))
        except MicrophoneUnavailableError as exc:
            checks.append(_check("record test", "warn", str(exc)))

    checks.extend(_stt_checks())
    checks.extend(_tts_checks())
    checks.append(_check("Windows microphone permission", "warn", _windows_permission_hint()))
    return checks


def _stt_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    faster_whisper = importlib.util.find_spec("faster_whisper") is not None
    checks.append(_check("faster-whisper import", "pass" if faster_whisper else "warn", "Installed." if faster_whisper else "Install with: uv sync --extra speech"))
    status = SpeechInputEngine().stt_status()
    checks.append(
        _check(
            "STT backend",
            "pass" if status.get("ready") else "warn",
            f"{status.get('engine')} model={status.get('model')} compute={status.get('compute_type')}",
        )
    )
    if faster_whisper:
        checks.append(_check("model availability", "warn", "First transcription may download/load the configured Whisper model."))
    return checks


def _tts_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    engine = SpeechOutputEngine()
    info = engine.diagnostics()
    ready = info.get("status") == "ready"
    backend = str(info.get("engine") or "print_only")
    voice = str(info.get("voice") or "default")
    checks.append(_check("TTS backend", "pass" if ready else "warn", f"{backend} available." if ready else "No audible TTS backend found; print-only fallback will be used."))
    checks.append(_check("TTS selected voice", "pass" if ready else "warn", voice))
    try:
        result = engine.speak("Hello, I am Grandpa.", interrupt=True, dry_run=True)
        checks.append(_check("TTS speech test", "pass" if result.status in {"dry_run", "completed"} else "warn", result.message))
    except Exception as exc:
        checks.append(_check("TTS speech test", "warn", str(exc)))
    return checks


def _import_sounddevice():
    try:
        import sounddevice  # type: ignore
    except ImportError as exc:
        raise VoiceDependencyError(VOICE_INPUT_INSTALL_MESSAGE, detail=str(exc)) from exc
    return sounddevice


def _default_input_device(sounddevice) -> int | None:
    try:
        default = sounddevice.default.device
        if isinstance(default, (list, tuple)):
            value = default[0]
        else:
            value = default
        return int(value) if value is not None and int(value) >= 0 else None
    except Exception:
        return None


def _windows_permission_hint() -> str:
    return "On Windows, check Settings > Privacy & security > Microphone and allow desktop apps to access the microphone."


def _check(name: str, status: str, message: str) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message}


__all__ = ["VoiceDeviceInfo", "list_input_devices", "run_voice_doctor"]
