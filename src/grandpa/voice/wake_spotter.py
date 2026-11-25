""""Hey Grandpa" without a trained wake model.

openWakeWord needs a ``hey_grandpa.onnx`` that is trained once on a GPU
(``wake_engine.py``). Until that exists, this module listens a cheaper way:

1. Every 80 ms frame gets an energy check against a noise floor that follows
   the room. Silence costs almost nothing.
2. When someone speaks, the frames are collected into one short segment
   (0.3 s of pre-roll, ending at 0.6 s of quiet, at most 6 s).
3. Only that segment goes to a tiny Whisper model (``tiny.en``, int8, CPU),
   on a worker thread, one at a time. A segment that arrives while the last
   one is still being read is dropped, so a playing video cannot pile up work.
4. The words must *start* with the wake phrase ("hey grandpa", "hi grandpa",
   "grandpa", ...). "I called my grandpa" does not wake him.

Audio stays in memory and is dropped after the check. Nothing is written.

The engine has the same ``process(frame)`` shape as
:class:`grandpa.voice.wake_engine.WakeWordEngine`, so
:class:`~grandpa.voice.wake_engine.WakeWordListener` drives either one.
"""

from __future__ import annotations

import io
import logging
import math
import re
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE

SPOTTER_MODEL = "tiny.en"

GREETINGS = frozenset({"hey", "hi", "hello", "ok", "okay", "hay", "yo", "a", "eh"})
#: How Whisper tends to spell "Grandpa" when it is said quickly or with an accent.
GRANDPA_WORDS = frozenset(
    {"grandpa", "granpa", "grampa", "grandpaa", "grandpappa", "grandpas", "grandpa's"}
)


@dataclass(frozen=True)
class WakeMatch:
    """What the spotter heard. ``rest`` is how many words followed the phrase."""

    matched: bool
    rest: int = 0


def match_wake(transcript: str) -> WakeMatch:
    """Does ``transcript`` *start* with "Hey Grandpa" (or a close spelling)?

    Allowed: "Grandpa, ...", "Hey Grandpa ...", "Hi, Grandpa!", "Hey grand pa".
    Not allowed: the phrase later in the sentence ("I told grandpa ...").
    """
    words = re.sub(r"[^\w\s']", " ", str(transcript).casefold()).split()
    # "grand pa" -> "grandpa"
    joined: list[str] = []
    for word in words:
        if joined and joined[-1] == "grand" and word == "pa":
            joined[-1] = "grandpa"
        else:
            joined.append(word)
    words = joined
    if not words:
        return WakeMatch(False)
    if words[0] in GRANDPA_WORDS:
        return WakeMatch(True, len(words) - 1)
    if len(words) >= 2 and words[0] in GREETINGS and words[1] in GRANDPA_WORDS:
        return WakeMatch(True, len(words) - 2)
    return WakeMatch(False)


def pcm_to_wav(samples: Any) -> bytes:
    """16 kHz mono int16 samples as a WAV file in memory."""
    import numpy as np

    data = np.asarray(samples, dtype=np.int16).tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(data)
    return buffer.getvalue()


