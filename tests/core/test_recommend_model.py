"""Tests for local Ollama model recommendations."""

from __future__ import annotations

from grandpa.core.config import GpuInfo, HardwareInfo, recommend_model


def test_8gb_ram_uses_small_tier() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=8.0, gpu=None)
    assert recommend_model(hw, "ollama") == "grandpa-mini:latest"


def test_16gb_ram_uses_4b_tier() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=16.0, gpu=None)
    assert recommend_model(hw, "ollama") == "grandpa-mini:latest"


def test_32gb_ram_uses_9b_tier() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=32.0, gpu=None)
    assert recommend_model(hw, "ollama") == "grandpa-mini:latest"


def test_gpu_memory_drives_recommendation() -> None:
    hw = HardwareInfo(
        platform="win32",
        ram_gb=64.0,
        gpu=GpuInfo(vendor="nvidia", name="RTX 4090", vram_gb=24.0, count=1),
    )
    assert recommend_model(hw, "ollama") == "grandpa-mini:latest"


def test_unsupported_engine_has_no_recommendation() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=16.0, gpu=None)
    assert recommend_model(hw, "vllm") == ""


def test_no_usable_memory_has_no_recommendation() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=4.0, gpu=None)
    assert recommend_model(hw, "ollama") == ""
