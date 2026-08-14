"""Launch Grandpa's tracked voice service with the isolated runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import tomllib


def main() -> int:
    runtime_root = Path(__file__).resolve().parents[1]
    project_root = runtime_root.parent
    manifest_path = runtime_root / "references" / "reference.local.toml"
    if not manifest_path.is_file():
        raise RuntimeError("Missing references/reference.local.toml")
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    reference = (manifest_path.parent / str(manifest.get("audio", ""))).resolve()
    transcript = str(manifest.get("transcript", "")).strip()
    if not reference.is_file() or not transcript or transcript.startswith("REPLACE WITH"):
        raise RuntimeError("Reference audio and exact transcript must be configured.")

    cache = runtime_root / "models_or_cache" / "huggingface"
    hub_cache = cache / "hub"
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["GRANDPA_VOICE_MODEL_CACHE"] = str(hub_cache)
    os.environ["GRANDPA_VOICE_REFERENCE_AUDIO"] = str(reference)
    os.environ["GRANDPA_VOICE_REFERENCE_TEXT"] = transcript
    sys.path.insert(0, str(project_root / "src"))

    import uvicorn

    from grandpa.core.config import load_config
    from grandpa.voice_service.post_processing import CharacterVoiceSettings
    from grandpa.voice_service.service import VoiceServiceRuntime, create_app

    voice_config = load_config().grandpa_voice
    ffmpeg_path = _find_ffmpeg(runtime_root)
    runtime = VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text=transcript,
        nfe_step=voice_config.nfe_step,
        cpu_threads=voice_config.cpu_threads,
        cfg_strength=voice_config.cfg_strength,
        character_voice_settings=CharacterVoiceSettings(
            enabled=voice_config.character_voice,
            pitch_semitones=voice_config.pitch_semitones,
            speed=voice_config.character_speed,
            target_lufs=voice_config.target_lufs,
            true_peak_db=voice_config.true_peak_db,
            compression=voice_config.compression,
            eq_profile=voice_config.eq_profile,
        ),
        ffmpeg_path=ffmpeg_path,
    )
    uvicorn.run(create_app(runtime), host="127.0.0.1", port=8765)
    return 0


def _find_ffmpeg(runtime_root: Path) -> str:
    import shutil

    discovered = shutil.which("ffmpeg")
    if discovered:
        return discovered
    candidates = sorted((runtime_root / "tools").glob("ffmpeg-*/**/bin/ffmpeg.exe"))
    return str(candidates[-1]) if candidates else ""


if __name__ == "__main__":
    raise SystemExit(main())
