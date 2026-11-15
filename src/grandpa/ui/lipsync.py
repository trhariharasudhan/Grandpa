"""Lip-sync for the avatar (A4): a timed track of mouth shapes for one reply.

Python decides the mouth, the page only draws it -- the same rule as the
states. For one reply Grandpa is about to say aloud:

1. the reply is synthesised to a WAV file first (pyttsx3, the T2 default);
2. the WAV's loudness is measured every :data:`FRAME_MS` (the *amplitude* pass);
3. the reply's letters are turned into mouth shapes, a rough grapheme ->
   phoneme -> viseme guess (the *phoneme* pass), and spread over the stretch
   of audio that is actually loud, each shape opened as wide as the audio is
   loud at that moment. Text with no Latin letters (Tamil script) gets the
   amplitude pass alone: the mouth opens with the voice;
4. the track and the wall-clock time playback will start are published in one
   ``speaking`` state, then the WAV is played.

The page plays the track against ``Date.now() - speech_start_ms``. Both clocks
are this PC's clock, so the WebSocket's delay does not shift the mouth; the
only drift left is the sound card's own output latency.

Viseme names are the shape keys Captain's ``grandpa.glb`` carries:
AA, E, I, O, U, FV, MBP, plus ``rest`` (mouth closed, no key).
"""

from __future__ import annotations

import logging
import math
import os
import re
import sys
import tempfile
import time
import wave
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VISEMES = ("AA", "E", "I", "O", "U", "FV", "MBP", "rest")
FRAME_MS = 20
"""One loudness reading per 20 ms of audio."""
MAX_TRACK = 600
"""Most entries one track may carry (about 30 s of quick speech)."""
SILENCE = 0.08
"""Below this (0..1, of the reply's loud level) the mouth rests."""
LEAD_MS = 60
"""Playback starts this long after the state is published, so the page has the
track before the first sound. Small against the 100 ms drift budget, because
the page's clock already accounts for it."""
WORDS_PER_MINUTE = 185
"""pyttsx3's speaking rate, the same as the speech output engine's."""

# --- the phoneme pass -----------------------------------------------------------

# (letters, viseme, weight, relative length). Longest match first.
_DIGRAPHS: dict[str, tuple[str, float, float]] = {
    "ee": ("I", 1.0, 1.3),
    "ea": ("I", 1.0, 1.3),
    "ie": ("I", 1.0, 1.2),
    "oo": ("U", 1.0, 1.3),
    "ou": ("O", 1.0, 1.3),
    "ow": ("O", 1.0, 1.3),
    "oa": ("O", 1.0, 1.3),
    "ai": ("E", 1.0, 1.3),
    "ay": ("E", 1.0, 1.3),
    "au": ("AA", 1.0, 1.3),
    "aw": ("AA", 1.0, 1.3),
    "ph": ("FV", 1.0, 0.7),
    "wh": ("U", 0.7, 0.6),
    "th": ("E", 0.35, 0.6),
    "sh": ("U", 0.5, 0.7),
    "ch": ("U", 0.5, 0.7),
    "ng": ("E", 0.3, 0.5),
}
_LETTERS: dict[str, tuple[str, float, float]] = {
    "a": ("AA", 1.0, 1.0),
    "e": ("E", 0.9, 0.9),
    "i": ("I", 0.9, 0.9),
    "y": ("I", 0.7, 0.8),
    "o": ("O", 1.0, 1.0),
    "u": ("U", 0.9, 0.9),
    "w": ("U", 0.7, 0.6),
    "q": ("U", 0.6, 0.6),
    "m": ("MBP", 1.0, 0.7),
    "b": ("MBP", 1.0, 0.6),
    "p": ("MBP", 1.0, 0.6),
    "f": ("FV", 1.0, 0.7),
    "v": ("FV", 1.0, 0.7),
}
_CONSONANT = ("E", 0.3, 0.55)
"""t d n l s z k g h r c x j: a narrow, half-open mouth."""
_PAUSES = {",": 1.5, ";": 1.5, ":": 1.5, ".": 2.5, "!": 2.5, "?": 2.5}
_WORD_GAP = 0.25


@dataclass(frozen=True, slots=True)
class Token:
    viseme: str
    weight: float
    length: float


def text_to_tokens(text: str) -> list[Token]:
    """The reply's letters as mouth shapes, each with a relative length.

    A rough guess at English pronunciation, good enough for a mouth: vowels
    open it, m/b/p close it, f/v bite the lip. A silent final "e" is dropped.
    Pauses at punctuation are ``rest`` tokens.
    """
    tokens: list[Token] = []
    for word in re.findall(r"[A-Za-z']+|[,;:.!?]|\s+|[^\sA-Za-z']+", text.lower()):
        if word.isspace():
            tokens.append(Token("rest", 0.0, _WORD_GAP))
            continue
        if word in _PAUSES:
            tokens.append(Token("rest", 0.0, _PAUSES[word]))
            continue
        if not re.fullmatch(r"[a-z']+", word):
            continue  # digits, symbols, other scripts: the amplitude pass covers them
        letters = word.replace("'", "")
        if len(letters) > 2 and letters.endswith("e") and letters[-2] not in "aeiouy":
            letters = letters[:-1]
        i = 0
        while i < len(letters):
            pair = letters[i : i + 2]
            if pair in _DIGRAPHS:
                viseme, weight, length = _DIGRAPHS[pair]
                i += 2
            else:
                viseme, weight, length = _LETTERS.get(letters[i], _CONSONANT)
                i += 1
            tokens.append(Token(viseme, weight, length))
    return tokens


