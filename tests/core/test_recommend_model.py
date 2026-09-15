"""Tests for local Ollama model recommendations.

These used to assert ``grandpa-mini:latest`` for every tier while being *named*
after tiers -- "uses_4b_tier", "uses_9b_tier" -- that the function never
actually selected. It returned one constant regardless of hardware.

It tiers for real now, because the default model has to be one that can call
the action layer's tools and that model needs memory a small machine does not
have. Usable memory is GPU VRAM when present, otherwise ``(RAM - 4) * 0.8``.
"""

from __future__ import annotations

from grandpa.core.config import GpuInfo, HardwareInfo, recommend_model
from grandpa.intelligence.grandpa_models import (
    DEFAULT_MODEL_TAG,
    SMALL_MACHINE_MODEL_TAG,
)


def test_8gb_ram_gets_the_small_machine_model() -> None:
    """(8 - 4) * 0.8 = 3.2 GB usable, below the default's 6 GB floor."""
    hw = HardwareInfo(platform="win32", ram_gb=8.0, gpu=None)

    assert recommend_model(hw, "ollama") == SMALL_MACHINE_MODEL_TAG


def test_16gb_ram_gets_the_default() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=16.0, gpu=None)

    assert recommend_model(hw, "ollama") == DEFAULT_MODEL_TAG


def test_32gb_ram_gets_the_default() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=32.0, gpu=None)

    assert recommend_model(hw, "ollama") == DEFAULT_MODEL_TAG


def test_gpu_memory_drives_recommendation() -> None:
    """A 24 GB card beats the RAM calculation, so the default applies."""
    hw = HardwareInfo(
        platform="win32",
        ram_gb=64.0,
        gpu=GpuInfo(vendor="nvidia", name="RTX 4090", vram_gb=24.0, count=1),
    )

    assert recommend_model(hw, "ollama") == DEFAULT_MODEL_TAG


def test_a_small_gpu_still_gets_the_small_machine_model() -> None:
    """VRAM is used when a GPU is present, so a 4 GB card does not get the
    default even on a machine with plenty of RAM."""
    hw = HardwareInfo(
        platform="win32",
        ram_gb=64.0,
        gpu=GpuInfo(vendor="nvidia", name="GTX 1650", vram_gb=4.0, count=1),
    )

    assert recommend_model(hw, "ollama") == SMALL_MACHINE_MODEL_TAG


def test_the_two_tiers_are_different_models() -> None:
    """A tiering function that returns one constant is not tiering."""
    assert DEFAULT_MODEL_TAG != SMALL_MACHINE_MODEL_TAG


def test_unsupported_engine_has_no_recommendation() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=16.0, gpu=None)

    assert recommend_model(hw, "vllm") == ""


def test_no_usable_memory_has_no_recommendation() -> None:
    hw = HardwareInfo(platform="win32", ram_gb=4.0, gpu=None)

    assert recommend_model(hw, "ollama") == ""
