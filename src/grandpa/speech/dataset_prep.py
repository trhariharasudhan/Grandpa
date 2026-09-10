"""Dataset preparation for local cloned-voice reference clips.

Phase 7 of ``implementation_plan.md``. Ingests raw recordings, normalises them
to the 24 kHz mono form the F5 voice service expects, aligns each clip with its
transcript, and emits a manifest plus a validation report.

The module is deliberately pure and offline: it reads and writes files through
``soundfile`` and does arithmetic with ``numpy``. It never loads a model, opens
a socket, or touches the TTS registry, so it is testable without audio hardware
or a running voice service.

Resampling uses NumPy linear interpolation rather than ``scipy``/``librosa`` so
the ``voice`` extra gains no new dependency, and rather than ``audioop`` — which
is deprecated and slated for removal in Python 3.13.

Nothing here trains or fine-tunes a voice. This phase only prepares data.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

import numpy as np

logger = logging.getLogger(__name__)

#: Sample rate the F5 voice service and the rest of ``speech/`` standardise on.
TARGET_SAMPLE_RATE = 24000

DEFAULT_MIN_DURATION_SECONDS = 1.0
DEFAULT_MAX_DURATION_SECONDS = 30.0

#: Absolute amplitude below which a sample counts as silence when trimming.
DEFAULT_SILENCE_THRESHOLD = 0.01

#: Peak the normaliser targets. Below 1.0 to leave headroom against clipping
#: once the clip is re-encoded.
DEFAULT_NORMALIZE_PEAK = 0.95

SUPPORTED_SUFFIXES: Tuple[str, ...] = (".wav", ".flac", ".ogg", ".aiff", ".aif")

MANIFEST_CSV_NAME = "metadata.csv"
MANIFEST_JSON_NAME = "metadata.json"

# Rejection reasons. Stable strings so callers and tests can assert on them
# rather than on prose.
REASON_UNSUPPORTED = "unsupported_file"
REASON_UNREADABLE = "unreadable_audio"
REASON_EMPTY = "empty_audio"
REASON_SILENT = "silent_audio"
REASON_TOO_SHORT = "duration_below_minimum"
REASON_TOO_LONG = "duration_above_maximum"
REASON_MISSING_TRANSCRIPT = "missing_transcript"


class DatasetPrepError(RuntimeError):
    """Controlled failure raised for unusable inputs to dataset preparation."""


@dataclass(frozen=True)
class ClipRecord:
    """One accepted clip and how it was transformed."""

    source_path: Path
    output_path: Path
    clip_id: str
    transcript: str
    duration_seconds: float
    sample_rate: int
    source_sample_rate: int
    source_channels: int
    peak: float
    trimmed_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "source_path": str(self.source_path),
            "output_path": str(self.output_path),
            "transcript": self.transcript,
            "duration_seconds": round(self.duration_seconds, 6),
            "sample_rate": self.sample_rate,
            "source_sample_rate": self.source_sample_rate,
            "source_channels": self.source_channels,
            "peak": round(self.peak, 6),
            "trimmed_seconds": round(self.trimmed_seconds, 6),
        }


@dataclass(frozen=True)
class RejectedClip:
    """A clip that was not accepted, and why.

    Rejections are recorded rather than logged-and-forgotten so a caller can
    show the operator exactly which recordings need attention.
    """

    source_path: Path
    reason: str
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DatasetReport:
    """Validation report for one preparation run."""

    clips: Tuple[ClipRecord, ...] = ()
    rejected: Tuple[RejectedClip, ...] = ()
    #: Transcript keys with no matching audio file. Surfaced, never dropped.
    orphan_transcripts: Tuple[str, ...] = ()
    target_sample_rate: int = TARGET_SAMPLE_RATE
    source_sample_rates: Dict[int, int] = field(default_factory=dict)

    @property
    def clip_count(self) -> int:
        return len(self.clips)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def total_duration_seconds(self) -> float:
        return float(sum(clip.duration_seconds for clip in self.clips))

    @property
    def average_duration_seconds(self) -> float:
        if not self.clips:
            return 0.0
        return self.total_duration_seconds / len(self.clips)

    def rejections_by_reason(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.rejected:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_count": self.clip_count,
            "rejected_count": self.rejected_count,
            "total_duration_seconds": round(self.total_duration_seconds, 6),
            "average_duration_seconds": round(self.average_duration_seconds, 6),
            "target_sample_rate": self.target_sample_rate,
            "source_sample_rates": {
                str(rate): count
                for rate, count in sorted(self.source_sample_rates.items())
            },
            "orphan_transcripts": list(self.orphan_transcripts),
            "rejections_by_reason": self.rejections_by_reason(),
            "clips": [clip.to_dict() for clip in self.clips],
            "rejected": [item.to_dict() for item in self.rejected],
        }


# ---------------------------------------------------------------------------
# Signal helpers — pure NumPy, no I/O
# ---------------------------------------------------------------------------


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Downmix ``samples`` to a 1-D mono signal by averaging channels."""
    array = np.asarray(samples, dtype=np.float64)
    if array.ndim == 1:
        return array
    if array.ndim != 2:
        raise DatasetPrepError(f"expected 1-D or 2-D audio, got {array.ndim}-D")
    if array.shape[1] == 1:
        return array[:, 0]
    return array.mean(axis=1)


