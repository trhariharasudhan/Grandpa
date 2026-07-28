"""Focused tests for the local-assistant configuration."""

from __future__ import annotations

from pathlib import Path

from grandpa.core.config import (
    GrandpaConfig,
    HardwareInfo,
    IntelligenceConfig,
    LearningConfig,
    SchedulerConfig,
    SecurityConfig,
    generate_default_toml,
    generate_minimal_toml,
    load_config,
    recommend_engine,
)


def test_defaults_are_local_and_safe() -> None:
    cfg = GrandpaConfig()

    assert cfg.engine.default == "ollama"
    assert cfg.memory.default_backend == "sqlite"
    assert cfg.security.enabled is True
    assert cfg.security.enforce_tool_confirmation is True


def test_recommend_engine_is_ollama() -> None:
    assert recommend_engine(HardwareInfo(platform="Windows", ram_gb=16)) == "ollama"


def test_intelligence_generation_defaults() -> None:
    cfg = IntelligenceConfig()

    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 1024
    assert cfg.provider == "local"


def test_learning_is_limited_to_runtime_routing() -> None:
    cfg = LearningConfig()

    assert cfg.enabled is True
    assert cfg.routing.policy == "heuristic"
    assert cfg.default_policy == "heuristic"


def test_learning_policy_compatibility_alias() -> None:
    cfg = LearningConfig()
    cfg.default_policy = "learned"

    assert cfg.routing.policy == "learned"


def test_security_defaults() -> None:
    cfg = SecurityConfig()

    assert cfg.scan_input is True
    assert cfg.scan_output is True
    assert cfg.mode == "redact"


def test_scheduler_defaults() -> None:
    cfg = SchedulerConfig()

    assert cfg.enabled is False
    assert cfg.poll_interval == 60


def test_loads_supported_sections(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[engine]
default = "ollama"

[engine.ollama]
host = "http://127.0.0.1:11434"

[intelligence]
default_model = "grandpa-fast:latest"

[learning.routing]
policy = "learned"

[scheduler]
enabled = true
poll_interval = 15
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.engine.ollama.host == "http://127.0.0.1:11434"
    assert cfg.intelligence.default_model == "grandpa-fast:latest"
    assert cfg.learning.routing.policy == "learned"
    assert cfg.scheduler.enabled is True
    assert cfg.scheduler.poll_interval == 15


def test_default_toml_only_advertises_ollama() -> None:
    rendered = generate_default_toml(HardwareInfo(ram_gb=16))

    assert '[engine]\ndefault = "ollama"' in rendered
    assert "[engine.ollama]" in rendered
    assert "[engine.vllm]" not in rendered
    assert "[channels" not in rendered
    assert "[sandbox" not in rendered
    assert "[mining" not in rendered


def test_minimal_toml_uses_requested_loopback_host() -> None:
    rendered = generate_minimal_toml(
        HardwareInfo(ram_gb=16),
        engine="ollama",
        host="http://127.0.0.1:11434",
    )

    assert 'default = "ollama"' in rendered
    assert 'host = "http://127.0.0.1:11434"' in rendered
