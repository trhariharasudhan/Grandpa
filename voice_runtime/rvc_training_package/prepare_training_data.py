"""Build the portable Hari RVC pilot dataset without modifying source recordings."""

from __future__ import annotations

import csv
import hashlib
import math
import shutil
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
RAW_ROOT = PROJECT_ROOT / "voice_runtime" / "datasets" / "hari_piper" / "raw"
DATASET_ROOT = PACKAGE_ROOT / "dataset"
TARGET_SAMPLE_RATE = 40_000
SILENCE_THRESHOLD_DBFS = -45.0
EDGE_PADDING_MS = 100
CLIPPING_THRESHOLD = 0.999
MAX_CLIPPED_FRACTION = 0.005
MIN_DURATION_SECONDS = 1.0
MIN_SNR_DB = 12.0


@dataclass(frozen=True)
class ManifestRecord:
    source_filename: str
    training_filename: str
    provenance: str
    source_format: str
    source_subtype: str
    source_sample_rate: int | None
    source_channels: int | None
    source_duration_seconds: float | None
    training_duration_seconds: float | None
    edge_trimmed_seconds: float | None
    peak_dbfs: float | None
    clipped_fraction: float | None
    estimated_snr_db: float | None
    transcript_present: bool
    accepted: bool
    reason: str
    source_sha256: str
    training_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype(np.float32, copy=False)
    return np.mean(audio, axis=1, dtype=np.float32)


def _trim_edge_silence(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    frame_size = max(1, round(sample_rate * 0.02))
    frame_count = math.ceil(len(audio) / frame_size)
    padded = np.pad(audio, (0, frame_count * frame_size - len(audio)))
    frames = padded.reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    threshold = 10 ** (SILENCE_THRESHOLD_DBFS / 20.0)
    active = np.flatnonzero(rms >= threshold)
    if not active.size:
        return np.array([], dtype=np.float32)
    padding = round(sample_rate * EDGE_PADDING_MS / 1000)
    start = max(0, int(active[0] * frame_size) - padding)
    end = min(len(audio), int((active[-1] + 1) * frame_size) + padding)
    return audio[start:end]


def _estimate_snr_db(audio: np.ndarray, sample_rate: int) -> float:
    frame_size = max(1, round(sample_rate * 0.02))
    frame_count = max(1, len(audio) // frame_size)
    frames = audio[: frame_count * frame_size].reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    return _dbfs(float(np.percentile(rms, 80))) - _dbfs(
        float(np.percentile(rms, 20))
    )


def _resample(audio: np.ndarray, source_rate: int) -> np.ndarray:
    if source_rate == TARGET_SAMPLE_RATE:
        return audio
    ratio = Fraction(TARGET_SAMPLE_RATE, source_rate)
    return resample_poly(audio, ratio.numerator, ratio.denominator).astype(np.float32)


def _candidate_paths() -> list[Path]:
    roots = (RAW_ROOT / "original", RAW_ROOT / "original_v2")
    return sorted(path for root in roots for path in root.glob("*.wav"))


def _prepare(path: Path) -> ManifestRecord:
    relative = path.relative_to(RAW_ROOT).as_posix()
    output_name = f"{path.parent.name}_{path.stem}.wav"
    output_path = DATASET_ROOT / output_name
    source_hash = _sha256(path)
    transcript_present = path.with_suffix(".txt").is_file()

    try:
        info = sf.info(path)
        audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    except Exception as exc:
        return ManifestRecord(
            relative, output_name, "original_microphone", "unknown", "unknown",
            None, None, None, None, None, None, None, None,
            transcript_present, False, f"audio decode failed: {exc}", source_hash, "",
        )

    mono = _mono(audio)
    source_duration = len(mono) / sample_rate
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    clipped_fraction = (
        float(np.mean(np.abs(mono) >= CLIPPING_THRESHOLD)) if mono.size else 1.0
    )
    trimmed = _trim_edge_silence(mono, sample_rate)
    trimmed_duration = len(trimmed) / sample_rate
    snr_db = _estimate_snr_db(trimmed, sample_rate) if trimmed.size else 0.0

    reasons: list[str] = []
    if not trimmed.size or peak <= 1e-6:
        reasons.append("silent or no detectable speech")
    if trimmed_duration < MIN_DURATION_SECONDS:
        reasons.append("speech duration is too short")
    if clipped_fraction > MAX_CLIPPED_FRACTION:
        reasons.append("excessive clipping")
    if snr_db < MIN_SNR_DB:
        reasons.append("estimated SNR below 12 dB")

    training_hash = ""
    if not reasons:
        prepared = np.clip(_resample(trimmed, sample_rate), -1.0, 1.0)
        sf.write(output_path, prepared, TARGET_SAMPLE_RATE, subtype="PCM_16", format="WAV")
        written = sf.info(output_path)
        if (
            written.format != "WAV"
            or written.subtype != "PCM_16"
            or written.channels != 1
            or written.samplerate != TARGET_SAMPLE_RATE
        ):
            output_path.unlink(missing_ok=True)
            reasons.append("prepared output failed PCM WAV verification")
        else:
            training_hash = _sha256(output_path)

    return ManifestRecord(
        source_filename=relative,
        training_filename=output_name,
        provenance="original_microphone",
        source_format=info.format,
        source_subtype=info.subtype,
        source_sample_rate=int(sample_rate),
        source_channels=int(audio.shape[1]),
        source_duration_seconds=round(source_duration, 6),
        training_duration_seconds=round(trimmed_duration, 6),
        edge_trimmed_seconds=round(source_duration - trimmed_duration, 6),
        peak_dbfs=round(_dbfs(peak), 3),
        clipped_fraction=round(clipped_fraction, 8),
        estimated_snr_db=round(snr_db, 3),
        transcript_present=transcript_present,
        accepted=not reasons,
        reason="; ".join(reasons) if reasons else "accepted",
        source_sha256=source_hash,
        training_sha256=training_hash,
    )


def main() -> None:
    if DATASET_ROOT.exists():
        shutil.rmtree(DATASET_ROOT)
    DATASET_ROOT.mkdir(parents=True)

    records = [_prepare(path) for path in _candidate_paths()]
    manifest_path = PACKAGE_ROOT / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ManifestRecord.__annotations__))
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))

    accepted = [record for record in records if record.accepted]
    rejected = [record for record in records if not record.accepted]
    total_duration = sum(record.training_duration_seconds or 0 for record in accepted)
    print(f"Accepted: {len(accepted)}")
    print(f"Rejected: {len(rejected)}")
    print(f"Accepted duration: {total_duration:.3f} seconds")
    print(f"Dataset: {DATASET_ROOT}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
