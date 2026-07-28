"""Tests for the local Ollama initialization guidance."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.cli.init_cmd import _next_steps_text

_NO_DOWNLOAD = "--no-download"


def _invoke_init(tmp_path: Path, *args: str, input_text: str | None = None):
    config_dir = tmp_path / ".grandpa"
    config_path = config_dir / "config.toml"
    with (
        mock.patch("grandpa.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
        mock.patch("grandpa.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
        mock.patch("grandpa.cli.init_cmd.PrivacyScanner"),
    ):
        result = CliRunner().invoke(
            cli,
            ["init", "--engine", "ollama", *args],
            input=input_text,
        )
    return result, config_path


def test_init_shows_local_next_steps(tmp_path: Path) -> None:
    result, _ = _invoke_init(tmp_path, _NO_DOWNLOAD)
    assert result.exit_code == 0
    assert "Getting Started" in result.output
    assert "ollama serve" in result.output
    assert "grandpa ask" in result.output.lower()
    assert "grandpa doctor" in result.output.lower()


def test_next_steps_use_selected_model() -> None:
    text = _next_steps_text("ollama", "qwen3.5:4b")
    assert "ollama pull qwen3.5:4b" in text


def test_init_generates_minimal_config(tmp_path: Path) -> None:
    result, config_path = _invoke_init(tmp_path, _NO_DOWNLOAD)
    assert result.exit_code == 0
    content = config_path.read_text()
    assert "[engine.ollama]" in content
    assert "Grandpa init --full" in content


def test_init_full_generates_reference_config(tmp_path: Path) -> None:
    result, config_path = _invoke_init(tmp_path, "--full", _NO_DOWNLOAD)
    assert result.exit_code == 0
    content = config_path.read_text()
    assert "[server]" in content
    assert "[security]" in content


def test_init_download_calls_ollama(tmp_path: Path) -> None:
    config_dir = tmp_path / ".grandpa"
    config_path = config_dir / "config.toml"
    with (
        mock.patch("grandpa.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
        mock.patch("grandpa.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
        mock.patch("grandpa.cli.init_cmd.ollama_pull", return_value=True) as pull,
        mock.patch("grandpa.cli.init_cmd.PrivacyScanner"),
    ):
        result = CliRunner().invoke(
            cli,
            ["init", "--engine", "ollama"],
            input="y\n",
        )
    assert result.exit_code == 0
    pull.assert_called_once()


def test_init_rejects_retired_engine(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        ["init", "--engine", "vllm", _NO_DOWNLOAD],
    )
    assert result.exit_code == 2
    assert "Invalid value" in result.output