# --- the amplitude pass ---------------------------------------------------------


def read_wav(path: Path) -> tuple[list[float], int]:
    """Mono samples in -1..1 and the sample rate, from a PCM WAV file."""
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 1:
        values = [(b - 128) / 128.0 for b in raw]
    elif width in (2, 4):
        data = array("h" if width == 2 else "i", raw[: len(raw) - len(raw) % width])
        if sys.byteorder == "big":
            data.byteswap()
        scale = float(2 ** (8 * width - 1))
        values = [v / scale for v in data]
    else:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    if channels > 1:
        values = [
            sum(values[i : i + channels]) / channels
            for i in range(0, len(values) - channels + 1, channels)
        ]
    return values, rate


def envelope(
    samples: Sequence[float], sample_rate: int, frame_ms: int = FRAME_MS
) -> list[float]:
    """Loudness per frame, 0..1, relative to the reply's own loud level."""
    if sample_rate <= 0:
        return []
    step = max(1, int(sample_rate * frame_ms / 1000))
    levels: list[float] = []
    for start in range(0, len(samples), step):
        chunk = samples[start : start + step]
        levels.append(
            math.sqrt(sum(v * v for v in chunk) / len(chunk)) if chunk else 0.0
        )
    if not levels:
        return []
    ordered = sorted(levels)
    loud = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] or max(ordered)
    if loud <= 0:
        return [0.0] * len(levels)
    return [min(1.0, level / loud) for level in levels]


# --- the track ------------------------------------------------------------------


