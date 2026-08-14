"""Apply the proven Windows CPU inference fixes to F5-TTS 1.1.22."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

SUPPORTED_VERSION = "1.1.22"


def _replace_once(path: Path, original: str, replacement: str) -> str:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return "already_applied"
    if text.count(original) != 1:
        raise RuntimeError(f"Unexpected source layout in {path}")
    path.write_text(text.replace(original, replacement), encoding="utf-8")
    return "applied"


def main() -> int:
    version = importlib.metadata.version("f5-tts")
    if version != SUPPORTED_VERSION:
        raise RuntimeError(
            f"Compatibility fixes require f5-tts {SUPPORTED_VERSION}, found {version}."
        )

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    package = site_packages / "f5_tts"
    utils_status = _replace_once(
        package / "infer" / "utils_infer.py",
        "    audio, sr = torchaudio.load(ref_audio)\n",
        (
            "    try:\n"
            "        audio, sr = torchaudio.load(ref_audio)\n"
            "    except Exception as exc:\n"
            "        print(f\"torchaudio.load failed ({exc}), falling back to soundfile...\")\n"
            "        import soundfile as sf\n"
            "\n"
            "        speech, sr = sf.read(ref_audio)\n"
            "        audio = torch.tensor(speech, dtype=torch.float32)\n"
            "        if len(audio.shape) == 1:\n"
            "            audio = audio.unsqueeze(0)\n"
            "        else:\n"
            "            audio = audio.T\n"
        ),
    )
    trainer_status = _replace_once(
        package / "model" / "__init__.py",
        "from f5_tts.model.trainer import Trainer\n",
        (
            "try:\n"
            "    from f5_tts.model.trainer import Trainer\n"
            "except Exception:\n"
            "    Trainer = None\n"
        ),
    )
    print(f"utils_infer.py: {utils_status}")
    print(f"model/__init__.py: {trainer_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
