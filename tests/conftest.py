"""Shared fixtures — clear all registries and the event bus between tests."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import grandpa.core.config as _config
from grandpa.core.config import GpuInfo, HardwareInfo
from grandpa.core.events import EventBus, reset_event_bus
from grandpa.core.registry import (
    AgentRegistry,
    BenchmarkRegistry,
    ChannelRegistry,
    CompressionRegistry,
    ConnectorRegistry,
    EngineRegistry,
    MemoryRegistry,
    MinerRegistry,
    ModelRegistry,
    RouterPolicyRegistry,
    SkillRegistry,
    SpeechRegistry,
    ToolRegistry,
    TTSRegistry,
)

_TEST_HOME = Path(os.environ.get("GRANDPA_TEST_HOME", Path.cwd() / "runtime" / "test-home"))
_TEST_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("GRANDPA_HOME", str(_TEST_HOME))
_config.DEFAULT_CONFIG_DIR = _TEST_HOME
_config.DEFAULT_CONFIG_PATH = _TEST_HOME / "config.toml"

_OPTIONAL_ENVIRONMENT_TESTS = {
    "tests/connectors/test_live_smoke.py": (
        "GRANDPA_RUN_LIVE_CONNECTOR_TESTS",
        "live connector smoke test; set GRANDPA_RUN_LIVE_CONNECTOR_TESTS=1 to run",
    ),
    "tests/connectors/test_new_connectors_live.py": (
        "GRANDPA_RUN_LIVE_CONNECTOR_TESTS",
        "live connector credentials/network test; set GRANDPA_RUN_LIVE_CONNECTOR_TESTS=1 to run",
    ),
    "tests/evals/comparison/test_openclaw_runner_contract.py": (
        "GRANDPA_RUN_EXTERNAL_RUNNER_TESTS",
        "external OpenClaw runner contract requires a working Node runtime outside sandbox constraints",
    ),
    "tests/evals/comparison/test_hermes_runner_contract.py": (
        "GRANDPA_RUN_EXTERNAL_RUNNER_TESTS",
        "external Hermes runner contract requires a working Node runtime outside sandbox constraints",
    ),
    "tests/evals/datasets/test_external_agent_datasets.py": (
        "GRANDPA_RUN_EXTERNAL_RUNNER_TESTS",
        "external agent dataset tests require foreign framework fixtures",
    ),
    "tests/skills/test_integration_live.py": (
        "GRANDPA_RUN_LIVE_SKILL_TESTS",
        "live skill integration tests require a running inference engine and installed user skills",
    ),
}
_RUST_EXTENSION_AVAILABLE = importlib.util.find_spec("grandpa_rust") is not None
_RELEASE_TEST_PATHS = {
    "tests/test_actions_decomposition.py",
    "tests/test_autonomous_workflows.py",
    "tests/test_browser_control.py",
    "tests/test_desktop_control_services.py",
    "tests/test_intent_router.py",
    "tests/test_local_actions.py",
    "tests/test_native_agent_planner.py",
    "tests/test_pc_control.py",
    "tests/test_pc_control_api.py",
    "tests/test_pc_control_kernel.py",
    "tests/test_plugin_runtime.py",
    "tests/test_release_gate.py",
    "tests/test_services_layer.py",
    "tests/test_skill_runtime.py",
    "tests/test_visual_targeting.py",
    "tests/test_workflow_skill_graph.py",
    "tests/server/test_routes.py",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Classify optional/environment suites and keep default full runs local."""
    for item in items:
        rel_path = item.path.as_posix()
        if rel_path.startswith(str(Path.cwd()).replace("\\", "/")):
            rel_path = Path(rel_path).relative_to(Path.cwd()).as_posix()
        optional_rule = _OPTIONAL_ENVIRONMENT_TESTS.get(rel_path)
        if optional_rule:
            env_var, reason = optional_rule
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.optional)
            item.add_marker(pytest.mark.environment)
            if os.environ.get(env_var) != "1":
                item.add_marker(pytest.mark.skip(reason=reason))
        if rel_path == "tests/core/test_rust_bridge.py" and (
            "TestGetRustModule" in item.nodeid or "TestRustBackedModules" in item.nodeid
        ):
            item.add_marker(pytest.mark.optional)
            item.add_marker(pytest.mark.environment)
            if not _RUST_EXTENSION_AVAILABLE:
                item.add_marker(pytest.mark.skip(reason="grandpa_rust extension is not built"))
        if rel_path == "tests/core/test_credentials.py" and item.name == "test_file_permissions":
            item.add_marker(pytest.mark.environment)
            if os.name == "nt":
                item.add_marker(
                    pytest.mark.skip(reason="POSIX chmod mode assertions are not reliable on Windows")
                )
        if rel_path == "tests/telemetry/test_energy_rapl.py":
            item.add_marker(pytest.mark.environment)
            if os.name == "nt":
                item.add_marker(
                    pytest.mark.skip(reason="Linux RAPL sysfs paths cannot be represented on Windows")
                )
        if rel_path == "tests/engine/test_gemma_cpp.py" and "TestGemmaCppLive" in item.nodeid:
            item.add_marker(pytest.mark.live)
            item.add_marker(pytest.mark.optional)
            item.add_marker(pytest.mark.environment)
            if os.environ.get("GEMMA_CPP_MODEL_PATH") is None:
                item.add_marker(
                    pytest.mark.skip(reason="gemma.cpp live tests require GEMMA_CPP_MODEL_PATH")
                )
        if rel_path == "tests/evals/test_dataset_splits_integration.py":
            remote_dataset_params = (
                "grandpa.evals.datasets.gaia",
                "grandpa.evals.datasets.liveresearchbench",
                "grandpa.evals.datasets.taubench",
                "grandpa.evals.datasets.livecodebench",
            )
            if any(param in item.nodeid for param in remote_dataset_params):
                item.add_marker(pytest.mark.optional)
                item.add_marker(pytest.mark.environment)
                item.add_marker(pytest.mark.slow)
            if os.environ.get("GRANDPA_RUN_HF_DATASET_TESTS") != "1":
                item.add_marker(
                    pytest.mark.skip(
                        reason="remote/gated dataset split test; set GRANDPA_RUN_HF_DATASET_TESTS=1 to run"
                    )
                )
        if rel_path in _RELEASE_TEST_PATHS:
            item.add_marker(pytest.mark.release)
        marker_names = {marker.name for marker in item.iter_markers()}
        if not marker_names.intersection(
            {"optional", "environment", "slow", "live", "live_channel", "live_external"}
        ):
            item.add_marker(pytest.mark.core)


