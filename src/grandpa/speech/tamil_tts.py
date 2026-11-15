"""Tamil voice: Meta's MMS Tamil TTS (VITS) run locally with sherpa-onnx.

Piper has no Tamil voice, so replies written in Tamil script were spoken by the
English voice (or not at all). MMS ``tam`` is a single-speaker VITS model;
converted to ONNX it is ~114 MB and runs on the CPU through sherpa-onnx, with
no PyTorch beside Ollama.

The model lives in ``~/.Grandpa/voices/mms-tam`` (``model.onnx`` +
``tokens.txt``); ``python -m grandpa.speech.tamil_tts download`` fetches it
from the ``willwade/mms-tts-multilingual-models-onnx`` conversion.

Licence: MMS weights are CC-BY-NC 4.0 (non-commercial). Fine for Captain's
own Grandpa; re-check before any commercial release.

Optional dependency: ``sherpa-onnx`` (``uv sync --extra tamil-voice``).
"""

from __future__ import annotations

import io
import os
import threading
import urllib.request
import wave
from array import array
from pathlib import Path
from typing import Any, List

from grandpa.core.registry import TTSRegistry
from grandpa.speech.tts import TTSBackend, TTSResult

MODEL_SUBDIR = ("voices", "mms-tam")
"""Under ~/.Grandpa, resolved by :func:`model_dir` when asked (never at import)."""
ENV_MODEL_DIR = "GRANDPA_TAMIL_VOICE_DIR"
MODEL_URL = "https://huggingface.co/willwade/mms-tts-multilingual-models-onnx/resolve/main/tam/{file}"
FILES = ("tokens.txt", "model.onnx")
SPEED = 0.95
"""A touch slower than the model's default: an old man's pace."""
THREADS = 4

_lock = threading.Lock()
_loaded: dict[Path, Any] = {}

_TAMIL = range(0x0B80, 0x0C00)


def tamil_share(text: str) -> float:
    """The share of the letters in ``text`` that are Tamil script (0..1)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if ord(c) in _TAMIL) / len(letters)


def is_tamil(text: str, threshold: float = 0.5) -> bool:
    """True when most of the reply is written in Tamil script."""
    return tamil_share(text) >= threshold


def model_dir() -> Path:
    custom = os.environ.get(ENV_MODEL_DIR, "").strip()
    return (
        Path(custom).expanduser()
        if custom
        else Path.home() / ".Grandpa" / Path(*MODEL_SUBDIR)
    )


def model_ready() -> bool:
    folder = model_dir()
    return all(
        (folder / name).is_file() and (folder / name).stat().st_size > 0
        for name in FILES
    )


def sherpa_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("sherpa_onnx") is not None


def ready() -> bool:
    return sherpa_installed() and model_ready()


def _load(folder: Path) -> Any:
    with _lock:
        if folder not in _loaded:
            import sherpa_onnx

            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(folder / "model.onnx"),
                        tokens=str(folder / "tokens.txt"),
                    ),
                    num_threads=THREADS,
                    provider="cpu",
                ),
            )
            _loaded[folder] = sherpa_onnx.OfflineTts(config)
        return _loaded[folder]


def _to_wav(samples, sample_rate: int, wav: wave.Wave_write) -> None:
    pcm = array("h", (max(-32768, min(32767, int(s * 32767))) for s in samples))
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(int(sample_rate))
    wav.writeframes(pcm.tobytes())


def clean_for_model(text: str) -> str:
    """Keep what the MMS Tamil alphabet has: Tamil letters, digits and spaces.

    Sentence punctuation is not in its token list (sherpa-onnx skips it with a
    warning per character); a pause is kept as a space instead."""
    out = []
    for ch in text:
        if ord(ch) in _TAMIL or ch.isdigit() or ch == "'":
            out.append(ch)
        elif ch.isspace() or ch in ".,;:!?-–—()":
            out.append(" ")
        elif ch.isascii() and ch.isalpha():
            out.append(ch.lower())  # stray Latin letters: the model knows a-z
    return " ".join("".join(out).split())


def synthesize_wav(text: str, path: Path, *, speed: float = SPEED) -> None:
    """Write Tamil ``text`` as speech to the WAV file ``path``.

    On the Vivobook: ~5 s to load once (done in the background at avatar
    start), then ~0.6 s per second of audio."""
    if not model_ready():
        raise RuntimeError(f"No Tamil voice model in {model_dir()}.")
    engine = _load(model_dir())
    audio = engine.generate(clean_for_model(text), sid=0, speed=speed)
    if not len(audio.samples):
        raise RuntimeError("The Tamil voice produced no audio.")
    with wave.open(str(path), "wb") as wav:
        _to_wav(audio.samples, audio.sample_rate, wav)


def download(dest: Path | None = None, timeout: float = 900.0) -> Path:
    """Fetch ``model.onnx`` and ``tokens.txt``; files already present are kept."""
    folder = dest or model_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        out = folder / name
        if out.is_file() and out.stat().st_size > 0:
            continue
        tmp = out.with_name(out.name + ".part")
        with (
            urllib.request.urlopen(
                MODEL_URL.format(file=name), timeout=timeout
            ) as response,
            open(tmp, "wb") as fh,
        ):
            while chunk := response.read(1 << 16):
                fh.write(chunk)
        tmp.replace(out)
    return folder


@TTSRegistry.register("mms_tamil")
class TamilTTSBackend(TTSBackend):
    """MMS Tamil through sherpa-onnx."""

    backend_id = "mms_tamil"

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if not model_ready():
            raise RuntimeError("No Tamil voice model installed.")
        audio = _load(model_dir()).generate(
            clean_for_model(text), sid=0, speed=SPEED * speed
        )
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            _to_wav(audio.samples, audio.sample_rate, wav)
        rate = int(audio.sample_rate)
        return TTSResult(
            audio=buf.getvalue(),
            format="wav",
            voice_id="mms-tam",
            sample_rate=rate,
            duration_seconds=len(audio.samples) / rate if rate else 0.0,
            metadata={"backend": "mms_tamil"},
        )

    def available_voices(self) -> List[str]:
        return ["mms-tam"] if model_ready() else []

    def health(self) -> bool:
        return ready()


def main(argv: list[str] | None = None) -> int:
    """``python -m grandpa.speech.tamil_tts download``."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["download"]:
        print("usage: python -m grandpa.speech.tamil_tts download")
        return 2
    print("downloading the MMS Tamil voice (~114 MB) ...", flush=True)
    print("saved", download())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MODEL_SUBDIR",
    "clean_for_model",
    "TamilTTSBackend",
    "download",
    "is_tamil",
    "model_ready",
    "ready",
    "synthesize_wav",
    "tamil_share",
]
