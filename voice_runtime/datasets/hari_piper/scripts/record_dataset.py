r"""Record a short, lossless, single-speaker pilot dataset for Piper.

Run this script with Grandpa's main environment, which owns the lightweight
``sounddevice`` and ``soundfile`` dependencies::

    D:\Grandpa\.venv\Scripts\python.exe record_dataset.py

The script never trains a model. It records PCM16 WAV candidates, validates
them before acceptance, writes exact transcript sidecars, and runs the existing
non-destructive preparation logic in a timestamped ``original_v2`` namespace.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import soundfile as sf

TARGET_SAMPLE_RATE = 22_050
CHANNELS = 1
MAX_RECORDING_SECONDS = 12.0
MIN_RECORDING_SECONDS = 2.0
MIN_SNR_DB = 12.0
MIN_PEAK_DBFS = -42.0
MAX_CLIPPED_FRACTION = 0.005
FRAME_SECONDS = 0.02
MAX_ACTIVITY_THRESHOLD_DBFS = -45.0
ACTIVITY_MARGIN_ABOVE_NOISE_DB = 6.0
EDGE_SILENCE_PADDING_SECONDS = 0.15
MIN_ACTIVE_FRAME_FRACTION = 0.05
VIRTUAL_INPUT_HINTS = (
    "sound mapper",
    "primary sound capture",
    "stereo mix",
    "pc speaker",
    "virtual",
)

DATASET_ROOT = Path(__file__).resolve().parents[1]
RAW_OUTPUT = DATASET_ROOT / "raw" / "original_v2"
VOICE_RUNTIME_PYTHON = DATASET_ROOT.parents[1] / ".venv" / "Scripts" / "python.exe"
PROGRESS_PATH = RAW_OUTPUT / ".recording_progress.json"


@dataclass(frozen=True)
class RecordingItem:
    """One exact utterance and its training labels."""

    number: int
    slug: str
    text: str
    language: str
    style: str

    @property
    def stem(self) -> str:
        return f"{self.number:03d}_{self.slug}"


@dataclass(frozen=True)
class AudioMetrics:
    """Objective measurements for one candidate PCM WAV."""

    format: str
    subtype: str
    sample_rate: int
    channels: int
    duration_seconds: float
    peak_dbfs: float
    clipped_fraction: float
    estimated_snr_db: float
    silent_frame_fraction: float
    activity_threshold_dbfs: float
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class DatasetProgress:
    """Filesystem-derived completion state for the recording set."""

    completed: tuple[RecordingItem, ...]
    remaining: tuple[RecordingItem, ...]
    invalid: tuple[tuple[RecordingItem, str], ...]

    @property
    def next_item(self) -> RecordingItem | None:
        return self.remaining[0] if self.remaining else None


@dataclass(frozen=True)
class SessionState:
    """Non-authoritative conveniences preserved between recording sessions."""

    skipped: tuple[str, ...] = ()
    last_attempted: str | None = None
    checkpoints_shown: tuple[int, ...] = ()


PROMPTS: tuple[RecordingItem, ...] = (
    RecordingItem(1, "english_intro", "Hello, my name is Hari Hara Sudhan, and I enjoy building practical technology projects.", "en", "neutral"),
    RecordingItem(2, "english_learning", "I learn new ideas step by step and test them with small working examples.", "en", "neutral"),
    RecordingItem(3, "english_ai", "Artificial intelligence and automation can help people solve useful real-world problems.", "en", "neutral"),
    RecordingItem(4, "english_practice", "I stay curious, keep practicing, and improve my work through careful testing.", "en", "neutral"),
    RecordingItem(5, "tanglish_start", "Vanakkam, naan Hari. Innaiku namma Grandpa project la konjam work panna porom.", "ta-Latn", "tanglish"),
    RecordingItem(6, "tanglish_status", "First current system status check pannalam, apram pending tasks enna irukku nu paakkalam.", "ta-Latn", "tanglish"),
    RecordingItem(7, "tanglish_debug", "Problem vandha immediate-ah change pannaama, first root cause identify pannuvom.", "ta-Latn", "tanglish"),
    RecordingItem(8, "tanglish_verify", "Correct solution kidaichadhukku apram test panni result verify pannalam.", "ta-Latn", "tanglish"),
    RecordingItem(9, "tamil_learning", "Namma oru pudhu vishayam kathukkumbodhu ellathaiyum ore nerathula purinjikanum nu avasiyam illa.", "ta-Latn", "tamil-heavy"),
    RecordingItem(10, "tamil_practice", "Konjam konjam practice panni, nammale oru project build panna aarambichaa concepts easy-ah puriyum.", "ta-Latn", "tamil-heavy"),
    RecordingItem(11, "tamil_failure", "Edhavadhu thappu nadandha adha failure-ah paakkaama, enna problem nu kandupidikkanum.", "ta-Latn", "tamil-heavy"),
    RecordingItem(12, "tamil_progress", "Daily consistent-ah practice panni improve aaguradhu dhaan namakku romba mukkiyam.", "ta-Latn", "tamil-heavy"),
    RecordingItem(13, "technical_stack", "My development environment uses Python, FastAPI, Docker, Git, and GitHub.", "en", "technical"),
    RecordingItem(14, "technical_data", "The application uses an API, a database, SQLite, PostgreSQL, and Ollama.", "en", "technical"),
    RecordingItem(15, "technical_architecture", "Grandpa connects local artificial intelligence components through a modular architecture.", "en", "technical"),
    RecordingItem(16, "technical_debug", "I check logs, configuration, dependencies, memory usage, and running processes before changing code.", "en", "technical"),
    RecordingItem(17, "assistant_ready", "Hari, Grandpa is ready and the local services are running normally.", "en", "assistant"),
    RecordingItem(18, "assistant_help", "I can help you check files, review project status, and understand technical problems.", "en", "assistant"),
    RecordingItem(19, "assistant_failure", "If something fails, I will identify the affected component and report the problem clearly.", "en", "assistant"),
    RecordingItem(20, "assistant_continue", "Once the issue is resolved, we can continue from where we stopped.", "en", "assistant"),
    RecordingItem(21, "command_received", "Command received. Grandpa is processing the requested operation now.", "en", "command"),
    RecordingItem(22, "command_file", "File operation completed successfully, and the requested directory is available.", "en", "command"),
    RecordingItem(23, "command_backup", "Configuration validation and local backup completed successfully without any errors.", "en", "command"),
    RecordingItem(24, "command_confirm", "Please confirm before Grandpa performs any destructive system operation.", "en", "command"),
    RecordingItem(25, "question_work", "Hari, innaiku namma enna important work panna porom?", "ta-Latn", "question"),
    RecordingItem(26, "question_project", "Grandpa project continue pannalama, illa vera task first complete pannalama?", "ta-Latn", "question"),
    RecordingItem(27, "question_services", "Ollama server running-ah irukka? Voice service ready-ah irukka?", "ta-Latn", "question"),
    RecordingItem(28, "question_roadmap", "Recent changes ellam test panniyacha? Next milestone roadmap-la paakkalama?", "ta-Latn", "question"),
    RecordingItem(29, "numbers_date", "Today is August eleventh, in the year twenty twenty-six.", "en", "numbers"),
    RecordingItem(30, "numbers_time", "The current time is seven thirty, and the second check happens at nine fifteen.", "en", "numbers"),
    RecordingItem(31, "numbers_count", "There are ten files, twenty-five records, and one hundred and fifty entries.", "en", "numbers"),
    RecordingItem(32, "numbers_ports", "The services use port eight seven six five and port eleven four three four.", "en", "numbers"),
    RecordingItem(33, "network_status", "The local network connection is stable, responsive, and fully operational.", "en", "network"),
    RecordingItem(34, "network_address", "Check the IP address, default gateway, DNS server, and active network adapter.", "en", "network"),
    RecordingItem(35, "network_port", "Verify whether the required TCP port is listening before changing the configuration.", "en", "network"),
    RecordingItem(36, "network_router", "The router connects devices, while DNS converts domain names into network addresses.", "en", "network"),
    RecordingItem(37, "narration_change", "Technology changes quickly, so practical learning is very important.", "en", "narration"),
    RecordingItem(38, "narration_build", "I understand the basic concept first and then build a small working project.", "en", "narration"),
    RecordingItem(39, "narration_improve", "I test different situations, find problems, and improve the design over time.", "en", "narration"),
    RecordingItem(40, "narration_reason", "The important thing is to keep building and understand why something works.", "en", "narration"),
)


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _expected_transcript(path: Path, expected: str) -> bool:
    """Accept only the exact prompt plus the recorder's optional final newline."""

    try:
        actual = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return False
    return actual in {expected, expected + "\n", expected + "\r\n"}