@pytest.fixture(autouse=True)
def _clean_registries() -> None:
    """Ensure each test starts with empty registries and a fresh event bus."""
    ModelRegistry.clear()
    EngineRegistry.clear()
    MemoryRegistry.clear()
    MinerRegistry.clear()
    AgentRegistry.clear()
    ToolRegistry.clear()
    RouterPolicyRegistry.clear()
    BenchmarkRegistry.clear()
    ChannelRegistry.clear()
    SpeechRegistry.clear()
    CompressionRegistry.clear()
    ConnectorRegistry.clear()
    TTSRegistry.clear()
    SkillRegistry.clear()
    reset_event_bus()


# ---------------------------------------------------------------------------
# Hardware fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nvidia_gpu() -> GpuInfo:
    """NVIDIA A100 GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA A100-SXM4-80GB", vram_gb=80.0, count=1)


@pytest.fixture
def nvidia_consumer_gpu() -> GpuInfo:
    """NVIDIA consumer GPU fixture."""
    return GpuInfo(
        vendor="nvidia",
        name="NVIDIA GeForce RTX 4090",
        vram_gb=24.0,
        count=1,
    )


@pytest.fixture
def nvidia_multi_gpu() -> GpuInfo:
    """NVIDIA multi-GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA H100", vram_gb=80.0, count=4)


@pytest.fixture
def amd_gpu() -> GpuInfo:
    """AMD MI300X GPU fixture."""
    return GpuInfo(vendor="amd", name="AMD Instinct MI300X", vram_gb=192.0, count=1)