def resample_linear(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int = TARGET_SAMPLE_RATE,
) -> np.ndarray:
    """Resample a mono signal with linear interpolation.

    Chosen over a polyphase filter to keep the ``voice`` extra dependency-free.
    Adequate for reference clips; it does not low-pass before decimation, so
    downsampling can alias above the new Nyquist frequency.
    """
    if source_rate <= 0 or target_rate <= 0:
        raise DatasetPrepError(
            f"sample rates must be positive, got {source_rate} -> {target_rate}"
        )
    array = np.asarray(samples, dtype=np.float64)
    if array.ndim != 1:
        raise DatasetPrepError("resample_linear expects a mono (1-D) signal")
    if source_rate == target_rate or array.size == 0:
        return array
    if array.size == 1:
        return array.copy()

    duration = array.size / float(source_rate)
    target_size = int(round(duration * target_rate))
    if target_size <= 0:
        return np.zeros(0, dtype=np.float64)

    source_positions = np.arange(array.size, dtype=np.float64)
    target_positions = np.linspace(0.0, array.size - 1, target_size, dtype=np.float64)
    return np.interp(target_positions, source_positions, array)


def normalize_amplitude(
    samples: np.ndarray,
    peak: float = DEFAULT_NORMALIZE_PEAK,
) -> Tuple[np.ndarray, float]:
    """Scale ``samples`` so the loudest sample sits at ``peak``.

    Returns ``(normalised, source_peak)``. A silent or empty signal is returned
    unchanged rather than divided by zero.
    """
    if peak <= 0.0:
        raise DatasetPrepError(f"normalisation peak must be positive, got {peak}")
    array = np.asarray(samples, dtype=np.float64)
    if array.size == 0:
        return array, 0.0
    source_peak = float(np.max(np.abs(array)))
    if source_peak <= 0.0:
        return array, 0.0
    return array * (peak / source_peak), source_peak


def strip_silence(
    samples: np.ndarray,
    threshold: float = DEFAULT_SILENCE_THRESHOLD,
) -> Tuple[np.ndarray, int]:
    """Trim leading and trailing samples quieter than ``threshold``.

    Returns ``(trimmed, removed_sample_count)``. Interior silence is preserved —
    only the head and tail are trimmed, so pauses inside speech survive.
    """
    array = np.asarray(samples, dtype=np.float64)
    if array.size == 0:
        return array, 0
    voiced = np.flatnonzero(np.abs(array) > threshold)
    if voiced.size == 0:
        return np.zeros(0, dtype=np.float64), int(array.size)
    first = int(voiced[0])
    last = int(voiced[-1])
    trimmed = array[first : last + 1]
    return trimmed, int(array.size - trimmed.size)


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------


