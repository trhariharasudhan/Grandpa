"""B1: "Hey Grandpa" from the microphone, with openWakeWord.

``wake_word.py`` finds a wake phrase inside a transcript, which means the
microphone was already open and Whisper already ran. This module is the step
before that: a small local model (openWakeWord, ONNX on the CPU) listens to
80 ms frames and says "that was the wake phrase" without any speech-to-text.

How a detection is decided, in order:

* the model scores every 80 ms frame between 0 and 1;
* ``patience`` frames in a row must reach ``threshold`` (one loud frame is not
  enough -- this is what keeps a cough or a door from waking him);
* after a detection there is a ``cooldown`` during which nothing fires, and the
  model's buffers are reset so the same "Hey Grandpa" cannot fire twice;
* optionally openWakeWord's own Silero VAD drops frames that are not speech.

Nothing here writes audio anywhere. Frames live in memory for one ``predict``
call and are dropped.

Which model: openWakeWord has no "Hey Grandpa" model of its own, so one is
trained once with openWakeWord's Colab notebook (see
``docs/user-guide/wake-word.md``) and placed at ``~/.Grandpa/wakeword/hey_grandpa.onnx``.
Until then a built-in model name such as ``hey_mycroft`` can be passed to check
that the microphone path works.
"""

from __future__ import annotations

import math
import os
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from grandpa.core.config import DEFAULT_CONFIG_DIR

SAMPLE_RATE = 16_000
#: openWakeWord works on 80 ms frames (1280 samples at 16 kHz).
FRAME_SAMPLES = 1280
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE

DEFAULT_MODEL_NAME = "hey_grandpa"
DEFAULT_MODEL_DIR = DEFAULT_CONFIG_DIR / "wakeword"
#: Repo-local spot, for a model Captain decides to keep next to the code.
REPO_MODEL_DIR = Path(__file__).resolve().parents[3] / "assets" / "wakeword"

DEFAULT_THRESHOLD = 0.5
DEFAULT_PATIENCE = 2
DEFAULT_COOLDOWN_SECONDS = 2.0
DEFAULT_VAD_THRESHOLD = 0.3

#: The B1 target: fewer than one false trigger per hour of ordinary sound.
FALSE_TRIGGER_BUDGET_PER_HOUR = 1.0

SETUP_HINT = (
    "No 'Hey Grandpa' model yet. Train one once (about an hour on a free Colab "
    "GPU, steps in docs/user-guide/wake-word.md) and save it as "
    f"{DEFAULT_MODEL_DIR / 'hey_grandpa.onnx'}. To check the microphone path "
    "now, use a built-in model: --model hey_mycroft"
)


class WakeEngineUnavailable(RuntimeError):
    """openWakeWord, its feature models, or the wake model is missing."""