@pytest.fixture
def apple_gpu() -> GpuInfo:
    """Apple Silicon GPU fixture."""
    return GpuInfo(vendor="apple", name="Apple M4 Max", vram_gb=128.0, count=1)


@pytest.fixture
def hardware_nvidia(nvidia_gpu: GpuInfo) -> HardwareInfo:
    """Full NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 7763",
        cpu_count=64,
        ram_gb=512.0,
        gpu=nvidia_gpu,
    )


@pytest.fixture
def hardware_nvidia_consumer(nvidia_consumer_gpu: GpuInfo) -> HardwareInfo:
    """Consumer NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Core i9-14900K",
        cpu_count=24,
        ram_gb=64.0,
        gpu=nvidia_consumer_gpu,
    )


@pytest.fixture
def hardware_amd(amd_gpu: GpuInfo) -> HardwareInfo:
    """Full AMD hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 9654",
        cpu_count=96,
        ram_gb=768.0,
        gpu=amd_gpu,
    )


@pytest.fixture
def hardware_apple(apple_gpu: GpuInfo) -> HardwareInfo:
    """Apple Silicon hardware profile."""
    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M4 Max",
        cpu_count=16,
        ram_gb=128.0,
        gpu=apple_gpu,
    )


@pytest.fixture
def hardware_cpu_only() -> HardwareInfo:
    """CPU-only hardware profile (no GPU)."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Xeon E5-2686 v4",
        cpu_count=8,
        ram_gb=32.0,
        gpu=None,
    )


# ---------------------------------------------------------------------------
# Engine availability fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_ollama() -> bool:
    """Check if Ollama is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_vllm() -> bool:
    """Check if vLLM is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8000/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_llamacpp() -> bool:
    """Check if llama.cpp server is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8080/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cloud API key fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_openai_key() -> bool:
    """Check if OPENAI_API_KEY is set."""
    return bool(os.environ.get("OPENAI_API_KEY"))


@pytest.fixture
def has_anthropic_key() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def has_gemini_key() -> bool:
    """Check if GEMINI_API_KEY or GOOGLE_API_KEY is set."""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


# ---------------------------------------------------------------------------
# Mock engine factory
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """Factory for mock InferenceEngine instances."""

    def _factory(
        engine_id: str = "mock",
        model_response: str = "Hello!",
        tool_calls: list | None = None,
        models: list[str] | None = None,
    ) -> MagicMock:
        engine = MagicMock()
        engine.engine_id = engine_id
        engine.health.return_value = True
        engine.list_models.return_value = models or ["test-model"]

        result = {
            "content": model_response,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
            "finish_reason": "stop",
        }
        if tool_calls:
            result["tool_calls"] = tool_calls
            result["finish_reason"] = "tool_calls"
        engine.generate.return_value = result
        return engine

    return _factory


@pytest.fixture
def event_bus() -> EventBus:
    """Fresh EventBus with history recording enabled."""
    return EventBus(record_history=True)


# ---------------------------------------------------------------------------
# Mining sidecar fixtures (shared across tests/mining/ and tests/engine/)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_sidecar_payload() -> dict:
    """A valid vllm-pearl sidecar payload with all expected fields."""
    return {
        "provider": "vllm-pearl",
        "vllm_endpoint": "http://127.0.0.1:8000/v1",
        "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
        "gateway_url": "http://127.0.0.1:8337",
        "gateway_metrics_url": "http://127.0.0.1:8339",
        "container_id": "abc123def456",
        "wallet_address": "prl1qexampleaddress",
        "started_at": 1714867200,
    }


@pytest.fixture
def sidecar_path(tmp_path: Path) -> Path:
    """Path to a (not-yet-written) mining sidecar JSON file."""
    return tmp_path / "mining.json"


@pytest.fixture
def written_sidecar(sidecar_path: Path, sample_sidecar_payload: dict) -> Path:
    """A written mining sidecar JSON file; returns the path."""
    sidecar_path.write_text(json.dumps(sample_sidecar_payload))
    return sidecar_path