def load_transcripts(path: Path) -> Dict[str, str]:
    """Load transcripts keyed by clip id from a JSON or delimited text file.

    Accepts a JSON object, a two-column CSV, or a pipe-delimited file in the
    ``clip_id|transcript`` form F5/LJSpeech datasets use.
    """
    source = Path(path)
    if not source.is_file():
        raise DatasetPrepError(f"transcript file not found: {source}")

    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DatasetPrepError(
                f"invalid transcript JSON in {source}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise DatasetPrepError(f"transcript JSON must be an object: {source}")
        return {str(key): str(value) for key, value in data.items()}

    transcripts: Dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        delimiter = "|" if "|" in line else ","
        clip_id, _, transcript = line.partition(delimiter)
        clip_id = clip_id.strip()
        if not clip_id:
            continue
        transcripts[Path(clip_id).stem] = transcript.strip()
    return transcripts


# ---------------------------------------------------------------------------
# Ingestion and preprocessing
# ---------------------------------------------------------------------------


def discover_audio_files(
    raw_dir: Path,
    *,
    exclude: Iterable[Path] = (),
) -> Tuple[Tuple[Path, ...], Tuple[Path, ...]]:
    """Return ``(audio_files, other_files)`` found directly under ``raw_dir``.

    Non-audio files are returned rather than ignored so the caller can report
    them instead of silently skipping content the operator expected to be used.
    """
    directory = Path(raw_dir)
    if not directory.is_dir():
        raise DatasetPrepError(f"raw audio directory not found: {directory}")

    excluded = {Path(item).resolve() for item in exclude}
    audio: list[Path] = []
    other: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.resolve() in excluded:
            continue
        if entry.suffix.lower() in SUPPORTED_SUFFIXES:
            audio.append(entry)
        else:
            other.append(entry)
    return tuple(audio), tuple(other)


def preprocess_samples(
    samples: np.ndarray,
    source_rate: int,
    *,
    target_rate: int = TARGET_SAMPLE_RATE,
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
    normalize_peak: float = DEFAULT_NORMALIZE_PEAK,
) -> Tuple[np.ndarray, float, float]:
    """Run the full preprocessing chain on decoded audio.

    Order matters: downmix, resample, trim, then normalise. Normalising last
    means the trimmed clip uses the full headroom rather than being scaled by a
    peak that may have sat inside the removed silence.

    Returns ``(processed, source_peak, trimmed_seconds)``.
    """
    mono = to_mono(samples)
    resampled = resample_linear(mono, source_rate, target_rate)
    trimmed, removed = strip_silence(resampled, silence_threshold)
    normalised, source_peak = normalize_amplitude(trimmed, normalize_peak)
    trimmed_seconds = removed / float(target_rate) if target_rate else 0.0
    return normalised, source_peak, trimmed_seconds


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def write_manifest(report: DatasetReport, output_dir: Path) -> Tuple[Path, Path]:
    """Write ``metadata.csv`` and ``metadata.json`` for ``report``.

    The CSV is pipe-delimited ``clip_id|transcript|duration_seconds`` so it
    stays readable by the LJSpeech-style tooling F5 datasets use; the JSON
    carries the full records and the validation report.
    """
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    csv_path = directory / MANIFEST_CSV_NAME
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="|", lineterminator="\n")
        for clip in report.clips:
            writer.writerow(
                [clip.clip_id, clip.transcript, f"{clip.duration_seconds:.6f}"]
            )

    json_path = directory / MANIFEST_JSON_NAME
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return csv_path, json_path


