"""Focused tests for the local-assistant configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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
    validate_ollama_num_ctx,
)


def test_defaults_are_local_and_safe() -> None:
    cfg = GrandpaConfig()

    assert cfg.engine.default == "ollama"
    assert cfg.memory.default_backend == "sqlite"
    assert cfg.security.enabled is True
    assert cfg.engine.ollama.num_ctx == 8192


def test_loads_ollama_context_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[engine.ollama]\nnum_ctx = 1024\n", encoding="utf-8")

    assert load_config(config_path).engine.ollama.num_ctx == 1024


def test_invalid_ollama_context_in_toml_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[engine.ollama]\nnum_ctx = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="engine.ollama.num_ctx"):
        load_config(config_path)


@pytest.mark.parametrize("value", (0, -1, 255, 262_145, True, "1024"))
def test_rejects_invalid_ollama_context(value: object) -> None:
    with pytest.raises(ValueError, match="engine.ollama.num_ctx"):
        validate_ollama_num_ctx(value)


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


def test_removed_config_keys_are_not_fields() -> None:
    """Inert options were removed, not left looking configurable."""
    from grandpa.core.config import REMOVED_CONFIG_KEYS, GrandpaConfig

    cfg = GrandpaConfig()
    for dotted in REMOVED_CONFIG_KEYS:
        section, _, key = dotted.partition(".")
        assert not hasattr(getattr(cfg, section), key), dotted


def test_removed_config_key_in_toml_warns_instead_of_silently_dropping(
    tmp_path: Path, monkeypatch
) -> None:
    """_apply_toml_section ignores unknown keys, so removal needs a warning."""
    import grandpa.core.config as config_module
    from grandpa.core.config import consume_config_recovery_warnings, load_config

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[security]\nenabled = true\nrate_limit_rpm = 120\n", encoding="utf-8"
    )
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_DIR", tmp_path)

    consume_config_recovery_warnings()  # clear anything pending
    cfg = load_config()

    assert cfg.security.enabled is True
    warnings = consume_config_recovery_warnings()
    assert any("security.rate_limit_rpm" in w for w in warnings), warnings


def test_security_profiles_only_set_live_keys() -> None:
    """A profile must not advertise behaviour it cannot deliver."""
    from grandpa.core.config import (
        _SECURITY_PROFILES,
        SecurityConfig,
        ServerConfig,
    )

    security_fields = set(SecurityConfig.__dataclass_fields__)
    server_fields = set(ServerConfig.__dataclass_fields__)
    for name, definition in _SECURITY_PROFILES.items():
        assert set(definition.get("security", {})) <= security_fields, name
        assert set(definition.get("server", {})) <= server_fields, name


def test_dotenv_files_are_not_loaded(tmp_path: Path, monkeypatch) -> None:
    """Grandpa configures from config.toml + the process environment only.

    A `.env` file is not read: nothing in the codebase parses one and
    python-dotenv is not a dependency. The misleading `.env.example` and the
    README step that told users to copy it were removed rather than adding a
    second configuration mechanism.
    """
    import grandpa.core.config as config_module
    from grandpa.core.config import load_config

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "GRANDPA_API_KEY=gp_sk_from_dotenv\n", encoding="utf-8"
    )
    monkeypatch.delenv("GRANDPA_API_KEY", raising=False)
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_DIR", tmp_path)

    load_config()

    assert os.environ.get("GRANDPA_API_KEY") is None

    from grandpa.server.auth_middleware import api_key_from_env

    assert api_key_from_env() == ""


def test_repository_ships_no_dotenv_example() -> None:
    """The file implied a loader that does not exist."""
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / ".env.example").exists()
