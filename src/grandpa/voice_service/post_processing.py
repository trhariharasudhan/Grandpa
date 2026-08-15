"""Deterministic FFmpeg character processing for cloned voice output."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class CharacterVoiceProcessingError(RuntimeError):
    """Raised when local character processing cannot produce valid WAV audio."""


@dataclass(frozen=True, slots=True)
class CharacterVoiceSettings:
    """Bounded settings for Grandpa's non-ML voice character stage."""

    enabled: bool = True
    pitch_semitones: float = -2.0
    speed: float = 0.92
    target_lufs: float = -14.5
    true_peak_db: float = -1.0
    compression: bool = True
    eq_profile: str = "grandpa_deep_clear"


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class FFmpegCharacterVoiceProcessor:
    """Apply bounded pitch, pace, dynamics, EQ, and loudness processing."""

    def __init__(
        self,
        settings: CharacterVoiceSettings,
        *,
        ffmpeg_path: str = "",
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.settings = settings
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or ""
        self._run = command_runner or _run_command

    def process(self, wav_bytes: bytes) -> bytes:
        if not self.settings.enabled:
            return wav_bytes
        if not self.ffmpeg_path:
            raise CharacterVoiceProcessingError("FFmpeg is not available")

        with tempfile.TemporaryDirectory(prefix="grandpa-voice-") as temp_dir:
            root = Path(temp_dir)
            source = root / "raw.wav"
            output = root / "character.wav"
            source.write_bytes(wav_bytes)
            sample_rate = _wav_sample_rate(source)
            base_filters = build_character_filters(self.settings, sample_rate)
            measurement = self._measure_loudness(source, base_filters)
            loudnorm = _second_pass_loudnorm(self.settings, measurement)
            limiter = _true_peak_limiter(self.settings.true_peak_db)
            command = [
                self.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-af",
                ",".join((*base_filters, loudnorm, limiter)),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
            completed = self._run(command)
            if completed.returncode != 0 or not output.is_file():
                detail = (completed.stderr or "FFmpeg produced no output").strip()
                raise CharacterVoiceProcessingError(detail)
            processed = output.read_bytes()
            if not processed.startswith(b"RIFF"):
                raise CharacterVoiceProcessingError("FFmpeg returned an invalid WAV")
            return processed

    def _measure_loudness(
        self,
        source: Path,
        base_filters: tuple[str, ...],
    ) -> dict[str, float]:
        loudnorm = (
            f"loudnorm=I={self.settings.target_lufs}:"
            f"TP={self.settings.true_peak_db}:LRA=7:print_format=json"
        )
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostats",
            "-i",
            str(source),
            "-af",
            ",".join((*base_filters, loudnorm)),
            "-f",
            "null",
            "NUL",
        ]
        completed = self._run(command)
        if completed.returncode != 0:
            raise CharacterVoiceProcessingError(completed.stderr.strip())
        return _parse_loudnorm_measurement(completed.stderr)


def build_character_filters(
    settings: CharacterVoiceSettings,
    sample_rate: int,
) -> tuple[str, ...]:
    """Return the deterministic pre-normalization FFmpeg filter chain."""
    filters = []

    # Avoid asetrate / aresample / atempo if pitch is exactly 0.0
    if settings.pitch_semitones != 0.0:
        pitch_ratio = 2.0 ** (settings.pitch_semitones / 12.0)
        tempo = settings.speed / pitch_ratio
        filters.extend(
            [
                f"asetrate={sample_rate}*{pitch_ratio:.8f}",
                f"aresample={sample_rate}",
                f"atempo={tempo:.8f}",
            ]
        )
    elif settings.speed != 1.0:
        filters.append(f"atempo={settings.speed:.8f}")

    filters.append("highpass=f=70")

    if settings.compression:
        if settings.eq_profile == "grandpa_presence":
            # Slightly stronger compression/body than F (Clarity)
            filters.append(
                "acompressor=threshold=0.08:ratio=2.5:attack=15:release=180:"
                "makeup=1.5:knee=2.828"
            )
        elif settings.eq_profile == "grandpa_clarity":
            # Very light compression for clarity
            filters.append(
                "acompressor=threshold=0.15:ratio=1.8:attack=25:release=220:"
                "makeup=1.2:knee=2.828"
            )
        else:
            filters.append(
                "acompressor=threshold=0.10:ratio=2:attack=20:release=200:"
                "makeup=1.5:knee=2.828"
            )
    filters.extend(_eq_filters(settings.eq_profile))
    return tuple(filters)


def _eq_filters(profile: str) -> tuple[str, ...]:
    if profile == "grandpa_balanced":
        return (
            "equalizer=f=140:t=q:w=1:g=2",
            "equalizer=f=3000:t=q:w=1:g=1",
        )
    if profile == "grandpa_deep":
        return (
            "equalizer=f=130:t=q:w=1:g=3",
            "equalizer=f=350:t=q:w=1:g=-1.5",
            "equalizer=f=3000:t=q:w=1:g=1.5",
        )
    if profile == "grandpa_balanced_clear":
        return (
            "equalizer=f=140:t=q:w=1:g=0.75",
            "equalizer=f=320:t=q:w=1:g=-0.75",
            "equalizer=f=3000:t=q:w=0.8:g=1.5",
        )
    if profile == "grandpa_deep_clear":
        return (
            "equalizer=f=135:t=q:w=1:g=1.5",
            "equalizer=f=320:t=q:w=1:g=-1",
            "equalizer=f=3000:t=q:w=0.8:g=1.75",
        )
    if profile == "grandpa_clarity":
        return (
            "equalizer=f=300:t=q:w=1.0:g=-1.5",  # small mud reduction around 250-350 Hz
            "equalizer=f=3000:t=q:w=0.8:g=1.5",  # mild broad presence enhancement around 2-4 kHz
        )
    if profile == "grandpa_presence":
        return (
            "equalizer=f=150:t=q:w=1.0:g=1.0",  # body
            "equalizer=f=3000:t=q:w=0.8:g=2.0",  # mild presence enhancement
        )
    if profile in {"none", "flat"}:
        return ()
    raise CharacterVoiceProcessingError(f"Unknown EQ profile: {profile}")


def _parse_loudnorm_measurement(stderr: str) -> dict[str, float]:
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        raise CharacterVoiceProcessingError("FFmpeg loudness measurement was missing")
    try:
        raw = json.loads(stderr[start : end + 1])
        return {
            "input_i": float(raw["input_i"]),
            "input_lra": float(raw["input_lra"]),
            "input_tp": float(raw["input_tp"]),
            "input_thresh": float(raw["input_thresh"]),
            "target_offset": float(raw["target_offset"]),
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CharacterVoiceProcessingError(
            "FFmpeg returned invalid loudness measurements"
        ) from exc


def _second_pass_loudnorm(
    settings: CharacterVoiceSettings,
    measured: dict[str, float],
) -> str:
    return (
        f"loudnorm=I={settings.target_lufs}:TP={settings.true_peak_db}:LRA=7:"
        f"measured_I={measured['input_i']}:measured_LRA={measured['input_lra']}:"
        f"measured_TP={measured['input_tp']}:"
        f"measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true"
    )


def _true_peak_limiter(target_db: float) -> str:
    # Leave a small inter-sample margin because alimiter operates on samples.
    limit = 10.0 ** ((target_db - 0.15) / 20.0)
    return f"alimiter=limit={limit:.8f}:attack=5:release=50:level=false:latency=true"


def _wav_sample_rate(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as wav_file:
            return wav_file.getframerate()
    except (OSError, EOFError, wave.Error) as exc:
        raise CharacterVoiceProcessingError("F5 returned an invalid WAV") from exc


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )


def validate_character_voice_settings(settings: CharacterVoiceSettings) -> None:
    """Reject unsafe or artifact-prone character processing values."""
    numeric = {
        "pitch_semitones": settings.pitch_semitones,
        "speed": settings.speed,
        "target_lufs": settings.target_lufs,
        "true_peak_db": settings.true_peak_db,
    }
    if any(
        isinstance(value, bool) or not math.isfinite(float(value))
        for value in numeric.values()
    ):
        raise ValueError("Character voice numeric settings must be finite numbers")
    if not -4.0 <= settings.pitch_semitones <= 2.0:
        raise ValueError("grandpa_voice.pitch_semitones must be between -4 and 2")
    if not 0.75 <= settings.speed <= 1.25:
        raise ValueError("grandpa_voice.character_speed must be between 0.75 and 1.25")
    if not -24.0 <= settings.target_lufs <= -10.0:
        raise ValueError("grandpa_voice.target_lufs must be between -24 and -10")
    if not -6.0 <= settings.true_peak_db <= -0.1:
        raise ValueError("grandpa_voice.true_peak_db must be between -6 and -0.1")
    if settings.eq_profile not in {
        "grandpa_balanced",
        "grandpa_deep",
        "grandpa_balanced_clear",
        "grandpa_deep_clear",
        "grandpa_clarity",
        "grandpa_presence",
        "none",
        "flat",
    }:
        raise ValueError("grandpa_voice.eq_profile is not supported")


__all__ = [
    "CharacterVoiceProcessingError",
    "CharacterVoiceSettings",
    "FFmpegCharacterVoiceProcessor",
    "build_character_filters",
    "validate_character_voice_settings",
]
