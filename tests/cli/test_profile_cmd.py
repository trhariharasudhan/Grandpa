from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from grandpa.cli.profile_cmd import profile
from grandpa.core.config import GrandpaConfig, load_config
from grandpa.profile import (
    atomic_update_profile,
    ensure_profile,
    format_profile_display_name,
    load_profile,
    repair_runtime_configuration,
    validate_title,
    validate_username,
)


def _console() -> Console:
    return Console(record=True, width=100)


def test_first_run_collects_and_persists_local_profile(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(
        path,
        engine="existing-engine",
        model="existing-model",
        memory_enabled=False,
    )
    load_config.cache_clear()
    config = load_config(path)
    prompts: list[str] = []

    def answer(label: str, _default: str) -> str:
        prompts.append(label)
        return "  Hari  "

    updated = ensure_profile(
        console=_console(),
        path=path,
        config=config,
        interactive=True,
        text_prompt=answer,
        title_prompt=lambda _current: "Mr.",
    )

    assert prompts == ["Display name"]
    assert updated.user.username == "Hari"
    assert updated.user.title == "Mr."
    assert updated.user.onboarding_completed is True
    assert updated.engine.default == "existing-engine"
    assert updated.intelligence.default_model == "existing-model"
    assert updated.agent.context_from_memory is False
    assert load_profile(path).username == "Hari"


def test_completed_onboarding_does_not_prompt_again(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(
        path,
        username="Hari",
        title="Mrs.",
        engine="ollama",
        model="grandpa-fast:latest",
        memory_enabled=True,
        onboarding_completed=True,
    )
    load_config.cache_clear()

    updated = ensure_profile(
        console=_console(),
        path=path,
        interactive=True,
        text_prompt=lambda *_args: (_ for _ in ()).throw(AssertionError("prompted")),
    )

    assert updated.user.username == "Hari"


def test_noninteractive_first_run_continues_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = GrandpaConfig()

    updated = ensure_profile(
        console=_console(),
        path=path,
        config=config,
        interactive=False,
    )

    assert updated is config
    assert updated.user.onboarding_completed is False
    assert not path.exists()


def test_profile_edit_updates_existing_profile(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(
        path,
        username="Username",
        engine="ollama",
        model="old-model",
        memory_enabled=True,
        onboarding_completed=True,
    )
    load_config.cache_clear()

    result = CliRunner().invoke(
        profile,
        ["edit"],
        input="1\nHari\n",
        env={"Grandpa_CONFIG": str(path)},
    )

    assert result.exit_code == 0
    updated = load_profile(path)
    assert updated.username == "Hari"
    assert updated.model == "old-model"
    assert updated.memory_enabled is True


def test_profile_reset_requires_confirmation_and_resets_onboarding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(
        path,
        username="Hari",
        title="Mrs.",
        onboarding_completed=True,
        engine="ollama",
        model="grandpa-fast:latest",
        memory_enabled=False,
    )
    load_config.cache_clear()

    result = CliRunner().invoke(
        profile,
        ["reset", "--yes"],
        env={"Grandpa_CONFIG": str(path)},
    )

    assert result.exit_code == 0
    assert load_profile(path).onboarding_completed is False
    assert load_profile(path).username == "Hari"
    assert load_profile(path).title == "Mrs."
    assert load_profile(path).engine == "ollama"
    assert load_profile(path).model == "grandpa-fast:latest"
    assert load_profile(path).memory_enabled is False


def test_profile_reset_can_be_cancelled(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(path, username="Hari", onboarding_completed=True)
    load_config.cache_clear()

    result = CliRunner().invoke(
        profile,
        ["reset"],
        input="n\n",
        env={"Grandpa_CONFIG": str(path)},
    )

    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()
    assert load_profile(path).onboarding_completed is True


def test_username_validation_rejects_empty_long_and_control_characters() -> None:
    for value in ("   ", "x" * 41, "Hari\x00"):
        try:
            validate_username(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected invalid display name: {value!r}")

    assert validate_username("  Hari   S  ") == "Hari S"


def test_onboarding_reprompts_after_an_empty_display_name(tmp_path: Path) -> None:
    answers = iter(["   ", "Hari"])
    prompts: list[str] = []

    def answer(label: str, _default: str) -> str:
        prompts.append(label)
        return next(answers)

    updated = ensure_profile(
        console=_console(),
        path=tmp_path / "config.toml",
        config=GrandpaConfig(),
        interactive=True,
        text_prompt=answer,
        title_prompt=lambda _current: "",
    )

    assert prompts == ["Display name", "Display name"]
    assert updated.user.username == "Hari"


@pytest.mark.parametrize("title", ["Mr.", "Ms.", "Mrs.", "Mx.", ""])
def test_new_profile_persists_supported_title(tmp_path: Path, title: str) -> None:
    path = tmp_path / "config.toml"

    updated = ensure_profile(
        console=_console(),
        path=path,
        config=GrandpaConfig(),
        interactive=True,
        text_prompt=lambda _label, _default: "Hari Hara Sudhan",
        title_prompt=lambda _current: title,
    )

    assert updated.user.title == title
    assert load_profile(path).title == title


def test_legacy_profile_without_title_loads_without_onboarding(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[user]\nusername = "Hari Hara Sudhan"\nonboarding_completed = true\n',
        encoding="utf-8",
    )
    load_config.cache_clear()

    profile_data = load_profile(path)

    assert profile_data.username == "Hari Hara Sudhan"
    assert profile_data.title == ""
    assert profile_data.onboarding_completed is True


def test_profile_table_compatibility_and_title_normalization(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[profile]\ndisplay_name = "Hari Hara Sudhan"\ntitle = "Mr."\n',
        encoding="utf-8",
    )
    load_config.cache_clear()

    loaded = load_profile(path)

    assert format_profile_display_name(loaded) == "Mr. Hari Hara Sudhan"
    assert validate_title("Mr..") == "Mr."


def test_profile_title_can_be_edited_and_removed(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(path, username="Hari", title="Mr.", onboarding_completed=True)
    load_config.cache_clear()

    edited = CliRunner().invoke(
        profile,
        ["edit"],
        input="2\n4\n",
        env={"Grandpa_CONFIG": str(path)},
    )
    assert edited.exit_code == 0
    assert load_profile(path).title == "Mx."

    removed = CliRunner().invoke(
        profile,
        ["edit"],
        input="2\n5\n",
        env={"Grandpa_CONFIG": str(path)},
    )
    assert removed.exit_code == 0
    assert load_profile(path).title == ""


def test_invalid_onboarding_runtime_values_are_repaired_without_pull(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(
        path,
        username="Hari",
        onboarding_completed=True,
        engine="oki",
        model="ok",
        memory_enabled=False,
    )
    load_config.cache_clear()
    config = load_config(path)

    repaired = repair_runtime_configuration(
        config,
        resolved_engine="ollama",
        available_models=["grandpa-fast:latest"],
        path=path,
    )

    assert repaired.engine.default == "ollama"
    assert repaired.intelligence.default_model == "grandpa-fast:latest"
    assert repaired.agent.context_from_memory is False
    assert repaired.user.username == "Hari"


def test_runtime_repair_leaves_legitimate_configuration_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    atomic_update_profile(
        path,
        username="Hari",
        onboarding_completed=True,
        engine="ollama",
        model="custom-model:latest",
        memory_enabled=True,
    )
    before = path.read_text(encoding="utf-8")
    load_config.cache_clear()

    repaired = repair_runtime_configuration(
        load_config(path),
        resolved_engine="ollama",
        available_models=["grandpa-fast:latest"],
        path=path,
    )

    assert repaired.intelligence.default_model == "custom-model:latest"
    assert path.read_text(encoding="utf-8") == before


def test_runtime_repair_migrates_legacy_tiny_qwen_when_mini_is_installed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    legacy = "qwen2.5:0.5b-instruct-q4_K_M"
    atomic_update_profile(
        path,
        username="Hari",
        onboarding_completed=True,
        engine="ollama",
        model=legacy,
        memory_enabled=True,
    )
    load_config.cache_clear()

    repaired = repair_runtime_configuration(
        load_config(path),
        resolved_engine="ollama",
        available_models=[legacy, "grandpa-mini:latest"],
        path=path,
    )

    assert repaired.intelligence.default_model == "grandpa-mini:latest"
