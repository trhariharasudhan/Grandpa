from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.core.config import (
    CONFIG_RECOVERY_FAILED_MESSAGE,
    CONFIG_RECOVERY_MESSAGE,
    consume_config_recovery_warnings,
    load_config,
)


@pytest.fixture(autouse=True)
def clear_config_cache_and_warnings():
    load_config.cache_clear()
    consume_config_recovery_warnings()
    yield
    load_config.cache_clear()
    consume_config_recovery_warnings()


@pytest.mark.parametrize(
    "content",
    (
        "[engine\ndefault = 'ollama'",
        "",
        '[engine]\ndefault = "ollama',
        '[user]\nusername = "Hari"\n[engine\ndefault = "ollama"',
    ),
)
def test_invalid_config_is_backed_up_and_replaced_with_defaults(
    tmp_path: Path,
    content: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(content, encoding="utf-8")

    config = load_config(config_path)

    backups = list(tmp_path.glob("config.toml.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == content
    assert config_path.read_text(encoding="utf-8").strip()
    assert config.engine.default
    assert consume_config_recovery_warnings() == [CONFIG_RECOVERY_MESSAGE]
    assert consume_config_recovery_warnings() == []


def test_valid_partial_config_is_preserved(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    content = '[engine]\ndefault = "ollama"\n'
    config_path.write_text(content, encoding="utf-8")

    config = load_config(config_path)

    assert config.engine.default == "ollama"
    assert config_path.read_text(encoding="utf-8") == content
    assert list(tmp_path.glob("config.toml.corrupt-*")) == []
    assert consume_config_recovery_warnings() == []


def test_locked_invalid_config_uses_session_defaults_without_overwrite(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    content = "[broken"
    config_path.write_text(content, encoding="utf-8")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "grandpa.core.config._recover_invalid_config",
            lambda *_args: (_ for _ in ()).throw(PermissionError("locked")),
        )
        config = load_config(config_path)

    assert config.engine.default
    assert config_path.read_text(encoding="utf-8") == content
    assert consume_config_recovery_warnings() == [CONFIG_RECOVERY_FAILED_MESSAGE]