def build_track(
    text: str,
    duration_ms: int,
    levels: Sequence[float] | None = None,
    frame_ms: int = FRAME_MS,
) -> tuple[dict[str, Any], ...]:
    """``({"t": ms, "v": viseme, "w": 0..1}, ...)``, ending with ``rest``.

    ``t`` is from the start of playback. With ``levels`` (the envelope), the
    letters are spread over the loud stretch only and every shape is scaled by
    how loud the audio is right then; silent frames are ``rest``.
    """
    duration_ms = max(0, int(duration_ms))
    if duration_ms == 0:
        return ({"t": 0, "v": "rest", "w": 0.0},)
    tokens = text_to_tokens(text)
    entries: list[tuple[int, str, float]] = []

    def level_at(ms: float) -> float:
        if not levels:
            return 1.0
        index = min(len(levels) - 1, max(0, int(ms // frame_ms)))
        return levels[index]

    voiced = [i for i, level in enumerate(levels or []) if level >= SILENCE]
    if levels and not voiced:
        return (
            {"t": 0, "v": "rest", "w": 0.0},
            {"t": duration_ms, "v": "rest", "w": 0.0},
        )
    span_start = voiced[0] * frame_ms if voiced else 0
    span_end = min(duration_ms, (voiced[-1] + 1) * frame_ms) if voiced else duration_ms

    if any(t.viseme != "rest" for t in tokens):
        total = sum(t.length for t in tokens) or 1.0
        at = float(span_start)
        span = max(1, span_end - span_start)
        for token in tokens:
            level = level_at(at)
            if token.viseme == "rest" or level < SILENCE:
                entries.append((int(at), "rest", 0.0))
            else:
                entries.append((int(at), token.viseme, round(token.weight * level, 2)))
            at += token.length / total * span
    elif levels:
        # no letters to read (Tamil script, digits): the mouth follows the voice
        for index, level in enumerate(levels):
            entries.append(
                (
                    index * frame_ms,
                    "AA" if level >= SILENCE else "rest",
                    round(level, 2),
                )
            )
    if levels:
        # silences inside the span close the mouth even mid-word
        for index, level in enumerate(levels):
            if level < SILENCE and span_start <= index * frame_ms < span_end:
                entries.append((index * frame_ms, "rest", 0.0))
        entries.sort(key=lambda e: e[0])

    track: list[dict[str, Any]] = []
    if not entries or entries[0][0] > 0:
        track.append({"t": 0, "v": "rest", "w": 0.0})
    for t, viseme, weight in entries:
        if track and track[-1]["v"] == viseme and abs(track[-1]["w"] - weight) < 0.05:
            continue
        if track and track[-1]["t"] == t:
            track[-1] = {"t": t, "v": viseme, "w": weight}
            continue
        track.append({"t": t, "v": viseme, "w": weight})
    if len(track) > MAX_TRACK - 1:
        stride = math.ceil(len(track) / (MAX_TRACK - 1))
        track = track[::stride]
    track.append({"t": duration_ms, "v": "rest", "w": 0.0})
    return tuple(track)


# --- saying it ------------------------------------------------------------------


def synthesize_wav_pyttsx3(
    text: str, path: Path, *, rate: int = WORDS_PER_MINUTE
) -> None:
    """Write ``text`` as speech to ``path`` with pyttsx3 (SAPI5 on Windows)."""
    pyttsx3 = __import__("pyttsx3")
    engine = pyttsx3.init()
    if rate:
        engine.setProperty("rate", rate)
    engine.save_to_file(text, str(path))
    engine.runAndWait()


def play_wav(path: Path) -> None:
    """Play a WAV file and return when it has finished."""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return
    import sounddevice as sd
    import soundfile as sf

    data, rate = sf.read(str(path))
    sd.play(data, rate)
    sd.wait()


OnStart = Callable[[tuple[dict[str, Any], ...], float], None]


@dataclass
class LipSyncSpeaker:
    """Says one reply aloud and hands the mouth track over just before."""

    synthesize: Callable[[str, Path], None] = synthesize_wav_pyttsx3
    play: Callable[[Path], None] = play_wav
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    lead_ms: int = LEAD_MS
    max_chars: int = 360

    def speak(self, text: str, on_start: OnStart) -> bool:
        """Synthesise, publish the track with ``on_start``, play. False if silent."""
        from grandpa.voice.text_to_speech import clean_text_for_speech

        clean = clean_text_for_speech(text, max_chars=self.max_chars)
        if not clean:
            return False
        handle, name = tempfile.mkstemp(prefix="grandpa-say-", suffix=".wav")
        os.close(handle)
        path = Path(name)
        try:
            return self._speak_file(clean, path, on_start)
        finally:
            path.unlink(missing_ok=True)

    def _speak_file(self, clean: str, path: Path, on_start: OnStart) -> bool:
        try:
            self.synthesize(clean, path)
            samples, rate = read_wav(path)
        except Exception:  # noqa: BLE001 - no voice is not a broken avatar
            logger.warning("avatar speech could not be synthesised", exc_info=True)
            return False
        duration_ms = int(len(samples) * 1000 / rate) if rate else 0
        if duration_ms <= 0:
            return False
        track = build_track(clean, duration_ms, envelope(samples, rate))
        start_ms = self.clock() * 1000 + self.lead_ms
        on_start(track, start_ms)
        wait = start_ms / 1000 - self.clock()
        if wait > 0:
            self.sleep(wait)
        try:
            self.play(path)
        except Exception:  # noqa: BLE001
            logger.warning("avatar speech could not be played", exc_info=True)
            return False
        return True


def default_speaker() -> tuple[LipSyncSpeaker | None, str]:
    """The speaker ``grandpa avatar`` uses, and one line saying why or why not."""
    import importlib.util

    try:
        from grandpa.core.config import load_config

        tts = load_config().tts
        if not tts.enabled:
            return None, "Voice: off (tts.enabled is false in your config)."
    except Exception:  # noqa: BLE001 - a broken config should not stop the window
        pass
    if os.environ.get(ENV_VOICE_ENGINE, "").strip().lower() != "pyttsx3":
        speaker = _piper_speaker()
        if speaker is not None:
            return speaker
    if importlib.util.find_spec("pyttsx3") is None:
        return None, "Voice: off (pyttsx3 is not installed)."
    return LipSyncSpeaker(), "Voice: on, pyttsx3 with lip-sync (--quiet turns it off)."


ENV_VOICE_ENGINE = "GRANDPA_AVATAR_VOICE"
"""Set to ``pyttsx3`` to keep the old Windows voice even when Piper is installed."""


def _piper_speaker() -> tuple[LipSyncSpeaker, str] | None:
    """Piper (a local neural voice) when its package and a voice are installed.

    The voice is loaded in the background right away, so the first reply does
    not wait for it (loading takes ~1.5 s on the Vivobook; speaking a reply
    then takes ~0.13 s per second of audio)."""
    try:
        from grandpa.speech import piper_tts
    except Exception:  # noqa: BLE001 - an optional voice must not stop the window
        return None
    if not piper_tts.ready():
        return None
    model = piper_tts.voice_path()

    def warm() -> None:
        try:
            piper_tts._load(model)
        except Exception:  # noqa: BLE001
            logger.warning("Piper voice could not be loaded", exc_info=True)

    import threading

    threading.Thread(target=warm, name="piper-warm", daemon=True).start()
    speaker = LipSyncSpeaker(
        synthesize=lambda text, path: piper_tts.synthesize_wav(text, path)
    )
    return (
        speaker,
        f"Voice: on, Piper ({model.stem}) with lip-sync (--quiet turns it off).",
    )


__all__ = [
    "FRAME_MS",
    "LEAD_MS",
    "LipSyncSpeaker",
    "MAX_TRACK",
    "VISEMES",
    "build_track",
    "default_speaker",
    "envelope",
    "play_wav",
    "read_wav",
    "synthesize_wav_pyttsx3",
    "text_to_tokens",
]
