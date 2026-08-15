from __future__ import annotations

import io
import math
import wave
from array import array

from grandpa.voice.audio_diagnostics import analyze_pcm16_wav, compare_audio


def _wav(samples: list[int], *, sample_rate: int = 16_000) -> bytes:
    buffer = io.BytesIO()
    values = array("h", samples)
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(values.tobytes())
    return buffer.getvalue()


def test_audio_metrics_distinguish_speech_activity_from_silence() -> None:
    silence = [0] * 1_600
    speech = [round(2_000 * math.sin(index / 8)) for index in range(3_200)]

    metrics = analyze_pcm16_wav(_wav(silence + speech + silence))

    assert metrics.duration_seconds == 0.4
    assert metrics.rms > 500
    assert metrics.speech_active_rms > metrics.rms
    assert 0 < metrics.speech_active_percent < 100
    assert metrics.clipping_percent == 0
    assert metrics.speech_band_percent is not None


def test_compare_audio_uses_speech_active_characteristics() -> None:
    reference = analyze_pcm16_wav(_wav([1_000, -1_000] * 800))
    live = analyze_pcm16_wav(_wav([500, -500] * 800))

    comparison = compare_audio(live, reference)

    assert comparison["rms_ratio"] == 0.5
    assert comparison["speech_active_rms_ratio"] == 0.5


def test_audio_metrics_reject_non_pcm16_wav() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(8_000)
        wav_file.writeframes(b"\x80" * 100)

    try:
        analyze_pcm16_wav(buffer.getvalue())
    except ValueError as exc:
        assert "PCM16" in str(exc)
    else:  # pragma: no cover - protects the validation contract
        raise AssertionError("Expected non-PCM16 audio to be rejected")