def validate_recording_pair(item: RecordingItem) -> tuple[bool, str]:
    """Validate one accepted WAV/TXT pair from content, not filenames alone."""

    wav_path = RAW_OUTPUT / f"{item.stem}.wav"
    txt_path = RAW_OUTPUT / f"{item.stem}.txt"
    if not wav_path.is_file():
        return False, "WAV is missing"
    if not txt_path.is_file():
        return False, "transcript is missing"
    if not _expected_transcript(txt_path, item.text):
        return False, "transcript does not exactly match the expected prompt"
    metrics = inspect_pcm_wav(wav_path)
    if not metrics.passed:
        return False, "; ".join(metrics.issues)
    return True, ""


def scan_dataset_progress() -> DatasetProgress:
    """Calculate progress from validated filesystem artifacts."""

    completed: list[RecordingItem] = []
    remaining: list[RecordingItem] = []
    invalid: list[tuple[RecordingItem, str]] = []
    for item in PROMPTS:
        valid, reason = validate_recording_pair(item)
        if valid:
            completed.append(item)
            continue
        remaining.append(item)
        wav_path = RAW_OUTPUT / f"{item.stem}.wav"
        txt_path = RAW_OUTPUT / f"{item.stem}.txt"
        if wav_path.exists() or txt_path.exists():
            invalid.append((item, reason))
    return DatasetProgress(tuple(completed), tuple(remaining), tuple(invalid))


