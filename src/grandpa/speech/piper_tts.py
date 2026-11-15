"""Piper TTS backend: a local, offline neural voice (ONNX on the CPU).

Piper (https://github.com/OHF-Voice/piper1-gpl) runs small VITS voices with
onnxruntime. A medium voice is ~60 MB, loads in well under a second and speaks
faster than real time on a laptop CPU, so it sits beside Ollama without a GPU.

Voices live in ``~/.Grandpa/voices`` as ``<name>.onnx`` + ``<name>.onnx.json``
(``grandpa voice-model`` can fetch them; see ``download_voice``).
``GRANDPA_PIPER_VOICE`` picks one by name or by full path to the ``.onnx``.

Optional dependency: ``piper-tts`` (``uv sync --extra piper``). Without it, or
without a voice file, this backend reports itself unhealthy and Grandpa keeps
using pyttsx3.
"""

from __future__ import annotations

import io
import os
import threading
import urllib.request
import wave
from pathlib import Path
from typing import Any, List

from grandpa.core.registry import TTSRegistry
from grandpa.speech.tts import TTSBackend, TTSResult


def voices_dir() -> Path:
    """Where Piper voices live, resolved when asked (never at import)."""
    return Path.home() / ".Grandpa" / "voices"


ENV_VOICE = "GRANDPA_PIPER_VOICE"
DEFAULT_VOICE = "en_GB-alan-medium"
"""A calm, mature British male voice: the closest stock Piper voice to a wise grandpa."""
LENGTH_SCALE = 1.08
"""Speech length multiplier: a little slower than Piper's default, an old man's pace."""
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{family}/{lang}/{name}/{quality}/{voice}{ext}"

_lock = threading.Lock()
_loaded: dict[Path, Any] = {}


def voice_path(voice: str | None = None) -> Path | None:
    """The ``.onnx`` file for ``voice`` (a name or a path), if it and its config exist."""
    choice = (voice or os.environ.get(ENV_VOICE, "") or DEFAULT_VOICE).strip()
    path = Path(choice).expanduser()
    if path.suffix != ".onnx":
        path = voices_dir() / f"{choice}.onnx"
    config = path.with_name(path.name + ".json")
    return path if path.is_file() and config.is_file() else None


def piper_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("piper") is not None


def ready(voice: str | None = None) -> bool:
    """True when the package and a voice are both present."""
    return piper_installed() and voice_path(voice) is not None


def _load(path: Path) -> Any:
    with _lock:
        if path not in _loaded:
            from piper import PiperVoice

            _loaded[path] = PiperVoice.load(str(path))
        return _loaded[path]


def synthesize_wav(
    text: str,
    path: Path,
    *,
    voice: str | None = None,
    length_scale: float = LENGTH_SCALE,
) -> None:
    """Write ``text`` as speech to the WAV file ``path``."""
    model = voice_path(voice)
    if model is None:
        raise RuntimeError(
            f"No Piper voice found (looked for {voice or os.environ.get(ENV_VOICE) or DEFAULT_VOICE} in {voices_dir()})."
        )
    engine = _load(model)
    with wave.open(str(path), "wb") as wav:
        try:  # piper-tts >= 1.3
            from piper import SynthesisConfig

            engine.synthesize_wav(
                text, wav, syn_config=SynthesisConfig(length_scale=length_scale)
            )
        except ImportError:  # piper-tts 1.2
            engine.synthesize(text, wav, length_scale=length_scale)


def download_voice(
    voice: str = DEFAULT_VOICE, dest: Path | None = None, timeout: float = 300.0
) -> Path:
    """Fetch ``<voice>.onnx`` and its ``.json`` from the Piper voice collection.

    ``voice`` is ``<lang>-<name>-<quality>``, for example ``en_GB-alan-medium``.
    Files already present are kept.
    """
    dest = voices_dir() if dest is None else dest
    lang, name, quality = voice.split("-", 2)
    dest.mkdir(parents=True, exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        out = dest / f"{voice}{ext}"
        if out.is_file() and out.stat().st_size > 0:
            continue
        url = VOICE_URL.format(
            family=lang.split("_")[0],
            lang=lang,
            name=name,
            quality=quality,
            voice=voice,
            ext=ext,
        )
        tmp = out.with_name(out.name + ".part")
        with (
            urllib.request.urlopen(url, timeout=timeout) as response,
            open(tmp, "wb") as fh,
        ):
            while chunk := response.read(1 << 16):
                fh.write(chunk)
        tmp.replace(out)
    return dest / f"{voice}.onnx"


@TTSRegistry.register("piper")
class PiperTTSBackend(TTSBackend):
    """Piper: local neural TTS through onnxruntime."""

    backend_id = "piper"

    def __init__(self, *, voice: str = "", length_scale: float = LENGTH_SCALE) -> None:
        self._voice = voice or None
        self._length_scale = length_scale

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        voice = voice_id or self._voice
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            model = voice_path(voice)
            if model is None:
                raise RuntimeError("No Piper voice installed.")
            engine = _load(model)
            scale = self._length_scale / max(speed, 0.1)
            try:
                from piper import SynthesisConfig

                engine.synthesize_wav(
                    text, wav, syn_config=SynthesisConfig(length_scale=scale)
                )
            except ImportError:
                engine.synthesize(text, wav, length_scale=scale)
        data = buf.getvalue()
        with wave.open(io.BytesIO(data), "rb") as check:
            rate, frames = check.getframerate(), check.getnframes()
        return TTSResult(
            audio=data,
            format="wav",
            voice_id=(voice or os.environ.get(ENV_VOICE) or DEFAULT_VOICE),
            sample_rate=rate,
            duration_seconds=frames / rate if rate else 0.0,
            metadata={"backend": "piper"},
        )

    def available_voices(self) -> List[str]:
        folder = voices_dir()
        if not folder.is_dir():
            return []
        return sorted(
            p.stem
            for p in folder.glob("*.onnx")
            if p.with_name(p.name + ".json").is_file()
        )

    def health(self) -> bool:
        return ready(self._voice)


__all__ = [
    "DEFAULT_VOICE",
    "ENV_VOICE",
    "LENGTH_SCALE",
    "PiperTTSBackend",
    "voices_dir",
    "download_voice",
    "piper_installed",
    "ready",
    "synthesize_wav",
    "voice_path",
]


def main(argv: list[str] | None = None) -> int:
    """``python -m grandpa.speech.piper_tts download [voice ...]`` / ``list``."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"download", "list"}:
        print("usage: python -m grandpa.speech.piper_tts download [voice ...] | list")
        return 2
    if args[0] == "list":
        for name in PiperTTSBackend().available_voices():
            print(name)
        return 0
    for name in args[1:] or [DEFAULT_VOICE]:
        print("downloading", name, "...", flush=True)
        print("saved", download_voice(name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
