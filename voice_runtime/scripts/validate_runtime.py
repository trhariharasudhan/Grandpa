"""Validate the isolated runtime without importing or loading the F5 model."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

EXPECTED = {
    "f5-tts": "1.1.22",
    "torch": "2.13.0",
    "torchaudio": "2.11.0",
    "soundfile": "0.14.0",
}


def main() -> int:
    if Path(sys.prefix).resolve() != (Path(__file__).parents[1] / ".venv").resolve():
        raise RuntimeError("Validation must run with voice_runtime/.venv Python.")
    for package, expected in EXPECTED.items():
        actual = importlib.metadata.version(package)
        if actual != expected:
            raise RuntimeError(f"{package}: expected {expected}, found {actual}")
        print(f"{package}={actual}")
    print("device=cpu")
    print("runtime_validation=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
