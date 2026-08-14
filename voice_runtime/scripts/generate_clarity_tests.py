"""Generate RAW, F (Clarity), and G (Presence) audio files from the exact same F5 synthesis."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import wave
from pathlib import Path

import tomllib

# Add src to python path so we can import grandpa code
runtime_root = Path(__file__).resolve().parents[1]
project_root = runtime_root.parent
sys.path.insert(0, str(project_root / "src"))

from grandpa.voice_service.post_processing import (
    CharacterVoiceSettings,
    FFmpegCharacterVoiceProcessor,
)


def _load_reference(runtime_root: Path) -> tuple[Path, str]:
    manifest_path = runtime_root / "references" / "reference.local.toml"
    if not manifest_path.is_file():
        raise RuntimeError("Missing references/reference.local.toml")
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    audio = (manifest_path.parent / str(manifest.get("audio", ""))).resolve()
    transcript = str(manifest.get("transcript", "")).strip()
    if not audio.is_file() or audio.suffix.lower() != ".wav":
        raise RuntimeError("Reference audio must be an existing WAV inside references/.")
    return audio, transcript


def _find_ffmpeg(runtime_root: Path) -> str:
    discovered = shutil.which("ffmpeg")
    if discovered:
        return discovered
    candidates = sorted((runtime_root / "tools").glob("ffmpeg-*/**/bin/ffmpeg.exe"))
    return str(candidates[-1]) if candidates else ""


def measure_audio(ffmpeg_path: str, wav_path: Path) -> dict[str, float]:
    """Measure duration, LUFS, and true peak using ffmpeg."""
    import subprocess
    # Run loudnorm measurement filter
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-i",
        str(wav_path),
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "NUL",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    stderr = completed.stderr
    
    # Parse json from stderr
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        return {"lufs": 0.0, "true_peak": 0.0, "duration": 0.0}
        
    try:
        raw = json.loads(stderr[start : end + 1])
        # Get duration using ffprobe or wave
        with wave.open(str(wav_path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            duration = frames / float(rate)
            
        return {
            "lufs": float(raw["input_i"]),
            "true_peak": float(raw["input_tp"]),
            "duration": duration,
        }
    except Exception:
        return {"lufs": 0.0, "true_peak": 0.0, "duration": 0.0}


def main():
    print("Initializing F5-TTS clarity test generation script...")
    
    reference, transcript = _load_reference(runtime_root)
    ffmpeg_path = _find_ffmpeg(runtime_root)
    if not ffmpeg_path:
        print("Error: FFmpeg path could not be resolved.")
        return 1

    cache = runtime_root / "models_or_cache" / "huggingface"
    hub_cache = cache / "hub"
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from f5_tts.api import F5TTS

    text = "Hello Hari. Grandpa is ready. Tell me what you need, and I will handle it carefully."
    raw_path = runtime_root / "outputs" / "f5_character_RAW.wav"
    f_path = runtime_root / "outputs" / "f5_character_F_clarity.wav"
    g_path = runtime_root / "outputs" / "f5_character_G_presence.wav"

    # Step 1: Check/Delete existing target files so we overwrite them cleanly
    for p in (raw_path, f_path, g_path):
        if p.exists():
            p.unlink()

    # Step 2: Run F5-TTS synthesis once
    print(f"Loading F5-TTS model (CPU)...")
    model_load_start = time.perf_counter()
    model = F5TTS(device="cpu", hf_cache_dir=str(hub_cache))
    model_load_time = time.perf_counter() - model_load_start
    print(f"Model loaded in {model_load_time:.2f} seconds.")

    print(f"Synthesizing test phrase: {text!r}")
    synth_start = time.perf_counter()
    wav, sample_rate, _spectrogram = model.infer(
        ref_file=str(reference),
        ref_text=transcript,
        gen_text=text,
        file_wave=str(raw_path),
        seed=42,
    )
    synth_time = time.perf_counter() - synth_start
    print(f"F5 Synthesis completed in {synth_time:.2f} seconds. Output saved to: {raw_path}")

    # Read synthesized raw bytes
    raw_bytes = raw_path.read_bytes()

    # Step 3: Profile F (Clarity) Processing
    print("\n--- Processing Profile F (Clarity) ---")
    settings_f = CharacterVoiceSettings(
        enabled=True,
        pitch_semitones=0.0,
        speed=1.0,
        target_lufs=-15.0,
        true_peak_db=-1.0,
        compression=True,
        eq_profile="grandpa_clarity",
    )
    processor_f = FFmpegCharacterVoiceProcessor(settings_f, ffmpeg_path=ffmpeg_path)
    
    proc_f_start = time.perf_counter()
    processed_f_bytes = processor_f.process(raw_bytes)
    proc_f_time = time.perf_counter() - proc_f_start
    f_path.write_bytes(processed_f_bytes)
    print(f"Profile F saved to: {f_path}")

    # Step 4: Profile G (Presence) Processing
    print("\n--- Processing Profile G (Presence) ---")
    settings_g = CharacterVoiceSettings(
        enabled=True,
        pitch_semitones=0.0,
        speed=1.0,
        target_lufs=-14.5,
        true_peak_db=-1.0,
        compression=True,
        eq_profile="grandpa_presence",
    )
    processor_g = FFmpegCharacterVoiceProcessor(settings_g, ffmpeg_path=ffmpeg_path)
    
    proc_g_start = time.perf_counter()
    processed_g_bytes = processor_g.process(raw_bytes)
    proc_g_time = time.perf_counter() - proc_g_start
    g_path.write_bytes(processed_g_bytes)
    print(f"Profile G saved to: {g_path}")

    # Step 5: Measurements and Reporting
    print("\n==================== MEASUREMENTS & REPORT ====================")
    raw_metrics = measure_audio(ffmpeg_path, raw_path)
    f_metrics = measure_audio(ffmpeg_path, f_path)
    g_metrics = measure_audio(ffmpeg_path, g_path)

    print(f"RAW Voice:")
    print(f"  Duration: {raw_metrics['duration']:.2f} seconds")
    print(f"  Loudness: {raw_metrics['lufs']:.2f} LUFS")
    print(f"  True Peak: {raw_metrics['true_peak']:.2f} dBTP")
    
    from grandpa.voice_service.post_processing import build_character_filters
    f_filters = build_character_filters(settings_f, sample_rate)
    g_filters = build_character_filters(settings_g, sample_rate)

    print(f"\nProfile F (Clarity):")
    print(f"  Exact filter chain: {','.join(f_filters)}")
    print(f"  Duration: {f_metrics['duration']:.2f} seconds")
    print(f"  Loudness: {f_metrics['lufs']:.2f} LUFS")
    print(f"  True Peak: {f_metrics['true_peak']:.2f} dBTP")
    print(f"  Clipping: {'Yes' if f_metrics['true_peak'] > 0.0 else 'No'}")
    print(f"  Processing time: {proc_f_time:.4f} seconds")

    print(f"\nProfile G (Presence):")
    print(f"  Exact filter chain: {','.join(g_filters)}")
    print(f"  Duration: {g_metrics['duration']:.2f} seconds")
    print(f"  Loudness: {g_metrics['lufs']:.2f} LUFS")
    print(f"  True Peak: {g_metrics['true_peak']:.2f} dBTP")
    print(f"  Clipping: {'Yes' if g_metrics['true_peak'] > 0.0 else 'No'}")
    print(f"  Processing time: {proc_g_time:.4f} seconds")
    print("==============================================================")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
