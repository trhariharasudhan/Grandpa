"""Run F5-TTS quality and speed benchmarks sequentially for configs A, B, C, D, and E."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import wave
from pathlib import Path

import psutil
import tomllib
import torch

# Add src to python path so we can import grandpa code
runtime_root = Path(__file__).resolve().parents[1]
project_root = runtime_root.parent
sys.path.insert(0, str(project_root / "src"))

from grandpa.voice_service.post_processing import (
    CharacterVoiceSettings,
    FFmpegCharacterVoiceProcessor,
)


class MemoryTracker(threading.Thread):
    def __init__(self, pid: int):
        super().__init__()
        self.pid = pid
        self.peak_rss = 0
        self.stop_requested = threading.Event()

    def run(self):
        try:
            p = psutil.Process(self.pid)
            while not self.stop_requested.is_set():
                try:
                    rss = p.memory_info().rss
                    if rss > self.peak_rss:
                        self.peak_rss = rss
                except Exception:
                    pass
                time.sleep(0.1)
        except Exception:
            pass


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
    
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        return {"lufs": 0.0, "true_peak": 0.0, "duration": 0.0}
        
    try:
        raw = json.loads(stderr[start : end + 1])
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


def check_system_ram(min_required_gib: float = 3.5, include_own_process: bool = False) -> float:
    """Return available system RAM in GiB and assert threshold."""
    available_bytes = psutil.virtual_memory().available
    if include_own_process:
        available_bytes += psutil.Process().memory_info().rss
    available_gib = available_bytes / (1024 ** 3)
    if available_gib < min_required_gib:
        print(f"Safety Halt: Available system RAM is {available_gib:.2f} GiB (minimum required: {min_required_gib} GiB).")
        raise RuntimeError(f"Insufficient system RAM: {available_gib:.2f} GiB available.")
    return available_gib


def main():
    print("Initializing F5-TTS quality and latency benchmarking script...")
    
    # 1. Verification of resources
    reference, transcript = _load_reference(runtime_root)
    ffmpeg_path = _find_ffmpeg(runtime_root)
    if not ffmpeg_path:
        print("Error: FFmpeg path could not be resolved.")
        return 1

    # 2. Check safety system RAM
    initial_ram = check_system_ram()
    print(f"Safety verification passed. Initial available RAM: {initial_ram:.2f} GiB.")

    # 3. Environment configuration
    cache = runtime_root / "models_or_cache" / "huggingface"
    hub_cache = cache / "hub"
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # Set threads to 4 prior to loading/synthesis
    torch.set_num_threads(4)

    # 4. Load F5-TTS
    from f5_tts.api import F5TTS
    print("Loading F5-TTS model (CPU)...")
    model = F5TTS(device="cpu", hf_cache_dir=str(hub_cache))
    print("Model loaded successfully.")

    # Test phrase
    text = "Hello Hari. Grandpa is online and ready to help you. Your system is running normally, the internet connection is stable, and I am waiting for your next command."

    # Configs definition
    configs = [
        {"name": "A", "nfe": 16, "cfg": 2.0, "filename": "grandpa_quality_A_nfe16_cfg2.wav"},
        {"name": "B", "nfe": 16, "cfg": 1.5, "filename": "grandpa_quality_B_nfe16_cfg15.wav"},
        {"name": "C", "nfe": 12, "cfg": 1.5, "filename": "grandpa_quality_C_nfe12_cfg15.wav"},
        {"name": "D", "nfe": 12, "cfg": 1.0, "filename": "grandpa_quality_D_nfe12_cfg1.wav"},
        {"name": "E", "nfe": 8,  "cfg": 1.0, "filename": "grandpa_quality_E_nfe8_cfg1.wav"},
    ]

    results = []

    # Unchanged Grandpa Presence Postprocessing Config
    settings_g = CharacterVoiceSettings(
        enabled=True,
        pitch_semitones=0.0,
        speed=1.0,
        target_lufs=-14.5,
        true_peak_db=-1.0,
        compression=True,
        eq_profile="grandpa_presence",
    )
    processor = FFmpegCharacterVoiceProcessor(settings_g, ffmpeg_path=ffmpeg_path)

    for config in configs:
        print(f"\n=================== RUNNING CONFIG {config['name']} ===================")
        # RAM Safety check
        min_avail_ram = check_system_ram(include_own_process=True)
        print(f"Available system RAM (including model memory): {min_avail_ram:.2f} GiB. Starting synthesis...")

        # Setup paths
        raw_output_path = runtime_root / "outputs" / f"{config['filename'].replace('.wav', '_raw.wav')}"
        proc_output_path = runtime_root / "outputs" / config["filename"]

        if raw_output_path.exists():
            raw_output_path.unlink()
        if proc_output_path.exists():
            proc_output_path.unlink()

        # Track memory and runtime
        pid = os.getpid()
        tracker = MemoryTracker(pid)
        tracker.start()

        synth_start = time.perf_counter()
        
        # CPU synthesis run
        _wav, sample_rate, _spectrogram = model.infer(
            ref_file=str(reference),
            ref_text=transcript,
            gen_text=text,
            file_wave=str(raw_output_path),
            nfe_step=config["nfe"],
            cfg_strength=config["cfg"],
            seed=42,
        )
        
        synth_time = time.perf_counter() - synth_start

        # Stop memory tracker
        tracker.stop_requested.set()
        tracker.join()

        peak_process_ram_gib = tracker.peak_rss / (1024 ** 3)
        print(f"Synthesis completed in {synth_time:.2f} seconds. Peak process RAM: {peak_process_ram_gib:.2f} GiB.")

        # Post processing
        print("Applying grandpa_presence character processing...")
        proc_start = time.perf_counter()
        raw_bytes = raw_output_path.read_bytes()
        processed_bytes = processor.process(raw_bytes)
        proc_time = time.perf_counter() - proc_start
        proc_output_path.write_bytes(processed_bytes)
        print(f"Processed audio saved to: {proc_output_path}")

        # Metrics measurement
        metrics = measure_audio(ffmpeg_path, proc_output_path)
        rtf = synth_time / metrics["duration"] if metrics["duration"] > 0 else 0.0
        
        results.append({
            "config": config["name"],
            "nfe": config["nfe"],
            "cfg": config["cfg"],
            "threads": 4,
            "seed": 42,
            "synth_seconds": synth_time,
            "duration": metrics["duration"],
            "rtf": rtf,
            "peak_process_ram": peak_process_ram_gib,
            "min_avail_ram": min_avail_ram,
            "post_processing_seconds": proc_time,
            "lufs": metrics["lufs"],
            "true_peak": metrics["true_peak"],
            "clipping": "Yes" if metrics["true_peak"] > 0.0 else "No",
            "output_path": str(proc_output_path),
            "raw_path": str(raw_output_path)
        })

    # 5. Output Report
    print("\n\n==============================================================")
    print("                     BENCHMARK COMPLETE                       ")
    print("==============================================================")
    for res in results:
        print(f"Config {res['config']} (NFE={res['nfe']}, CFG={res['cfg']}):")
        print(f"  Synthesis time: {res['synth_seconds']:.2f} seconds")
        print(f"  Audio duration: {res['duration']:.2f} seconds (RTF: {res['rtf']:.3f})")
        print(f"  Peak process RAM: {res['peak_process_ram']:.2f} GiB | Min System RAM available: {res['min_avail_ram']:.2f} GiB")
        print(f"  Loudness: {res['lufs']:.2f} LUFS | True Peak: {res['true_peak']:.2f} dBTP (Clipping: {res['clipping']})")
        print(f"  Post-processing time: {res['post_processing_seconds']:.4f} seconds")
        print(f"  Output path: {res['output_path']}")
        print(f"  RAW path: {res['raw_path']}")
        print("--------------------------------------------------------------")

    # Write a markdown report file for Hari
    report_md = runtime_root / "outputs" / "quality_benchmarks_report.md"
    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# F5-TTS Latency & Quality Optimization Report\n\n")
        f.write("This report benchmarks different parameter settings of F5-TTS to optimize CPU inference latency while maintaining the approved speech quality.\n\n")
        f.write("## Benchmark Settings\n")
        f.write(f"- **Test Phrase:** {text!r}\n")
        f.write("- **Post-processing EQ Profile:** `grandpa_presence`\n")
        f.write("- **CPU Threads:** 4\n")
        f.write("- **Deterministic Seed:** 42\n\n")
        
        f.write("## Performance Metrics Table\n\n")
        f.write("| Config | NFE | CFG | Synthesis Time (s) | Audio Duration (s) | RTF | Peak Process RAM (GiB) | Min Avail RAM (GiB) | Post-Proc Time (s) | Loudness (LUFS) | True Peak (dBTP) | Clipping |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for res in results:
            f.write(
                f"| {res['config']} | {res['nfe']} | {res['cfg']} | {res['synth_seconds']:.2f} | {res['duration']:.2f} | {res['rtf']:.3f} | "
                f"{res['peak_process_ram']:.2f} | {res['min_avail_ram']:.2f} | {res['post_processing_seconds']:.4f} | {res['lufs']:.2f} | "
                f"{res['true_peak']:.2f} | {res['clipping']} |\n"
            )
            
        f.write("\n## Outputs Generated\n\n")
        for res in results:
            f.write(f"### Configuration {res['config']}\n")
            f.write(f"- **Processed WAV:** [{Path(res['output_path']).name}](file:///{res['output_path'].replace(os.sep, '/')})\n")
            f.write(f"- **RAW Diagnostic WAV:** [{Path(res['raw_path']).name}](file:///{res['raw_path'].replace(os.sep, '/')})\n\n")

    print(f"\nMarkdown report written to: {report_md}")


if __name__ == "__main__":
    main()
