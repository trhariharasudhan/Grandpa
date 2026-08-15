"""Reusable diagnostics for supervised microphone acceptance tests."""

from __future__ import annotations

import io
import math
import wave
from array import array
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AudioMetrics:
    """Objective PCM16 characteristics for one captured phrase."""

    duration_seconds: float
    sample_rate: int
    channels: int
    frame_count: int
    rms: float
    speech_active_rms: float
    peak_dbfs: float
    dynamic_range_db: float
    near_silent_percent: float
    speech_active_percent: float
    clipping_percent: float
    dc_offset: float
    zero_crossing_percent: float
    estimated_snr_db: float | None
    low_band_percent: float | None
    speech_band_percent: float | None
    high_band_percent: float | None

    def to_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def analyze_pcm16_wav(audio: bytes) -> AudioMetrics:
    """Analyze a PCM16 WAV without modifying its samples."""

    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        frames = wav_file.readframes(frame_count)
    if sample_width != 2:
        raise ValueError("Microphone diagnostics require PCM16 WAV audio.")

    samples = array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    mono = _downmix(samples, channels)
    if not mono:
        raise ValueError("The microphone capture contained no audio samples.")

    values = [float(sample) for sample in mono]
    absolute = [abs(value) for value in values]
    rms = _rms(values)
    peak = max(absolute)
    near_silent_cutoff = 164.0  # Approximately -46 dBFS.
    active_cutoff = max(180.0, rms * 0.75)
    active = [value for value in values if abs(value) >= active_cutoff]
    noise = [value for value in values if abs(value) < active_cutoff]
    active_rms = _rms(active)
    noise_rms = _rms(noise)
    snr = (
        20.0 * math.log10(active_rms / noise_rms)
        if active_rms > 0 and noise_rms > 0
        else None
    )
    nonzero = [value for value in absolute if value > 0]
    floor = _percentile(nonzero, 10.0) if nonzero else 0.0
    dynamic_range = 20.0 * math.log10(peak / floor) if peak > 0 and floor > 0 else 0.0
    crossings = sum(
        1 for left, right in zip(values, values[1:]) if (left < 0) != (right < 0)
    )
    low, speech, high = _spectral_distribution(values, sample_rate)
    return AudioMetrics(
        duration_seconds=frame_count / sample_rate if sample_rate else 0.0,
        sample_rate=sample_rate,
        channels=channels,
        frame_count=frame_count,
        rms=round(rms, 3),
        speech_active_rms=round(active_rms, 3),
        peak_dbfs=round(20.0 * math.log10(max(peak, 1.0) / 32768.0), 3),
        dynamic_range_db=round(dynamic_range, 3),
        near_silent_percent=round(
            100.0 * sum(value < near_silent_cutoff for value in absolute) / len(values),
            3,
        ),
        speech_active_percent=round(100.0 * len(active) / len(values), 3),
        clipping_percent=round(
            100.0 * sum(value >= 32767 for value in absolute) / len(values), 6
        ),
        dc_offset=round(sum(values) / len(values), 3),
        zero_crossing_percent=round(100.0 * crossings / max(1, len(values) - 1), 3),
        estimated_snr_db=round(snr, 3) if snr is not None else None,
        low_band_percent=low,
        speech_band_percent=speech,
        high_band_percent=high,
    )


def compare_audio(live: AudioMetrics, reference: AudioMetrics) -> dict[str, float]:
    """Return compact ratios useful when comparing live and known-good speech."""

    return {
        "rms_ratio": _safe_ratio(live.rms, reference.rms),
        "speech_active_rms_ratio": _safe_ratio(
            live.speech_active_rms, reference.speech_active_rms
        ),
        "speech_activity_ratio": _safe_ratio(
            live.speech_active_percent, reference.speech_active_percent
        ),
        "zero_crossing_ratio": _safe_ratio(
            live.zero_crossing_percent, reference.zero_crossing_percent
        ),
    }


def play_wav_bytes(audio: bytes) -> None:
    """Play a captured WAV synchronously through the configured Windows output."""

    import sounddevice as sounddevice
    import soundfile as soundfile

    data, sample_rate = soundfile.read(io.BytesIO(audio), dtype="float32")
    sounddevice.play(data, sample_rate)
    sounddevice.wait()


def _downmix(samples: array, channels: int) -> list[int]:
    if channels <= 1:
        return list(samples)
    usable = len(samples) - (len(samples) % channels)
    return [
        round(sum(samples[index : index + channels]) / channels)
        for index in range(0, usable, channels)
    ]


def _rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile / 100.0)
    return ordered[max(0, min(index, len(ordered) - 1))]


def _spectral_distribution(
    values: list[float], sample_rate: int
) -> tuple[float | None, float | None, float | None]:
    try:
        import numpy as np
    except ImportError:
        return None, None, None
    signal = np.asarray(values, dtype=np.float64)
    if signal.size < 2:
        return None, None, None
    signal -= signal.mean()
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(signal.size))) ** 2
    frequencies = np.fft.rfftfreq(signal.size, 1.0 / sample_rate)
    total = float(spectrum.sum())
    if total <= 0:
        return 0.0, 0.0, 0.0

    def band(start: float, end: float) -> float:
        mask = (frequencies >= start) & (frequencies < end)
        return round(float(spectrum[mask].sum()) * 100.0 / total, 3)

    return band(0, 300), band(300, 4_000), band(4_000, sample_rate / 2 + 1)


def _safe_ratio(value: float, baseline: float) -> float:
    return round(value / baseline, 3) if baseline else 0.0


__all__ = [
    "AudioMetrics",
    "analyze_pcm16_wav",
    "compare_audio",
    "play_wav_bytes",
]