class WhisperSpotter:
    """Reads one short segment with ``tiny.en``. Loaded on first use."""

    def __init__(self, model: str = SPOTTER_MODEL, factory: Callable[..., Any] | None = None):
        self.model_name = model
        self._factory = factory
        self._model: Any = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            factory = self._factory
            if factory is None:
                from faster_whisper import WhisperModel

                factory = WhisperModel
            self._model = factory(self.model_name, device="cpu", compute_type="int8", cpu_threads=2)

    def __call__(self, samples: Any) -> str:
        import numpy as np

        self.load()
        audio = np.asarray(samples, dtype=np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


@dataclass(frozen=True)
class SpotterConfig:
    minimum_rms: float = 300.0
    noise_multiplier: float = 3.0
    preroll_seconds: float = 0.3
    end_silence_seconds: float = 0.6
    minimum_seconds: float = 0.35
    maximum_seconds: float = 6.0
    cooldown_seconds: float = 2.0


class TranscriptWakeEngine:
    """Energy-gated segments, read by a tiny Whisper, matched on the words.

    ``on_wake(samples, match)`` runs on the worker thread with the segment
    that held the phrase, so the caller can re-read it with the main speech
    model when words followed it ("Hey Grandpa, open Notepad").
    ``gate()`` returning False (Grandpa busy, speaking, or the key held)
    makes the engine drop what it has and ignore audio until it is True.
    """

    label = "Hey Grandpa (speech check, tiny.en)"

    def __init__(
        self,
        on_wake: Callable[[Any, WakeMatch], None],
        *,
        spotter: Callable[[Any], str] | None = None,
        gate: Callable[[], bool] = lambda: True,
        config: SpotterConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        run: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.on_wake = on_wake
        self.spotter = spotter or WhisperSpotter()
        self.gate = gate
        self.config = config or SpotterConfig()
        self.clock = clock
        self._run = run or self._in_thread
        self._floor = 0.0
        preroll = max(1, round(self.config.preroll_seconds / FRAME_SECONDS))
        self._preroll: deque = deque(maxlen=preroll)
        self._segment: list[Any] = []
        self._speech_frames = 0
        self._quiet_frames = 0
        self._skip_until_quiet = False
        self._working = threading.Event()
        self._quiet_until = 0.0
        self.segments_read = 0
        self.segments_dropped = 0

    # --- audio thread -------------------------------------------------------

    def process(self, frame: Any) -> None:
        import numpy as np

        samples = np.asarray(frame, dtype=np.int16).reshape(-1)
        if not self.gate() or self.clock() < self._quiet_until:
            self._drop()
            return
        rms = math.sqrt(float(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0
        threshold = max(self.config.minimum_rms, self._floor * self.config.noise_multiplier)
        speech = rms >= threshold
        if not speech:
            # the floor follows the room, slowly, from quiet frames only
            self._floor = rms if self._floor == 0.0 else 0.95 * self._floor + 0.05 * rms
        if self._skip_until_quiet:
            if speech:
                self._quiet_frames = 0
            else:
                self._quiet_frames += 1
                if self._quiet_frames * FRAME_SECONDS >= self.config.end_silence_seconds:
                    self._skip_until_quiet = False
                    self._quiet_frames = 0
            return
        if not self._segment:
            self._preroll.append(samples)
            if speech:
                self._segment = list(self._preroll)
                self._preroll.clear()
                self._speech_frames, self._quiet_frames = 1, 0
            return
        self._segment.append(samples)
        if speech:
            self._speech_frames += 1
            self._quiet_frames = 0
        else:
            self._quiet_frames += 1
        seconds = len(self._segment) * FRAME_SECONDS
        if seconds >= self.config.maximum_seconds:
            self._finish()
            self._skip_until_quiet = True  # the rest of a long talk is not a wake
        elif self._quiet_frames * FRAME_SECONDS >= self.config.end_silence_seconds:
            self._finish()

    def _drop(self) -> None:
        self._segment = []
        self._preroll.clear()
        self._speech_frames = self._quiet_frames = 0
        self._skip_until_quiet = False

    def _finish(self) -> None:
        import numpy as np

        segment, speech = self._segment, self._speech_frames
        self._segment = []
        self._speech_frames = self._quiet_frames = 0
        if speech * FRAME_SECONDS < self.config.minimum_seconds:
            return  # a click or a cough
        if self._working.is_set():
            self.segments_dropped += 1
            return
        self._working.set()
        samples = np.concatenate(segment)
        self._run(lambda: self._read(samples))

    # --- worker -------------------------------------------------------------

    @staticmethod
    def _in_thread(job: Callable[[], None]) -> None:
        threading.Thread(target=job, name="grandpa-wake-spot", daemon=True).start()

    def _read(self, samples: Any) -> None:
        try:
            text = self.spotter(samples)
            self.segments_read += 1
            match = match_wake(text)
            if match.matched and self.gate():
                logger.info("wake phrase heard: %r", text)
                self._quiet_until = self.clock() + self.config.cooldown_seconds
                self.on_wake(samples, match)
        except Exception:  # noqa: BLE001 - one bad segment must not stop listening
            logger.exception("wake spotter failed")
        finally:
            self._working.clear()


__all__ = [
    "GRANDPA_WORDS",
    "SpotterConfig",
    "TranscriptWakeEngine",
    "WakeMatch",
    "WhisperSpotter",
    "match_wake",
    "pcm_to_wav",
]
