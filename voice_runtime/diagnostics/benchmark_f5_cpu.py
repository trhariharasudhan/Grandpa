"""Bounded F5 CPU benchmark; does not alter Grandpa runtime configuration."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import psutil
import soundfile as sf
import torch
from f5_tts.api import F5TTS

REFERENCE = Path(r"D:\Grandpa\voice_runtime\references\hari_reference.wav")
OUTPUT_DIR = Path(r"D:\Grandpa\voice_runtime\outputs\f5_cpu_benchmarks")
REPORT = Path(r"D:\Grandpa\voice_runtime\diagnostics\f5_cpu_benchmark.json")
REFERENCE_TEXT = (
    "Command received, processing request now, file operation completed "
    "successfully, internet connection is stable and operational."
)
GEN_TEXT = "Hello Hari, Grandpa is ready."
RUNS = (
    {"nfe": 16, "threads": 2, "cfg": 2.0},
    {"nfe": 8, "threads": 4, "cfg": 0.0},
    {"nfe": 4, "threads": 8, "cfg": 0.0},
)
SEED = 20260812


class MemoryMonitor:
    def __init__(self) -> None:
        self.minimum_available = psutil.virtual_memory().available
        self.peak_process_tree = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        root = psutil.Process()
        while not self._stop.wait(0.25):
            self.minimum_available = min(
                self.minimum_available, psutil.virtual_memory().available
            )
            processes = [root, *root.children(recursive=True)]
            working_set = 0
            for process in processes:
                try:
                    working_set += process.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self.peak_process_tree = max(self.peak_process_tree, working_set)

    def __enter__(self) -> MemoryMonitor:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "text": GEN_TEXT,
        "reference": str(REFERENCE),
        "seed": SEED,
        "torch": torch.__version__,
        "cpu_count": os.cpu_count(),
        "baseline": {
            "nfe": 32,
            "threads": 4,
            "cfg": 2.0,
            "total_seconds": 441.891,
            "audio_seconds": 1.514667,
        },
        "runs": [],
    }

    torch.set_num_interop_threads(4)
    load_started = time.perf_counter()
    engine = F5TTS(model="F5TTS_v1_Base", device="cpu", hf_cache_dir=os.environ.get("HF_HOME"))
    report["model_and_vocoder_load_seconds"] = time.perf_counter() - load_started

    sample_timing: list[float] = []
    vocoder_timing: list[float] = []
    original_sample = engine.ema_model.sample
    original_decode = engine.vocoder.decode

    def timed_sample(*args: object, **kwargs: object):
        started = time.perf_counter()
        try:
            return original_sample(*args, **kwargs)
        finally:
            sample_timing.append(time.perf_counter() - started)

    def timed_decode(*args: object, **kwargs: object):
        started = time.perf_counter()
        try:
            return original_decode(*args, **kwargs)
        finally:
            vocoder_timing.append(time.perf_counter() - started)

    engine.ema_model.sample = timed_sample
    engine.vocoder.decode = timed_decode

    for settings in RUNS:
        torch.set_num_threads(settings["threads"])
        sample_timing.clear()
        vocoder_timing.clear()
        output = OUTPUT_DIR / (
            f"hari_nfe{settings['nfe']}_threads{settings['threads']}_cfg{settings['cfg']:.0f}.wav"
        )
        initial_available = psutil.virtual_memory().available
        started = time.perf_counter()
        with MemoryMonitor() as memory:
            engine.infer(
                ref_file=str(REFERENCE),
                ref_text=REFERENCE_TEXT,
                gen_text=GEN_TEXT,
                nfe_step=settings["nfe"],
                cfg_strength=settings["cfg"],
                file_wave=str(output),
                seed=SEED,
            )
        total_seconds = time.perf_counter() - started
        audio_info = sf.info(output)
        run = {
            **settings,
            "total_seconds": total_seconds,
            "model_sample_seconds": sum(sample_timing),
            "vocos_decode_seconds": sum(vocoder_timing),
            "other_seconds": total_seconds - sum(sample_timing) - sum(vocoder_timing),
            "audio_seconds": audio_info.duration,
            "rtf": total_seconds / audio_info.duration,
            "initial_available_gib": initial_available / 1024**3,
            "minimum_available_gib": memory.minimum_available / 1024**3,
            "peak_process_tree_gib": memory.peak_process_tree / 1024**3,
            "output": str(output),
            "sample_rate": audio_info.samplerate,
            "channels": audio_info.channels,
        }
        report["runs"].append(run)
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(run, indent=2), flush=True)


if __name__ == "__main__":
    main()
