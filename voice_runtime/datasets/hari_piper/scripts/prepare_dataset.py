"""Prepare reviewed source clips for a single-speaker Piper pilot dataset.

This script is deliberately non-destructive: it reads only from ``raw/`` and
writes new files to ``processed/``, ``wavs/``, ``metadata/``, and ``reports/``.
It does not transcribe audio or silently accept uncertain transcripts.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_SAMPLE_RATE = 22_050
TARGET_PEAK_DBFS = -3.0
MAX_GAIN_DB = 12.0
SILENCE_THRESHOLD_DBFS = -45.0
SILENCE_PADDING_MS = 100
MIN_DURATION_SECONDS = 0.5
MAX_UTTERANCE_SECONDS = 15.0
CLIPPING_THRESHOLD = 0.999
MAX_CLIPPED_FRACTION = 0.005
MIN_ACCEPTABLE_SNR_DB = 6.0
REVIEW_SNR_DB = 12.0
ALLOWED_SOURCES = {"original", "synthetic_clone"}
REQUIRED_COLUMNS = {
    "clip_id",
    "filename",
    "transcript",
    "language",
    "style",
    "source",
}


@dataclass(frozen=True)
class ValidationRecord:
    clip_id: str
    source_filename: str
    output_filename: str
    transcript: str
    language: str
    style: str
    source: str
    source_duration_seconds: float | None
    processed_duration_seconds: float | None
    source_sample_rate: int | None
    source_channels: int | None
    peak_dbfs: float | None
    clipped_fraction: float | None
    estimated_snr_db: float | None
    quality_status: str
    reasons: list[str]


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _safe_clip_id(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    if not candidate or len(candidate) > 80:
        raise ValueError("clip_id must contain 1-80 letters, numbers, '_' or '-'")
    return candidate


def _resolve_inside(root: Path, relative_name: str) -> Path:
    candidate = (root / relative_name).resolve()
    if root.resolve() not in candidate.parents:
        raise ValueError("source filename escapes the raw dataset directory")
    return candidate


def _mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype(np.float32, copy=False)
    return np.mean(audio, axis=1, dtype=np.float32)


def _trim_silence(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    frame_size = max(1, int(sample_rate * 0.02))
    frame_count = math.ceil(len(audio) / frame_size)
    padded = np.pad(audio, (0, frame_count * frame_size - len(audio)))
    frames = padded.reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    active = np.flatnonzero(rms >= 10 ** (SILENCE_THRESHOLD_DBFS / 20.0))
    if active.size == 0:
        return np.array([], dtype=np.float32)
    padding = int(sample_rate * SILENCE_PADDING_MS / 1000)
    start = max(0, int(active[0] * frame_size) - padding)
    end = min(len(audio), int((active[-1] + 1) * frame_size) + padding)
    return audio[start:end]


def _estimate_snr_db(audio: np.ndarray, sample_rate: int) -> float:
    frame_size = max(1, int(sample_rate * 0.02))
    frame_count = max(1, len(audio) // frame_size)
    frames = audio[: frame_count * frame_size].reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    noise = float(np.percentile(rms, 20))
    speech = float(np.percentile(rms, 80))
    return _dbfs(speech) - _dbfs(noise)


def _resample(audio: np.ndarray, source_rate: int) -> np.ndarray:
    if source_rate == TARGET_SAMPLE_RATE:
        return audio
    ratio = Fraction(TARGET_SAMPLE_RATE, source_rate)
    return resample_poly(audio, ratio.numerator, ratio.denominator).astype(np.float32)


def _normalize(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio)))
    if peak <= 0:
        return audio
    desired_peak = 10 ** (TARGET_PEAK_DBFS / 20.0)
    gain = min(desired_peak / peak, 10 ** (MAX_GAIN_DB / 20.0))
    return np.clip(audio * gain, -1.0, 1.0).astype(np.float32)


def _read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"manifest is missing columns: {', '.join(sorted(missing))}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _process_row(row: dict[str, str], roots: dict[str, Path]) -> ValidationRecord:
    reasons: list[str] = []
    clip_id = _safe_clip_id(row["clip_id"])
    transcript = row["transcript"].strip()
    source_kind = row["source"].strip().lower()
    output_name = f"{clip_id}.wav"
    source_path = _resolve_inside(roots["raw"], row["filename"])

    if source_kind not in ALLOWED_SOURCES:
        reasons.append("source must be original or synthetic_clone")
    if not transcript:
        reasons.append("exact transcript is missing")
    if "|" in transcript or "\n" in transcript or "\r" in transcript:
        reasons.append("transcript contains a Piper metadata delimiter or newline")
    if not source_path.is_file():
        reasons.append("source file does not exist")
        return ValidationRecord(
            clip_id, row["filename"], output_name, transcript, row["language"],
            row["style"], source_kind, None, None, None, None, None, None, None,
            "rejected", reasons,
        )

    try:
        audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=True)
    except Exception as exc:
        reasons.append(f"audio decode failed: {exc.__class__.__name__}")
        return ValidationRecord(
            clip_id, row["filename"], output_name, transcript, row["language"],
            row["style"], source_kind, None, None, None, None, None, None, None,
            "rejected", reasons,
        )

    channels = int(audio.shape[1])
    source_duration = len(audio) / sample_rate
    mono = _mono(audio)
    source_peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    clipped_fraction = float(np.mean(np.abs(mono) >= CLIPPING_THRESHOLD)) if mono.size else 1.0
    if source_peak <= 1e-6:
        reasons.append("audio is silent")
    if clipped_fraction > MAX_CLIPPED_FRACTION:
        reasons.append("audio contains excessive clipping")

    trimmed = _trim_silence(mono, sample_rate)
    processed = _normalize(_resample(trimmed, sample_rate)) if trimmed.size else trimmed
    processed_duration = len(processed) / TARGET_SAMPLE_RATE
    snr_db = _estimate_snr_db(processed, TARGET_SAMPLE_RATE) if processed.size else 0.0
    if processed_duration < MIN_DURATION_SECONDS:
        reasons.append("utterance is too short")
    if processed_duration > MAX_UTTERANCE_SECONDS:
        reasons.append("utterance must be segmented before training")
    if snr_db < MIN_ACCEPTABLE_SNR_DB:
        reasons.append("estimated signal-to-noise ratio is extremely low")

    rejected = any(
        marker in reason
        for reason in reasons
        for marker in (
            "missing", "delimiter", "source", "decode", "silent", "clipping",
            "too short", "segmented", "extremely low",
        )
    )
    quality_status = "rejected" if rejected else "review" if snr_db < REVIEW_SNR_DB else "accepted"
    if quality_status != "rejected":
        processed_path = roots["processed"] / output_name
        wav_path = roots["wavs"] / output_name
        if processed_path.exists() or wav_path.exists():
            raise FileExistsError(f"refusing to overwrite prepared clip {output_name}")
        sf.write(processed_path, processed, TARGET_SAMPLE_RATE, subtype="PCM_16")
        shutil.copy2(processed_path, wav_path)

    return ValidationRecord(
        clip_id=clip_id,
        source_filename=row["filename"],
        output_filename=output_name,
        transcript=transcript,
        language=row["language"],
        style=row["style"],
        source=source_kind,
        source_duration_seconds=round(source_duration, 6),
        processed_duration_seconds=round(processed_duration, 6),
        source_sample_rate=int(sample_rate),
        source_channels=channels,
        peak_dbfs=round(_dbfs(source_peak), 3),
        clipped_fraction=round(clipped_fraction, 8),
        estimated_snr_db=round(snr_db, 3),
        quality_status=quality_status,
        reasons=reasons,
    )


def _write_outputs(records: list[ValidationRecord], roots: dict[str, Path]) -> None:
    extended_path = roots["metadata"] / "extended_manifest.csv"
    piper_path = roots["metadata"] / "metadata.csv"
    report_path = roots["reports"] / "validation_report.json"
    for path in (extended_path, piper_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")

    fields = list(asdict(records[0]).keys()) if records else list(ValidationRecord.__annotations__)
    with extended_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["reasons"] = "; ".join(record.reasons)
            writer.writerow(row)

    with piper_path.open("w", encoding="utf-8", newline="") as handle:
        for record in records:
            if record.quality_status == "accepted":
                handle.write(f"{record.output_filename}|{record.transcript}\n")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_sample_rate": TARGET_SAMPLE_RATE,
        "counts": {
            status: sum(record.quality_status == status for record in records)
            for status in ("accepted", "review", "rejected")
        },
        "records": [asdict(record) for record in records],
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    dataset_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=dataset_root / "metadata" / "source_manifest.csv",
        help="Reviewed source manifest; paths are resolved inside raw/.",
    )
    args = parser.parse_args()
    roots = {name: dataset_root / name for name in ("raw", "processed", "wavs", "metadata", "reports")}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)

    records = [_process_row(row, roots) for row in _read_manifest(args.manifest.resolve())]
    _write_outputs(records, roots)
    print(json.dumps({status: sum(r.quality_status == status for r in records) for status in ("accepted", "review", "rejected")}))
    return 0 if all(record.quality_status != "rejected" for record in records) else 2


if __name__ == "__main__":
    raise SystemExit(main())