@dataclass(frozen=True)
class WakeEngineConfig:
    """How the audio wake word decides. Env vars override the defaults."""

    model: str = ""
    threshold: float = DEFAULT_THRESHOLD
    patience: int = DEFAULT_PATIENCE
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    vad_threshold: float = DEFAULT_VAD_THRESHOLD
    noise_suppression: bool = False

    @classmethod
    def from_env(cls, **overrides: Any) -> "WakeEngineConfig":
        values: dict[str, Any] = {
            "model": os.getenv("GRANDPA_WAKE_MODEL", "").strip(),
            "threshold": _env_float("GRANDPA_WAKE_THRESHOLD", DEFAULT_THRESHOLD),
            "patience": int(_env_float("GRANDPA_WAKE_PATIENCE", DEFAULT_PATIENCE)),
            "cooldown_seconds": _env_float(
                "GRANDPA_WAKE_COOLDOWN", DEFAULT_COOLDOWN_SECONDS
            ),
            "vad_threshold": _env_float(
                "GRANDPA_WAKE_VAD_THRESHOLD", DEFAULT_VAD_THRESHOLD
            ),
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        config = cls(**values)
        return config.validated()

    def validated(self) -> "WakeEngineConfig":
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("wake threshold must be between 0 and 1")
        if self.patience < 1:
            raise ValueError("wake patience must be at least 1 frame")
        if self.cooldown_seconds < 0:
            raise ValueError("wake cooldown cannot be negative")
        if not 0.0 <= self.vad_threshold < 1.0:
            raise ValueError("wake VAD threshold must be between 0 and 1")
        return self


@dataclass(frozen=True)
class WakeEvent:
    """One detection."""

    model: str
    score: float
    at_seconds: float

    def describe(self) -> str:
        return f"{_clock(self.at_seconds)}  heard {self.model} (score {self.score:.2f})"


@dataclass(frozen=True)
class ResolvedModel:
    """Where the wake model comes from: a file, or an openWakeWord built-in."""

    reference: str
    label: str
    source: str  # "file" | "builtin"


def resolve_wake_model(
    model: str = "",
    *,
    search_dirs: Iterable[Path] | None = None,
    builtin_names: Iterable[str] | None = None,
) -> ResolvedModel:
    """Find the wake model, or raise :class:`WakeEngineUnavailable` with steps.

    ``model`` may be a path to an .onnx/.tflite file or a built-in openWakeWord
    name. Empty means "Hey Grandpa" from the usual places.
    """

    model = model.strip()
    if model:
        path = Path(model).expanduser()
        if path.suffix.lower() in {".onnx", ".tflite"} or path.exists():
            if not path.is_file():
                raise WakeEngineUnavailable(f"Wake model file not found: {path}")
            return ResolvedModel(str(path), path.stem, "file")
        names = set(builtin_names if builtin_names is not None else _builtin_names())
        if model in names:
            return ResolvedModel(model, model, "builtin")
        known = ", ".join(sorted(names)) or "none (is openwakeword installed?)"
        raise WakeEngineUnavailable(
            f"Unknown wake model {model!r}. Give a .onnx path or one of: {known}"
        )

    dirs = (
        list(search_dirs)
        if search_dirs is not None
        else [
            DEFAULT_MODEL_DIR,
            REPO_MODEL_DIR,
        ]
    )
    for directory in dirs:
        for suffix in (".onnx", ".tflite"):
            candidate = Path(directory) / f"{DEFAULT_MODEL_NAME}{suffix}"
            if candidate.is_file():
                return ResolvedModel(str(candidate), DEFAULT_MODEL_NAME, "file")
    raise WakeEngineUnavailable(SETUP_HINT)


def _builtin_names() -> list[str]:
    try:
        import openwakeword  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency
        return []
    return sorted(getattr(openwakeword, "MODELS", {}))


def load_openwakeword_model(resolved: ResolvedModel, config: WakeEngineConfig):
    """Build the openWakeWord ``Model`` (ONNX: tflite does not exist on Windows)."""

    try:
        from openwakeword.model import Model  # type: ignore
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise WakeEngineUnavailable(
            "openWakeWord is not installed. Run: uv sync --extra wake"
        ) from exc
    kwargs: dict[str, Any] = {
        "wakeword_models": [resolved.reference],
        "inference_framework": "onnx",
        "vad_threshold": config.vad_threshold,
        "enable_speex_noise_suppression": config.noise_suppression,
    }
    try:
        return Model(**kwargs)
    except Exception as exc:  # noqa: BLE001 - missing feature models, bad file
        raise WakeEngineUnavailable(
            f"openWakeWord could not load {resolved.label}: {exc}. "
            "If its feature models are missing, run: grandpa wake setup"
        ) from exc


class WakeWordEngine:
    """Turns 80 ms frames into wake events. Pure logic around ``model.predict``."""

    def __init__(
        self,
        config: WakeEngineConfig | None = None,
        *,
        model: Any = None,
        resolved: ResolvedModel | None = None,
    ) -> None:
        self.config = (config or WakeEngineConfig()).validated()
        if model is None:
            resolved = resolved or resolve_wake_model(self.config.model)
            model = load_openwakeword_model(resolved, self.config)
        self.resolved = resolved or ResolvedModel("injected", "injected", "file")
        self.model = model
        self._streak = 0
        self._samples_seen = 0
        self._cooldown_until = -math.inf
        self.peak_score = 0.0

    @property
    def label(self) -> str:
        return self.resolved.label

    @property
    def seconds_heard(self) -> float:
        return self._samples_seen / SAMPLE_RATE

    def process(self, frame: Any) -> WakeEvent | None:
        """Feed one frame of 16 kHz mono int16 audio (bytes or numpy)."""

        samples = _as_int16(frame)
        self._samples_seen += len(samples)
        now = self.seconds_heard
        scores = self.model.predict(samples) or {}
        score = max((float(v) for v in scores.values()), default=0.0)
        self.peak_score = max(self.peak_score, score)
        if now < self._cooldown_until:
            self._streak = 0
            return None
        if score >= self.config.threshold:
            self._streak += 1
        else:
            self._streak = 0
        if self._streak < self.config.patience:
            return None
        self._streak = 0
        self._cooldown_until = now + self.config.cooldown_seconds
        reset = getattr(self.model, "reset", None)
        if callable(reset):
            reset()
        return WakeEvent(model=self.label, score=score, at_seconds=now)

    def process_audio(self, pcm: Any) -> list[WakeEvent]:
        """Feed a whole recording; returns every detection in it."""

        samples = _as_int16(pcm)
        events: list[WakeEvent] = []
        for start in range(0, len(samples) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            event = self.process(samples[start : start + FRAME_SAMPLES])
            if event is not None:
                events.append(event)
        return events


@dataclass
class WakeReport:
    """What a file test or a listening session found."""

    seconds: float
    events: list[WakeEvent] = field(default_factory=list)
    peak_score: float = 0.0

    @property
    def triggers(self) -> int:
        return len(self.events)

    @property
    def per_hour(self) -> float:
        if self.seconds <= 0:
            return 0.0
        return self.triggers * 3600.0 / self.seconds

    def summary(self, *, negative: bool) -> str:
        minutes = self.seconds / 60.0
        line = (
            f"{self.triggers} trigger(s) in {minutes:.1f} min "
            f"(peak score {self.peak_score:.2f})"
        )
        if not negative:
            return line
        verdict = "within" if self.per_hour < FALSE_TRIGGER_BUDGET_PER_HOUR else "OVER"
        note = ""
        if self.seconds < 3600:
            note = " (under an hour of audio: a rough estimate)"
        return (
            f"{line}\nFalse triggers: {self.per_hour:.2f} per hour, {verdict} the "
            f"budget of < {FALSE_TRIGGER_BUDGET_PER_HOUR:g} per hour{note}"
        )


def evaluate_file(path: str | Path, engine: WakeWordEngine) -> WakeReport:
    """Run a WAV file through the engine (resampled to 16 kHz mono)."""

    samples = read_wav_16k_mono(path)
    events = engine.process_audio(samples)
    return WakeReport(
        seconds=len(samples) / SAMPLE_RATE,
        events=events,
        peak_score=engine.peak_score,
    )


def read_wav_16k_mono(path: str | Path):
    """Read a 16-bit PCM WAV as 16 kHz mono int16 (numpy)."""

    import numpy as np

    with wave.open(str(path), "rb") as wav:
        width = wav.getsampwidth()
        channels = wav.getnchannels()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(
            f"{path}: only 16-bit PCM WAV is supported (got {width * 8}-bit)"
        )
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(samples):
        duration = len(samples) / rate
        target = int(round(duration * SAMPLE_RATE))
        positions = np.linspace(0, len(samples) - 1, num=target)
        samples = np.interp(positions, np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype(np.int16)


class WakeWordListener:
    """Holds a 16 kHz microphone stream open and feeds the engine.

    ``on_wake`` runs on the audio reader thread; keep it short (B2 hands the
    event to the voice loop). Audio stays in memory.
    """

    def __init__(
        self,
        engine: WakeWordEngine,
        on_wake: Callable[[WakeEvent], None],
        *,
        device: int | str | None = None,
        sounddevice_module: Any = None,
    ) -> None:
        self.engine = engine
        self.on_wake = on_wake
        self.device = device
        self._sd = sounddevice_module
        self._stream: Any = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str = ""

    def start(self) -> None:
        sd = self._sd
        if sd is None:
            from grandpa.voice.device_manager import import_sounddevice

            sd = import_sounddevice()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self.device,
        )
        self._stream.start()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_forever, name="grandpa-wake-word", daemon=True
        )
        self._thread.start()

    def _read_forever(self) -> None:
        while not self._stop.is_set():
            try:
                data, _overflowed = self._stream.read(FRAME_SAMPLES)
            except Exception as exc:  # noqa: BLE001 - device unplugged etc.
                self.error = str(exc)
                return
            event = self.engine.process(data)
            if event is not None:
                self.on_wake(event)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001 - closing a dead stream
                pass
        self._stream = None

    def __enter__(self) -> "WakeWordListener":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def download_feature_models() -> str:
    """Fetch openWakeWord's shared feature models (melspectrogram, embedding, VAD).

    About 4 MB from openWakeWord's GitHub release, once. The wake model itself
    is separate (trained for "Hey Grandpa").
    """

    try:
        import openwakeword.utils as oww_utils  # type: ignore
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise WakeEngineUnavailable(
            "openWakeWord is not installed. Run: uv sync --extra wake"
        ) from exc
    oww_utils.download_models(["hey_mycroft"])
    import openwakeword  # type: ignore

    return str(Path(openwakeword.__file__).parent / "resources" / "models")


def status() -> dict[str, Any]:
    """What is installed and what is missing, for ``grandpa wake status``."""

    info: dict[str, Any] = {"openwakeword": False, "feature_models": False}
    try:
        import openwakeword  # type: ignore

        info["openwakeword"] = True
        models_dir = Path(openwakeword.__file__).parent / "resources" / "models"
        info["feature_models"] = all(
            (models_dir / name).is_file()
            for name in ("melspectrogram.onnx", "embedding_model.onnx")
        )
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    try:
        resolved = resolve_wake_model("")
        info["model"] = resolved.reference
    except WakeEngineUnavailable:
        info["model"] = ""
    return info


def _as_int16(frame: Any):
    import numpy as np

    if isinstance(frame, (bytes, bytearray, memoryview)):
        return np.frombuffer(bytes(frame), dtype="<i2")
    array = np.asarray(frame)
    if array.ndim > 1:
        array = array.reshape(-1)
    if array.dtype != np.int16:
        array = array.astype(np.int16)
    return array


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _clock(seconds: float) -> str:
    minutes, secs = divmod(max(0.0, seconds), 60.0)
    hours, minutes = divmod(minutes, 60.0)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:04.1f}"


__all__ = [
    "DEFAULT_MODEL_DIR",
    "FALSE_TRIGGER_BUDGET_PER_HOUR",
    "FRAME_SAMPLES",
    "SAMPLE_RATE",
    "ResolvedModel",
    "WakeEngineConfig",
    "WakeEngineUnavailable",
    "WakeEvent",
    "WakeReport",
    "WakeWordEngine",
    "WakeWordListener",
    "download_feature_models",
    "read_wav_16k_mono",
    "resolve_wake_model",
    "evaluate_file",
    "status",
]
