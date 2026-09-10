"""Tests for cloned-voice dataset preparation (Phase 7).

Every fixture is a synthetic WAV written into ``tmp_path`` with ``soundfile``.
Nothing here touches a microphone, a network, a model download, or an external
dataset, so the suite is deterministic and runs on a bare CI runner.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
import soundfile

from grandpa.speech.dataset_prep import (
    DEFAULT_SILENCE_THRESHOLD,
    MANIFEST_CSV_NAME,
    MANIFEST_JSON_NAME,
    REASON_EMPTY,
    REASON_MISSING_TRANSCRIPT,
    REASON_SILENT,
    REASON_TOO_LONG,
    REASON_TOO_SHORT,
    REASON_UNREADABLE,
    REASON_UNSUPPORTED,
    TARGET_SAMPLE_RATE,
    DatasetPrepError,
    discover_audio_files,
    format_report,
    load_transcripts,
    normalize_amplitude,
    prepare_dataset,
    preprocess_samples,
    read_manifest,
    resample_linear,
    strip_silence,
    to_mono,
    write_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tone(
    seconds: float,
    rate: int,
    *,
    freq: float = 220.0,
    amplitude: float = 0.5,
    channels: int = 1,
) -> np.ndarray:
    """Deterministic sine tone. Loud enough to survive silence trimming."""
    count = int(round(seconds * rate))
    t = np.arange(count, dtype=np.float64) / float(rate)
    wave = amplitude * np.sin(2.0 * math.pi * freq * t)
    if channels == 1:
        return wave
    return np.stack([wave] * channels, axis=1)


def _write_wav(path, samples: np.ndarray, rate: int) -> None:
    soundfile.write(path, samples, rate, subtype="PCM_16")


def _make_clip(directory, name: str, seconds: float, rate: int, **kwargs):
    path = directory / f"{name}.wav"
    _write_wav(path, _tone(seconds, rate, **kwargs), rate)
    return path


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------


class TestToMono:
    def test_mono_input_is_unchanged(self):
        mono = _tone(0.1, 24000)
        assert to_mono(mono).shape == mono.shape

    def test_stereo_is_averaged_to_mono(self):
        stereo = _tone(0.1, 24000, channels=2)
        result = to_mono(stereo)
        assert result.ndim == 1
        assert result.size == stereo.shape[0]
        # Identical channels average back to the original waveform.
        assert np.allclose(result, stereo[:, 0])

    def test_channels_with_different_content_are_averaged(self):
        left = np.array([1.0, 1.0, 1.0])
        right = np.array([0.0, 0.0, 0.0])
        assert np.allclose(to_mono(np.stack([left, right], axis=1)), 0.5)

    def test_three_dimensional_input_is_rejected(self):
        with pytest.raises(DatasetPrepError):
            to_mono(np.zeros((2, 2, 2)))


class TestResampleLinear:
    def test_44100_to_24000_changes_length_proportionally(self):
        samples = _tone(1.0, 44100)
        out = resample_linear(samples, 44100, TARGET_SAMPLE_RATE)
        assert out.size == TARGET_SAMPLE_RATE

    def test_16000_to_24000_upsamples(self):
        samples = _tone(1.0, 16000)
        out = resample_linear(samples, 16000, TARGET_SAMPLE_RATE)
        assert out.size == TARGET_SAMPLE_RATE

    def test_already_target_rate_is_a_noop(self):
        samples = _tone(0.5, TARGET_SAMPLE_RATE)
        out = resample_linear(samples, TARGET_SAMPLE_RATE, TARGET_SAMPLE_RATE)
        assert np.array_equal(out, samples)

    def test_endpoints_are_preserved(self):
        samples = np.array([0.0, 0.5, 1.0])
        out = resample_linear(samples, 3, 6)
        assert out[0] == pytest.approx(0.0)
        assert out[-1] == pytest.approx(1.0)

    def test_linear_ramp_stays_linear(self):
        ramp = np.linspace(0.0, 1.0, 100)
        out = resample_linear(ramp, 100, 200)
        assert np.allclose(out, np.linspace(0.0, 1.0, 200), atol=1e-6)

    def test_empty_and_single_sample_are_safe(self):
        assert resample_linear(np.zeros(0), 44100, 24000).size == 0
        assert resample_linear(np.array([0.25]), 44100, 24000).size == 1

    def test_non_positive_rate_is_rejected(self):
        with pytest.raises(DatasetPrepError):
            resample_linear(np.zeros(10), 0, 24000)

    def test_multichannel_input_is_rejected(self):
        with pytest.raises(DatasetPrepError):
            resample_linear(np.zeros((10, 2)), 44100, 24000)


class TestNormalizeAmplitude:
    def test_quiet_audio_is_scaled_up_to_peak(self):
        out, source_peak = normalize_amplitude(_tone(0.1, 24000, amplitude=0.05))
        assert source_peak == pytest.approx(0.05, abs=1e-3)
        assert float(np.max(np.abs(out))) == pytest.approx(0.95, abs=1e-6)

    def test_loud_audio_is_scaled_down(self):
        out, _ = normalize_amplitude(_tone(0.1, 24000, amplitude=1.0))
        assert float(np.max(np.abs(out))) <= 0.95 + 1e-9

    def test_silent_audio_is_not_divided_by_zero(self):
        out, source_peak = normalize_amplitude(np.zeros(100))
        assert source_peak == 0.0
        assert np.array_equal(out, np.zeros(100))

    def test_empty_audio_is_safe(self):
        out, source_peak = normalize_amplitude(np.zeros(0))
        assert out.size == 0
        assert source_peak == 0.0

    def test_non_positive_peak_is_rejected(self):
        with pytest.raises(DatasetPrepError):
            normalize_amplitude(np.ones(10), peak=0.0)


class TestStripSilence:
    def test_leading_and_trailing_silence_are_removed(self):
        speech = _tone(0.2, 24000, amplitude=0.5)
        padded = np.concatenate([np.zeros(2400), speech, np.zeros(4800)])
        trimmed, removed = strip_silence(padded)
        assert removed == pytest.approx(7200, abs=8)
        assert trimmed.size == pytest.approx(speech.size, abs=8)

    def test_interior_silence_is_preserved(self):
        speech = _tone(0.05, 24000)
        gap = np.zeros(2400)
        trimmed, _ = strip_silence(np.concatenate([speech, gap, speech]))
        assert trimmed.size >= speech.size * 2 + gap.size - 8

    def test_all_silence_becomes_empty(self):
        trimmed, removed = strip_silence(np.zeros(1000))
        assert trimmed.size == 0
        assert removed == 1000

    def test_empty_input_is_safe(self):
        trimmed, removed = strip_silence(np.zeros(0))
        assert trimmed.size == 0
        assert removed == 0

    def test_threshold_is_respected(self):
        quiet = np.full(100, DEFAULT_SILENCE_THRESHOLD / 2.0)
        assert strip_silence(quiet)[0].size == 0


class TestPreprocessChain:
    def test_stereo_44100_becomes_mono_24000_normalised(self):
        stereo = _tone(1.0, 44100, amplitude=0.2, channels=2)
        processed, source_peak, trimmed = preprocess_samples(stereo, 44100)
        assert processed.ndim == 1
        assert float(np.max(np.abs(processed))) == pytest.approx(0.95, abs=1e-6)
        assert source_peak == pytest.approx(0.2, abs=1e-2)
        assert trimmed >= 0.0
        assert processed.size == pytest.approx(TARGET_SAMPLE_RATE, abs=50)


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------


class TestLoadTranscripts:
    def test_json_object(self, tmp_path):
        path = tmp_path / "t.json"
        path.write_text(json.dumps({"a": "hello", "b": "world"}), encoding="utf-8")
        assert load_transcripts(path) == {"a": "hello", "b": "world"}

    def test_pipe_delimited(self, tmp_path):
        path = tmp_path / "metadata.csv"
        path.write_text("a|hello there\nb|second line\n", encoding="utf-8")
        assert load_transcripts(path) == {"a": "hello there", "b": "second line"}

    def test_comma_delimited_and_extension_is_stripped(self, tmp_path):
        path = tmp_path / "t.txt"
        path.write_text("a.wav,hello\n", encoding="utf-8")
        assert load_transcripts(path) == {"a": "hello"}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(DatasetPrepError):
            load_transcripts(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "t.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(DatasetPrepError):
            load_transcripts(path)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_audio_and_non_audio_are_separated(self, tmp_path):
        _make_clip(tmp_path, "one", 1.0, 24000)
        (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
        audio, other = discover_audio_files(tmp_path)
        assert [p.name for p in audio] == ["one.wav"]
        assert [p.name for p in other] == ["notes.txt"]

    def test_empty_directory(self, tmp_path):
        audio, other = discover_audio_files(tmp_path)
        assert audio == () and other == ()

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(DatasetPrepError):
            discover_audio_files(tmp_path / "absent")


# ---------------------------------------------------------------------------
# End-to-end preparation
# ---------------------------------------------------------------------------


class TestPrepareDataset:
    def test_mono_24k_clip_is_accepted_unchanged_in_rate(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "clip", 2.0, TARGET_SAMPLE_RATE)
        report = prepare_dataset(raw, out, transcripts={"clip": "hello"})

        assert report.clip_count == 1
        assert report.rejected_count == 0
        clip = report.clips[0]
        assert clip.sample_rate == TARGET_SAMPLE_RATE
        assert clip.source_sample_rate == TARGET_SAMPLE_RATE
        assert clip.source_channels == 1
        assert clip.output_path.is_file()

    def test_stereo_44100_is_converted(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "clip", 2.0, 44100, channels=2)
        report = prepare_dataset(raw, out, transcripts={"clip": "hello"})

        clip = report.clips[0]
        assert clip.source_sample_rate == 44100
        assert clip.source_channels == 2
        assert clip.sample_rate == TARGET_SAMPLE_RATE
        written, rate = soundfile.read(clip.output_path, always_2d=True)
        assert rate == TARGET_SAMPLE_RATE
        assert written.shape[1] == 1

    def test_16000_is_upsampled(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "clip", 2.0, 16000)
        report = prepare_dataset(raw, out, transcripts={"clip": "hello"})
        assert report.clips[0].source_sample_rate == 16000
        assert report.clips[0].duration_seconds == pytest.approx(2.0, abs=0.05)

    def test_duration_below_minimum_is_rejected(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "tiny", 0.2, TARGET_SAMPLE_RATE)
        report = prepare_dataset(
            raw, out, transcripts={"tiny": "x"}, min_duration_seconds=1.0
        )
        assert report.clip_count == 0
        assert report.rejected[0].reason == REASON_TOO_SHORT
        assert "0.2" in report.rejected[0].detail

    def test_duration_above_maximum_is_rejected(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "long", 3.0, TARGET_SAMPLE_RATE)
        report = prepare_dataset(
            raw, out, transcripts={"long": "x"}, max_duration_seconds=2.0
        )
        assert report.rejected[0].reason == REASON_TOO_LONG

    def test_missing_transcript_is_reported_not_dropped(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "orphan_audio", 2.0, TARGET_SAMPLE_RATE)
        report = prepare_dataset(raw, out, transcripts={})

        assert report.clip_count == 0
        assert report.rejected_count == 1
        assert report.rejected[0].reason == REASON_MISSING_TRANSCRIPT
        assert "orphan_audio" in report.rejected[0].detail

    def test_transcript_without_audio_is_reported(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "present", 2.0, TARGET_SAMPLE_RATE)
        report = prepare_dataset(
            raw, out, transcripts={"present": "ok", "absent": "no audio"}
        )
        assert report.clip_count == 1
        assert report.orphan_transcripts == ("absent",)

    def test_corrupt_audio_is_rejected_with_detail(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        (raw / "broken.wav").write_bytes(b"RIFFnot really a wav at all")
        report = prepare_dataset(raw, out, transcripts={"broken": "x"})

        assert report.clip_count == 0
        assert report.rejected[0].reason == REASON_UNREADABLE
        assert report.rejected[0].detail  # the exception is preserved

    def test_zero_length_audio_is_rejected(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _write_wav(raw / "empty.wav", np.zeros(0, dtype=np.float64), TARGET_SAMPLE_RATE)
        report = prepare_dataset(raw, out, transcripts={"empty": "x"})
        assert report.rejected[0].reason == REASON_EMPTY

    def test_all_silence_is_rejected(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _write_wav(
            raw / "quiet.wav", np.zeros(TARGET_SAMPLE_RATE * 2), TARGET_SAMPLE_RATE
        )
        report = prepare_dataset(raw, out, transcripts={"quiet": "x"})
        assert report.rejected[0].reason == REASON_SILENT

    def test_non_audio_file_is_reported(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        (raw / "readme.md").write_text("not audio", encoding="utf-8")
        report = prepare_dataset(raw, out, transcripts={})
        assert report.rejected[0].reason == REASON_UNSUPPORTED

    def test_empty_directory_yields_empty_report(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        report = prepare_dataset(raw, out, transcripts={})
        assert report.clip_count == 0
        assert report.rejected_count == 0
        assert report.total_duration_seconds == 0.0
        assert report.average_duration_seconds == 0.0

    def test_silence_is_trimmed_from_written_clip(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        speech = _tone(2.0, TARGET_SAMPLE_RATE)
        padded = np.concatenate(
            [np.zeros(TARGET_SAMPLE_RATE), speech, np.zeros(TARGET_SAMPLE_RATE)]
        )
        _write_wav(raw / "padded.wav", padded, TARGET_SAMPLE_RATE)

        report = prepare_dataset(raw, out, transcripts={"padded": "x"})
        clip = report.clips[0]
        assert clip.duration_seconds == pytest.approx(2.0, abs=0.05)
        assert clip.trimmed_seconds == pytest.approx(2.0, abs=0.05)

    def test_written_audio_is_normalised(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "quietclip", 2.0, TARGET_SAMPLE_RATE, amplitude=0.05)
        report = prepare_dataset(raw, out, transcripts={"quietclip": "x"})

        written, _ = soundfile.read(report.clips[0].output_path)
        assert float(np.max(np.abs(written))) > 0.9

    def test_write_audio_false_skips_files(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "clip", 2.0, TARGET_SAMPLE_RATE)
        report = prepare_dataset(raw, out, transcripts={"clip": "x"}, write_audio=False)
        assert report.clip_count == 1
        assert not report.clips[0].output_path.exists()

    def test_transcript_file_is_not_treated_as_audio(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "clip", 2.0, TARGET_SAMPLE_RATE)
        transcripts = raw / "metadata.csv"
        transcripts.write_text("clip|hello\n", encoding="utf-8")

        report = prepare_dataset(raw, out, transcript_file=transcripts)
        assert report.clip_count == 1
        assert report.rejected_count == 0

    def test_invalid_duration_bounds_are_rejected(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        with pytest.raises(DatasetPrepError):
            prepare_dataset(
                raw, out, min_duration_seconds=5.0, max_duration_seconds=1.0
            )


# ---------------------------------------------------------------------------
# Manifest and report
# ---------------------------------------------------------------------------


class TestManifestAndReport:
    def _prepared(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "one", 2.0, TARGET_SAMPLE_RATE)
        _make_clip(raw, "two", 3.0, 44100)
        report = prepare_dataset(
            raw, out, transcripts={"one": "first line", "two": "second line"}
        )
        return report, out

    def test_manifest_round_trip(self, tmp_path):
        report, out = self._prepared(tmp_path)
        csv_path, json_path = write_manifest(report, out)

        assert csv_path.name == MANIFEST_CSV_NAME
        assert json_path.name == MANIFEST_JSON_NAME

        rows = read_manifest(csv_path)
        assert len(rows) == 2
        by_id = {row["clip_id"]: row for row in rows}
        assert by_id["one"]["transcript"] == "first line"
        assert by_id["two"]["transcript"] == "second line"
        assert float(by_id["one"]["duration_seconds"]) == pytest.approx(2.0, abs=0.05)

    def test_manifest_json_carries_the_report(self, tmp_path):
        report, out = self._prepared(tmp_path)
        _, json_path = write_manifest(report, out)
        data = json.loads(json_path.read_text(encoding="utf-8"))

        assert data["clip_count"] == 2
        assert data["target_sample_rate"] == TARGET_SAMPLE_RATE
        assert set(data["source_sample_rates"]) == {"24000", "44100"}
        assert len(data["clips"]) == 2

    def test_report_totals_match_clips(self, tmp_path):
        report, _ = self._prepared(tmp_path)
        assert report.clip_count == 2
        assert report.total_duration_seconds == pytest.approx(5.0, abs=0.1)
        assert report.average_duration_seconds == pytest.approx(2.5, abs=0.05)
        assert report.source_sample_rates == {TARGET_SAMPLE_RATE: 1, 44100: 1}

    def test_rejections_by_reason_counts(self, tmp_path):
        raw, out = tmp_path / "raw", tmp_path / "out"
        raw.mkdir()
        _make_clip(raw, "short_a", 0.2, TARGET_SAMPLE_RATE)
        _make_clip(raw, "short_b", 0.2, TARGET_SAMPLE_RATE)
        (raw / "notes.txt").write_text("x", encoding="utf-8")

        report = prepare_dataset(
            raw,
            out,
            transcripts={"short_a": "a", "short_b": "b"},
            min_duration_seconds=1.0,
        )
        counts = report.rejections_by_reason()
        assert counts[REASON_TOO_SHORT] == 2
        assert counts[REASON_UNSUPPORTED] == 1

    def test_read_manifest_missing_file_raises(self, tmp_path):
        with pytest.raises(DatasetPrepError):
            read_manifest(tmp_path / "absent.csv")

    def test_format_report_mentions_key_totals(self, tmp_path):
        report, _ = self._prepared(tmp_path)
        text = format_report(report)
        assert "Accepted clips:   2" in text
        assert "24000 Hz" in text