def read_manifest(csv_path: Path) -> Tuple[Dict[str, str], ...]:
    """Read a manifest written by :func:`write_manifest`."""
    source = Path(csv_path)
    if not source.is_file():
        raise DatasetPrepError(f"manifest not found: {source}")
    rows: list[Dict[str, str]] = []
    with source.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="|"):
            if not row:
                continue
            clip_id = row[0]
            transcript = row[1] if len(row) > 1 else ""
            duration = row[2] if len(row) > 2 else "0"
            rows.append(
                {
                    "clip_id": clip_id,
                    "transcript": transcript,
                    "duration_seconds": duration,
                }
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def prepare_dataset(
    raw_dir: Path,
    output_dir: Path,
    *,
    transcripts: Mapping[str, str] | None = None,
    transcript_file: Path | None = None,
    target_rate: int = TARGET_SAMPLE_RATE,
    min_duration_seconds: float = DEFAULT_MIN_DURATION_SECONDS,
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
    normalize_peak: float = DEFAULT_NORMALIZE_PEAK,
    write_audio: bool = True,
) -> DatasetReport:
    """Prepare every clip in ``raw_dir`` and return a validation report.

    Each clip is decoded, downmixed, resampled to ``target_rate``, trimmed,
    normalised, matched to a transcript and checked against the duration
    bounds. Anything that fails is recorded in ``report.rejected`` with a
    stable reason rather than being dropped.
    """
    import soundfile as sf

    if min_duration_seconds < 0:
        raise DatasetPrepError("min_duration_seconds must not be negative")
    if max_duration_seconds < min_duration_seconds:
        raise DatasetPrepError(
            "max_duration_seconds must be greater than or equal to min_duration_seconds"
        )

    resolved_transcripts: Dict[str, str] = {}
    if transcript_file is not None:
        resolved_transcripts.update(load_transcripts(transcript_file))
    if transcripts is not None:
        resolved_transcripts.update({str(k): str(v) for k, v in transcripts.items()})

    exclude = (transcript_file,) if transcript_file is not None else ()
    audio_files, other_files = discover_audio_files(raw_dir, exclude=exclude)

    destination = Path(output_dir)
    if write_audio:
        destination.mkdir(parents=True, exist_ok=True)

    clips: list[ClipRecord] = []
    rejected: list[RejectedClip] = []
    source_rates: Dict[int, int] = {}
    matched_ids: set[str] = set()

    for path in other_files:
        rejected.append(
            RejectedClip(
                source_path=path,
                reason=REASON_UNSUPPORTED,
                detail=f"unsupported suffix '{path.suffix}'",
            )
        )

    for path in audio_files:
        clip_id = path.stem
        try:
            samples, source_rate = sf.read(path, dtype="float64", always_2d=True)
        except Exception as exc:  # soundfile raises several unrelated types
            rejected.append(
                RejectedClip(
                    source_path=path,
                    reason=REASON_UNREADABLE,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        source_rate = int(source_rate)
        source_channels = int(samples.shape[1]) if samples.ndim == 2 else 1
        source_rates[source_rate] = source_rates.get(source_rate, 0) + 1

        if samples.shape[0] == 0:
            rejected.append(
                RejectedClip(
                    source_path=path,
                    reason=REASON_EMPTY,
                    detail="decoded audio contains no frames",
                )
            )
            continue

        processed, source_peak, trimmed_seconds = preprocess_samples(
            samples,
            source_rate,
            target_rate=target_rate,
            silence_threshold=silence_threshold,
            normalize_peak=normalize_peak,
        )

        if processed.size == 0:
            rejected.append(
                RejectedClip(
                    source_path=path,
                    reason=REASON_SILENT,
                    detail=(
                        f"no samples above the silence threshold ({silence_threshold})"
                    ),
                )
            )
            continue

        duration = processed.size / float(target_rate)
        if duration < min_duration_seconds:
            rejected.append(
                RejectedClip(
                    source_path=path,
                    reason=REASON_TOO_SHORT,
                    detail=f"{duration:.3f}s < {min_duration_seconds:.3f}s",
                )
            )
            continue
        if duration > max_duration_seconds:
            rejected.append(
                RejectedClip(
                    source_path=path,
                    reason=REASON_TOO_LONG,
                    detail=f"{duration:.3f}s > {max_duration_seconds:.3f}s",
                )
            )
            continue

        if clip_id not in resolved_transcripts:
            rejected.append(
                RejectedClip(
                    source_path=path,
                    reason=REASON_MISSING_TRANSCRIPT,
                    detail=f"no transcript for clip id '{clip_id}'",
                )
            )
            continue

        matched_ids.add(clip_id)
        output_path = destination / f"{clip_id}.wav"
        if write_audio:
            sf.write(output_path, processed, target_rate, subtype="PCM_16")

        clips.append(
            ClipRecord(
                source_path=path,
                output_path=output_path,
                clip_id=clip_id,
                transcript=resolved_transcripts[clip_id],
                duration_seconds=duration,
                sample_rate=target_rate,
                source_sample_rate=source_rate,
                source_channels=source_channels,
                peak=source_peak,
                trimmed_seconds=trimmed_seconds,
            )
        )

    orphans = tuple(sorted(set(resolved_transcripts) - matched_ids))
    if orphans:
        logger.warning(
            "dataset_prep: %d transcript(s) had no matching audio: %s",
            len(orphans),
            ", ".join(orphans),
        )

    return DatasetReport(
        clips=tuple(clips),
        rejected=tuple(rejected),
        orphan_transcripts=orphans,
        target_sample_rate=target_rate,
        source_sample_rates=source_rates,
    )


def format_report(report: DatasetReport) -> str:
    """Render ``report`` as a short human-readable validation summary."""
    lines = [
        "Dataset validation report",
        f"  Accepted clips:   {report.clip_count}",
        f"  Rejected clips:   {report.rejected_count}",
        f"  Total duration:   {report.total_duration_seconds:.2f}s",
        f"  Average duration: {report.average_duration_seconds:.2f}s",
        f"  Target rate:      {report.target_sample_rate} Hz",
    ]
    if report.source_sample_rates:
        rates = ", ".join(
            f"{rate} Hz x{count}"
            for rate, count in sorted(report.source_sample_rates.items())
        )
        lines.append(f"  Source rates:     {rates}")
    reasons = report.rejections_by_reason()
    if reasons:
        lines.append("  Rejections:")
        for reason, count in sorted(reasons.items()):
            lines.append(f"    {reason}: {count}")
    if report.orphan_transcripts:
        lines.append(
            f"  Transcripts without audio: {', '.join(report.orphan_transcripts)}"
        )
    return "\n".join(lines)


__all__ = [
    "ClipRecord",
    "DatasetPrepError",
    "DatasetReport",
    "DEFAULT_MAX_DURATION_SECONDS",
    "DEFAULT_MIN_DURATION_SECONDS",
    "DEFAULT_NORMALIZE_PEAK",
    "DEFAULT_SILENCE_THRESHOLD",
    "MANIFEST_CSV_NAME",
    "MANIFEST_JSON_NAME",
    "REASON_EMPTY",
    "REASON_MISSING_TRANSCRIPT",
    "REASON_SILENT",
    "REASON_TOO_LONG",
    "REASON_TOO_SHORT",
    "REASON_UNREADABLE",
    "REASON_UNSUPPORTED",
    "RejectedClip",
    "SUPPORTED_SUFFIXES",
    "TARGET_SAMPLE_RATE",
    "discover_audio_files",
    "format_report",
    "load_transcripts",
    "normalize_amplitude",
    "prepare_dataset",
    "preprocess_samples",
    "read_manifest",
    "resample_linear",
    "strip_silence",
    "to_mono",
    "write_manifest",
]