def load_session_state() -> SessionState:
    """Load optional UX state; invalid state never affects completion."""

    try:
        payload = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        return SessionState(
            skipped=tuple(str(item) for item in payload.get("skipped", [])),
            last_attempted=(
                str(payload["last_attempted"])
                if payload.get("last_attempted")
                else None
            ),
            checkpoints_shown=tuple(
                int(item) for item in payload.get("checkpoints_shown", [])
            ),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return SessionState()


def save_session_state(state: SessionState) -> None:
    """Atomically save non-sensitive session conveniences."""

    RAW_OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed_clips": [item.stem for item in scan_dataset_progress().completed],
        "skipped": list(dict.fromkeys(state.skipped)),
        "last_attempted": state.last_attempted,
        "checkpoints_shown": sorted(set(state.checkpoints_shown)),
        "session_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    temporary = PROGRESS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(PROGRESS_PATH)


def _print_progress(progress: DatasetProgress, mode: str) -> None:
    print("\nHari Piper Dataset Recorder")
    print(f"Completed : {len(progress.completed)} / {len(PROMPTS)}")
    print(f"Remaining : {len(progress.remaining)}")
    print(f"Current   : {progress.next_item.stem if progress.next_item else 'Complete'}")
    print(f"Session   : {mode.title()}")


def inspect_pcm_wav(path: Path) -> AudioMetrics:
    """Verify the real container/codec and measure recording quality."""

    issues: list[str] = []
    try:
        header = path.read_bytes()[:12]
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError("file does not have a RIFF/WAVE header")
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                issues.append("WAV is compressed")
            if wav_file.getsampwidth() != 2:
                issues.append("WAV is not 16-bit PCM")
            wave_channels = wav_file.getnchannels()
            wave_rate = wav_file.getframerate()
        info = sf.info(path)
        if info.format != "WAV" or info.subtype != "PCM_16":
            issues.append("file is not genuine PCM16 WAV")
        audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    except Exception as exc:
        return AudioMetrics(
            "unreadable",
            "unknown",
            0,
            0,
            0.0,
            -240.0,
            1.0,
            0.0,
            1.0,
            MAX_ACTIVITY_THRESHOLD_DBFS,
            (f"audio validation failed: {type(exc).__name__}: {exc}",),
        )

    channels = int(audio.shape[1])
    mono = np.mean(audio, axis=1, dtype=np.float32)
    duration = len(mono) / sample_rate if sample_rate else 0.0
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    clipped = float(np.mean(np.abs(mono) >= 0.999)) if mono.size else 1.0
    snr, silent_fraction, activity_threshold = _signal_metrics(mono, sample_rate)

    if wave_channels != channels or wave_rate != sample_rate:
        issues.append("WAV header metadata is inconsistent")
    if channels != CHANNELS:
        issues.append(f"expected mono audio, found {channels} channels")
    if duration < MIN_RECORDING_SECONDS:
        issues.append(f"recording is shorter than {MIN_RECORDING_SECONDS:.0f} seconds")
    if duration > MAX_RECORDING_SECONDS + 0.25:
        issues.append(f"recording exceeds {MAX_RECORDING_SECONDS:.0f} seconds")
    if clipped > MAX_CLIPPED_FRACTION:
        issues.append("recording contains excessive clipping")
    if _dbfs(peak) < MIN_PEAK_DBFS:
        issues.append("recording level is too quiet")
    if snr < MIN_SNR_DB:
        issues.append(f"estimated SNR is below {MIN_SNR_DB:.0f} dB")
    if 1.0 - silent_fraction < MIN_ACTIVE_FRAME_FRACTION:
        issues.append("recording contains almost no detected speech")

    return AudioMetrics(
        info.format,
        info.subtype,
        int(sample_rate),
        channels,
        round(duration, 3),
        round(_dbfs(peak), 2),
        round(clipped, 8),
        round(snr, 2),
        round(silent_fraction, 4),
        round(activity_threshold, 2),
        tuple(dict.fromkeys(issues)),
    )


def _frame_rms(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if not audio.size or sample_rate <= 0:
        return np.array([], dtype=np.float32)
    frame_size = max(1, int(sample_rate * FRAME_SECONDS))
    frame_count = len(audio) // frame_size
    if frame_count == 0:
        return np.array([], dtype=np.float32)
    frames = audio[: frame_count * frame_size].reshape(frame_count, frame_size)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def _activity_threshold_dbfs(rms: np.ndarray) -> float:
    if not rms.size:
        return MAX_ACTIVITY_THRESHOLD_DBFS
    noise = float(np.percentile(rms, 20))
    return min(
        MAX_ACTIVITY_THRESHOLD_DBFS,
        _dbfs(noise) + ACTIVITY_MARGIN_ABOVE_NOISE_DB,
    )


def _signal_metrics(audio: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    rms = _frame_rms(audio, sample_rate)
    if not rms.size:
        return 0.0, 1.0, MAX_ACTIVITY_THRESHOLD_DBFS
    noise = float(np.percentile(rms, 20))
    speech = float(np.percentile(rms, 80))
    snr = _dbfs(speech) - _dbfs(noise)
    threshold_dbfs = _activity_threshold_dbfs(rms)
    threshold = 10 ** (threshold_dbfs / 20.0)
    return snr, float(np.mean(rms < threshold)), threshold_dbfs


def trim_edge_silence(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float, float, float]:
    """Trim only leading/trailing low-energy audio, preserving internal pauses."""

    samples = np.asarray(audio)
    if not samples.size or sample_rate <= 0:
        return samples, 0.0, 0.0, MAX_ACTIVITY_THRESHOLD_DBFS
    mono = samples[:, 0] if samples.ndim == 2 else samples
    if np.issubdtype(mono.dtype, np.integer):
        analysis = mono.astype(np.float32) / 32768.0
    else:
        analysis = mono.astype(np.float32, copy=False)
    rms = _frame_rms(analysis, sample_rate)
    if not rms.size:
        return samples, 0.0, 0.0, MAX_ACTIVITY_THRESHOLD_DBFS
    threshold_dbfs = _activity_threshold_dbfs(rms)
    active = np.flatnonzero(rms >= 10 ** (threshold_dbfs / 20.0))
    if not active.size:
        return samples, 0.0, 0.0, threshold_dbfs
    frame_size = max(1, int(sample_rate * FRAME_SECONDS))
    padding = int(sample_rate * EDGE_SILENCE_PADDING_SECONDS)
    start = max(0, int(active[0]) * frame_size - padding)
    end = min(len(samples), (int(active[-1]) + 1) * frame_size + padding)
    leading = start / sample_rate
    trailing = (len(samples) - end) / sample_rate
    return samples[start:end], leading, trailing, threshold_dbfs


def _import_sounddevice() -> Any:
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "sounddevice is unavailable. Run this utility with "
            "D:\\Grandpa\\.venv\\Scripts\\python.exe."
        ) from exc
    return sd


def list_input_devices(sd: Any) -> list[tuple[int, str, int, int]]:
    devices: list[tuple[int, str, int, int]] = []
    for index, raw in enumerate(sd.query_devices()):
        channels = int(raw.get("max_input_channels", 0))
        if channels > 0:
            devices.append(
                (
                    index,
                    str(raw.get("name", f"Input {index}")),
                    channels,
                    int(float(raw.get("default_samplerate", TARGET_SAMPLE_RATE))),
                )
            )
    return devices


def select_input_device(
    sd: Any,
    *,
    requested_index: int | None = None,
    requested_name: str | None = None,
) -> tuple[int, dict[str, Any]]:
    raw_devices = list(sd.query_devices())
    inputs = list_input_devices(sd)
    if requested_index is not None:
        match = next((item for item in inputs if item[0] == requested_index), None)
        if match is None:
            raise ValueError(f"Device {requested_index} is not a usable input device.")
        return requested_index, dict(raw_devices[requested_index])
    if requested_name:
        normalized = requested_name.casefold().strip()
        matches = [item for item in inputs if normalized in item[1].casefold()]
        if len(matches) != 1:
            raise ValueError(
                f"Microphone name '{requested_name}' matched {len(matches)} devices. "
                "Use --list-devices and --device."
            )
        index = matches[0][0]
        return index, dict(raw_devices[index])
    try:
        default = sd.default.device
        default_index = int(default[0] if isinstance(default, (tuple, list)) else default)
    except (AttributeError, TypeError, ValueError, OverflowError):
        default_index = -1
    default_input = next((item for item in inputs if item[0] == default_index), None)
    if default_input is not None and not _is_virtual_input(default_input[1]):
        return default_index, dict(raw_devices[default_index])
    if not inputs:
        raise ValueError("No usable input devices were found.")
    physical_inputs = [item for item in inputs if not _is_virtual_input(item[1])]
    preferred = next(
        (
            item
            for hint in ("microphone array", "microphone", "headset")
            for item in physical_inputs
            if hint in item[1].casefold()
        ),
        None,
    )
    index = (preferred or physical_inputs[0] if physical_inputs else inputs[0])[0]
    return index, dict(raw_devices[index])


def _is_virtual_input(name: str) -> bool:
    normalized = name.casefold()
    return any(hint in normalized for hint in VIRTUAL_INPUT_HINTS)


def select_sample_rate(sd: Any, device_index: int, device: dict[str, Any]) -> int:
    """Prefer 22.05 kHz, otherwise use the device's native lossless rate."""

    try:
        sd.check_input_settings(
            device=device_index,
            channels=CHANNELS,
            dtype="int16",
            samplerate=TARGET_SAMPLE_RATE,
        )
        return TARGET_SAMPLE_RATE
    except Exception:
        native_rate = int(float(device.get("default_samplerate", 0)))
        if native_rate <= 0:
            raise ValueError("The selected microphone has no valid native sample rate.")
        sd.check_input_settings(
            device=device_index,
            channels=CHANNELS,
            dtype="int16",
            samplerate=native_rate,
        )
        return native_rate


def countdown(seconds: int = 3) -> None:
    for remaining in range(seconds, 0, -1):
        print(f"Recording in {remaining}...", flush=True)
        time.sleep(1)
    print("Recording. Read the text, then press Enter to stop.", flush=True)


def _enter_pressed() -> bool:
    if os.name == "nt":
        import msvcrt

        if not msvcrt.kbhit():
            return False
        key = msvcrt.getwch()
        return key in {"\r", "\n"}
    if not sys.stdin.isatty():
        return False
    import select

    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return False
    sys.stdin.readline()
    return True


def capture_audio(
    sd: Any,
    *,
    device_index: int,
    sample_rate: int,
    stop_check: Callable[[], bool] = _enter_pressed,
) -> np.ndarray:
    chunks: list[np.ndarray] = []
    stream_errors: list[str] = []

    def callback(indata, _frames, _time_info, status) -> None:
        if status:
            stream_errors.append(str(status))
        chunks.append(indata.copy())

    deadline = time.monotonic() + MAX_RECORDING_SECONDS
    with sd.InputStream(
        samplerate=sample_rate,
        channels=CHANNELS,
        dtype="int16",
        device=device_index,
        callback=callback,
    ):
        while time.monotonic() < deadline:
            if stop_check():
                break
            time.sleep(0.03)
    if stream_errors:
        raise RuntimeError(f"Microphone stream error: {stream_errors[-1]}")
    if not chunks:
        raise RuntimeError("The microphone returned no audio frames.")
    return np.concatenate(chunks, axis=0)


def write_pcm_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write only a RIFF PCM16 WAV, never an inferred compressed format."""

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(
        path,
        np.asarray(audio, dtype=np.int16),
        sample_rate,
        format="WAV",
        subtype="PCM_16",
    )


def _temporary_wav(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".candidate_", suffix=".wav", dir=directory)
    os.close(handle)
    return Path(name)


def _print_metrics(metrics: AudioMetrics) -> None:
    print(
        f"Format: {metrics.format}/{metrics.subtype} | "
        f"{metrics.sample_rate} Hz | {metrics.channels} channel | "
        f"{metrics.duration_seconds:.2f}s"
    )
    print(
        f"Peak: {metrics.peak_dbfs:.2f} dBFS | "
        f"SNR: {metrics.estimated_snr_db:.2f} dB | "
        f"Clipped: {metrics.clipped_fraction * 100:.4f}%"
    )
    print(
        f"Detected speech: {(1.0 - metrics.silent_frame_fraction) * 100:.1f}% | "
        f"Low-energy/pause: {metrics.silent_frame_fraction * 100:.1f}% | "
        f"Activity threshold: {metrics.activity_threshold_dbfs:.1f} dBFS"
    )
    for issue in metrics.issues:
        print(f"  FAIL: {issue}")


def replay(sd: Any, path: Path) -> None:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    sd.play(audio, sample_rate)
    sd.wait()


def _trim_and_report(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    trimmed, leading, trailing, threshold = trim_edge_silence(audio, sample_rate)
    if leading > 0 or trailing > 0:
        print(
            f"Trimmed edge silence: {leading:.2f}s leading, {trailing:.2f}s trailing "
            f"(activity threshold {threshold:.1f} dBFS)."
        )
    return trimmed


def _write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text.strip() + "\n", encoding="utf-8")
    temporary.replace(path)


def prompt_choice(
    prompt: str,
    choices: set[str],
    *,
    default: str | None = None,
    input_fn: Callable[[str], str] = input,
) -> str:
    """Read a menu choice without treating empty input as an exit."""

    while True:
        choice = input_fn(prompt).strip().lower()
        if not choice and default is not None:
            return default
        if choice in choices:
            return choice
        print("Please choose " + ", ".join(sorted(choice.upper() for choice in choices)) + ".")


def choose_recording_mode(
    input_fn: Callable[[str], str] = input,
) -> str:
    print("\nRecording mode:\n")
    print("1. Normal")
    print("   Listen/accept each clip manually\n")
    print("2. Fast")
    print("   Automatically accept technically valid clips")
    print("   Only stop when validation fails\n")
    return "fast" if prompt_choice("Select mode [1]: ", {"1", "2"}, default="1", input_fn=input_fn) == "2" else "normal"


def record_mic_test(
    sd: Any,
    device_index: int,
    sample_rate: int,
    *,
    replace_existing: bool = False,
) -> AudioMetrics:
    output = RAW_OUTPUT / "000_mic_test.wav"
    if output.exists() and not replace_existing:
        raise RuntimeError("Microphone test already exists and replacement was not requested.")
    print("\nMicrophone test: say, 'Hari microphone test for Grandpa.'")
    input("Press Enter when ready...")
    countdown()
    candidate = _temporary_wav(RAW_OUTPUT)
    try:
        write_pcm_wav(
            candidate,
            _trim_and_report(
                capture_audio(sd, device_index=device_index, sample_rate=sample_rate),
                sample_rate,
            ),
            sample_rate,
        )
        metrics = inspect_pcm_wav(candidate)
        _print_metrics(metrics)
        if not metrics.passed:
            raise RuntimeError("Microphone test failed validation; dataset recording stopped.")
        candidate.replace(output)
        print(f"Microphone test passed: {output}")
        return metrics
    finally:
        candidate.unlink(missing_ok=True)


def record_item(
    sd: Any,
    item: RecordingItem,
    *,
    device_index: int,
    sample_rate: int,
    mode: str = "normal",
    input_fn: Callable[[str], str] = input,
) -> str:
    wav_path = RAW_OUTPUT / f"{item.stem}.wav"
    txt_path = RAW_OUTPUT / f"{item.stem}.txt"
    existing_valid, existing_reason = validate_recording_pair(item)
    if existing_valid:
        return "accepted"
    if wav_path.exists() or txt_path.exists():
        print(f"Existing incomplete/invalid pair: {existing_reason}")

    while True:
        print(f"\n[{item.number:02d}/{len(PROMPTS)}] {item.stem}")
        print("Read exactly:")
        print(item.text)
        input_fn("Press Enter when ready...")
        countdown()
        candidate = _temporary_wav(RAW_OUTPUT)
        try:
            write_pcm_wav(
                candidate,
                _trim_and_report(
                    capture_audio(
                        sd,
                        device_index=device_index,
                        sample_rate=sample_rate,
                    ),
                    sample_rate,
                ),
                sample_rate,
            )
            metrics = inspect_pcm_wav(candidate)
            _print_metrics(metrics)
            if mode == "fast" and metrics.passed:
                candidate.replace(wav_path)
                _write_text_atomic(txt_path, item.text)
                print(f"Accepted {wav_path.name}")
                print(f"Duration: {metrics.duration_seconds:.2f}s")
                return "accepted"
            while True:
                allowed = "[P] Play, [R] Re-record, [S] Skip, [Q] Save progress and quit"
                if metrics.passed:
                    allowed = "[A] Accept, " + allowed
                choices = {"p", "r", "s", "q"}
                if metrics.passed:
                    choices.add("a")
                choice = prompt_choice(f"{allowed}: ", choices, input_fn=input_fn)
                if choice == "p":
                    replay(sd, candidate)
                    continue
                break
            if choice == "s":
                return "skipped"
            if choice == "q":
                return "quit"
            if choice == "a" and metrics.passed:
                candidate.replace(wav_path)
                _write_text_atomic(txt_path, item.text)
                print(f"Accepted {wav_path.name}")
                print(f"Duration: {metrics.duration_seconds:.2f}s")
                return "accepted"
            print("Re-recording clip.")
        finally:
            candidate.unlink(missing_ok=True)


def _load_preparer() -> Any:
    path = Path(__file__).with_name("prepare_dataset.py")
    spec = importlib.util.spec_from_file_location("hari_piper_prepare_dataset", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the existing dataset preparer.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _recorded_rows() -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    issues: list[str] = []
    for item in PROMPTS:
        wav_path = RAW_OUTPUT / f"{item.stem}.wav"
        txt_path = RAW_OUTPUT / f"{item.stem}.txt"
        if not wav_path.exists() and not txt_path.exists():
            continue
        if not wav_path.is_file() or not txt_path.is_file():
            issues.append(f"{item.stem}: WAV/TXT pair is incomplete")
            continue
        if not _expected_transcript(txt_path, item.text):
            issues.append(f"{item.stem}: transcript differs from the recording prompt")
            continue
        transcript = item.text
        metrics = inspect_pcm_wav(wav_path)
        if not metrics.passed:
            issues.append(f"{item.stem}: {'; '.join(metrics.issues)}")
            continue
        rows.append(
            {
                "clip_id": item.stem,
                "filename": wav_path.name,
                "transcript": transcript,
                "language": item.language,
                "style": item.style,
                "source": "original",
            }
        )
    return rows, issues


def run_preparation() -> tuple[Path, list[Any], list[str]]:
    """Run the existing preparer in a fresh V2 output namespace."""

    rows, preflight_issues = _recorded_rows()
    if not rows:
        raise RuntimeError("No validated original_v2 recordings are available.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = DATASET_ROOT / "reports" / "original_v2" / run_id
    metadata_root = DATASET_ROOT / "metadata" / "original_v2" / run_id
    roots = {
        "raw": RAW_OUTPUT,
        "processed": DATASET_ROOT / "processed" / "original_v2" / run_id,
        "wavs": DATASET_ROOT / "wavs" / "original_v2" / run_id,
        "metadata": metadata_root,
        "reports": run_root,
    }
    for name, path in roots.items():
        if name != "raw":
            path.mkdir(parents=True, exist_ok=False)

    manifest_path = metadata_root / "source_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("clip_id", "filename", "transcript", "language", "style", "source"),
        )
        writer.writeheader()
        writer.writerows(rows)

    preparer = _load_preparer()
    records = [preparer._process_row(row, roots) for row in rows]
    preparer._write_outputs(records, roots)
    _print_preparation_summary(records, roots, manifest_path, preflight_issues)
    return manifest_path, records, preflight_issues


def launch_preparation() -> None:
    """Run SciPy-backed preparation in the existing isolated voice runtime."""

    if not VOICE_RUNTIME_PYTHON.is_file():
        raise RuntimeError(
            f"Voice runtime Python was not found: {VOICE_RUNTIME_PYTHON}"
        )
    completed = subprocess.run(
        [str(VOICE_RUNTIME_PYTHON), str(Path(__file__).resolve()), "--prepare-only"],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Dataset preparation failed with exit code {completed.returncode}."
        )


def _print_preparation_summary(
    records: Sequence[Any],
    roots: dict[str, Path],
    manifest_path: Path,
    preflight_issues: Sequence[str],
) -> None:
    accepted = [record for record in records if record.quality_status == "accepted"]
    rejected = [record for record in records if record.quality_status == "rejected"]
    review = [record for record in records if record.quality_status == "review"]
    durations = [float(record.processed_duration_seconds or 0.0) for record in accepted]
    print("\nPreparation complete")
    print(f"Recorded/validated: {len(records)}")
    print(f"Accepted: {len(accepted)} | Review: {len(review)} | Rejected: {len(rejected)}")
    print(f"Accepted duration: {sum(durations):.2f}s")
    print(f"Average duration: {(sum(durations) / len(durations)) if durations else 0.0:.2f}s")
    print("Encoding: WAV/PCM_16, mono; prepared at 22050 Hz")
    print(f"Transcript count: {len(records)}")
    print(f"Source manifest: {manifest_path}")
    print(f"Piper metadata: {roots['metadata'] / 'metadata.csv'}")
    print(f"Extended manifest: {roots['metadata'] / 'extended_manifest.csv'}")
    print(f"Validation report: {roots['reports'] / 'validation_report.json'}")
    print(f"Prepared WAVs: {roots['wavs']}")
    for issue in preflight_issues:
        print(f"Skipped before preparation: {issue}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=int, help="Exact sounddevice input index")
    parser.add_argument("--device-name", help="Unique part of an input-device name")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--mic-test-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--start-at", type=int, choices=range(1, len(PROMPTS) + 1), metavar="1-40")
    return parser


def ensure_microphone_test(
    sd: Any,
    device_index: int,
    sample_rate: int,
    *,
    input_fn: Callable[[str], str] = input,
) -> AudioMetrics:
    """Reuse a valid preflight by default or explicitly record a replacement."""

    output = RAW_OUTPUT / "000_mic_test.wav"
    if output.is_file():
        existing = inspect_pcm_wav(output)
        if existing.passed:
            print("Microphone test: PASS (existing)")
            choice = prompt_choice(
                "[R] Run microphone test again / [C] Continue with existing test [C]: ",
                {"r", "c"},
                default="c",
                input_fn=input_fn,
            )
            if choice == "c":
                return existing
        else:
            print("Microphone test: FAIL (existing)")
            for issue in existing.issues:
                print(f"  {issue}")
    return record_mic_test(
        sd,
        device_index,
        sample_rate,
        replace_existing=output.exists(),
    )


def checkpoint_decision(
    completed_count: int,
    state: SessionState,
    *,
    input_fn: Callable[[str], str] = input,
) -> tuple[bool, SessionState]:
    """Pause at pilot milestones once, defaulting to a safe saved exit."""

    if completed_count not in {10, 20, 30}:
        return True, state
    if completed_count in state.checkpoints_shown:
        return True, state
    print(f"\nPilot checkpoint reached: {completed_count} clips completed.")
    choice = prompt_choice(
        "[C] Continue recording / [Q] Save and quit [Q]: ",
        {"c", "q"},
        default="q",
        input_fn=input_fn,
    )
    updated = SessionState(
        skipped=state.skipped,
        last_attempted=state.last_attempted,
        checkpoints_shown=(*state.checkpoints_shown, completed_count),
    )
    return choice == "c", updated


def _updated_session_state(
    state: SessionState,
    *,
    last_attempted: str | None = None,
    skipped: str | None = None,
) -> SessionState:
    skipped_items = state.skipped + ((skipped,) if skipped else ())
    return SessionState(
        skipped=tuple(dict.fromkeys(skipped_items)),
        last_attempted=(
            last_attempted if last_attempted is not None else state.last_attempted
        ),
        checkpoints_shown=state.checkpoints_shown,
    )


def maybe_prepare_complete_dataset(
    *,
    input_fn: Callable[[str], str] = input,
) -> bool:
    """Offer preparation only after all filesystem-validated clips exist."""

    progress = scan_dataset_progress()
    if len(progress.completed) != len(PROMPTS):
        return False
    print("\nPilot checkpoint reached: 40 clips completed.")
    choice = prompt_choice(
        "Run dataset validation/preparation now? [y/N]: ",
        {"y", "n"},
        default="n",
        input_fn=input_fn,
    )
    if choice == "y":
        launch_preparation()
        print("Dataset validation complete. Piper training was not started.")
        return True
    print("Dataset preparation was not started.")
    return False


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.prepare_only:
        run_preparation()
        return 0

    progress = scan_dataset_progress()
    print(f"Completed: {len(progress.completed)} / {len(PROMPTS)}")
    print(f"Remaining: {len(progress.remaining)} / {len(PROMPTS)}")
    print(f"Next clip: {progress.next_item.stem if progress.next_item else 'Complete'}")
    for item, reason in progress.invalid:
        print(f"Needs recording: {item.stem} ({reason})")
    if not progress.remaining:
        maybe_prepare_complete_dataset()
        return 0

    sd = _import_sounddevice()
    if args.list_devices:
        for index, name, channels, sample_rate in list_input_devices(sd):
            print(f"{index}: {name} ({channels} input channel(s), native {sample_rate} Hz)")
        return 0

    device_index, device = select_input_device(
        sd,
        requested_index=args.device,
        requested_name=args.device_name,
    )
    sample_rate = select_sample_rate(sd, device_index, device)
    print(f"Microphone: {device.get('name', device_index)} (device {device_index})")
    print(f"Recording format: mono PCM16 WAV at {sample_rate} Hz")
    ensure_microphone_test(sd, device_index, sample_rate)
    if args.mic_test_only:
        return 0

    mode = choose_recording_mode()
    state = load_session_state()
    should_continue, state = checkpoint_decision(len(progress.completed), state)
    save_session_state(state)
    if not should_continue:
        print("Progress saved. Recording session stopped at the checkpoint.")
        return 0
    start_at = args.start_at or 1
    for item in progress.remaining:
        if item.number < start_at:
            continue
        progress = scan_dataset_progress()
        if item in progress.completed:
            continue
        _print_progress(progress, mode)
        state = _updated_session_state(state, last_attempted=item.stem)
        save_session_state(state)
        result = record_item(
            sd,
            item,
            device_index=device_index,
            sample_rate=sample_rate,
            mode=mode,
        )
        if result == "quit":
            save_session_state(state)
            print("Progress saved. Recording session stopped.")
            return 0
        if result == "skipped":
            state = _updated_session_state(state, skipped=item.stem)
            save_session_state(state)
            continue
        progress = scan_dataset_progress()
        save_session_state(state)
        print(f"Progress: {len(progress.completed)} / {len(PROMPTS)}")
        should_continue, state = checkpoint_decision(len(progress.completed), state)
        save_session_state(state)
        if not should_continue:
            print("Progress saved. Recording session stopped at the checkpoint.")
            return 0

    progress = scan_dataset_progress()
    if progress.remaining:
        print(
            f"Recording session complete for now. "
            f"{len(progress.remaining)} clip(s) remain."
        )
        return 0
    maybe_prepare_complete_dataset()
    return 0


def cli(argv: Sequence[str] | None = None) -> int:
    """Run the recorder with graceful interruption and stable exit codes."""

    try:
        return main(argv)
    except KeyboardInterrupt:
        print("\nRecording stopped. Accepted clips were preserved.")
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
