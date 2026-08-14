"""Run one direct, non-overwriting F5-TTS synthesis in the isolated runtime."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import tomllib


def _load_reference(runtime_root: Path) -> tuple[Path, str]:
    manifest_path = runtime_root / "references" / "reference.local.toml"
    if not manifest_path.is_file():
        raise RuntimeError(
            "Missing references/reference.local.toml; copy the example and add the exact transcript."
        )
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    audio = (manifest_path.parent / str(manifest.get("audio", ""))).resolve()
    transcript = str(manifest.get("transcript", "")).strip()
    if not audio.is_file() or audio.suffix.lower() != ".wav":
        raise RuntimeError("Reference audio must be an existing WAV inside references/.")
    if not transcript or transcript.startswith("REPLACE WITH"):
        raise RuntimeError("The exact reference transcript has not been configured.")
    if manifest_path.parent.resolve() not in audio.parents:
        raise RuntimeError("Reference audio must remain inside voice_runtime/references/.")
    return audio, transcript


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    runtime_root = Path(__file__).resolve().parents[1]
    expected_python = (runtime_root / ".venv" / "Scripts" / "python.exe").resolve()
    if Path(sys.executable).resolve() != expected_python:
        raise RuntimeError("Synthesis must use voice_runtime/.venv Python.")

    output = args.output.resolve()
    output_root = (runtime_root / "outputs").resolve()
    if output_root not in output.parents or output.suffix.lower() != ".wav":
        raise RuntimeError("Output must be a WAV inside voice_runtime/outputs/.")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")

    reference, transcript = _load_reference(runtime_root)
    cache = runtime_root / "models_or_cache" / "huggingface"
    hub_cache = cache / "hub"
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from f5_tts.api import F5TTS

    load_started = time.perf_counter()
    model = F5TTS(device="cpu", hf_cache_dir=str(hub_cache))
    load_seconds = time.perf_counter() - load_started

    synthesis_started = time.perf_counter()
    _wav, sample_rate, _spectrogram = model.infer(
        ref_file=str(reference),
        ref_text=transcript,
        gen_text=args.text.strip(),
        file_wave=str(output),
        seed=42,
    )
    synthesis_seconds = time.perf_counter() - synthesis_started
    print(f"output={output}")
    print(f"sample_rate={sample_rate}")
    print(f"model_load_seconds={load_seconds:.3f}")
    print(f"synthesis_seconds={synthesis_seconds:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
