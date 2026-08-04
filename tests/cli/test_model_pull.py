"""Tests for local Ollama model downloads."""

from __future__ import annotations

import io
from unittest import mock

import httpx
from click.testing import CliRunner
from rich.console import Console

from grandpa.cli import cli
from grandpa.cli.model import ollama_pull


def test_ollama_pull_success() -> None:
    console = Console(file=io.StringIO())
    response = mock.MagicMock()
    response.raise_for_status = mock.MagicMock()
    response.iter_lines.return_value = iter(
        ['{"status": "pulling manifest"}', '{"status": "success"}']
    )
    response.__enter__ = mock.MagicMock(return_value=response)
    response.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("httpx.stream", return_value=response):
        assert ollama_pull("http://localhost:11434", "qwen3.5:2b", console)


def test_ollama_pull_connection_error() -> None:
    console = Console(file=io.StringIO())
    with mock.patch("httpx.stream", side_effect=httpx.ConnectError("refused")):
        assert not ollama_pull("http://localhost:11434", "qwen3.5:2b", console)


def test_pull_cli_only_accepts_ollama() -> None:
    result = CliRunner().invoke(
        cli, ["model", "pull", "qwen3.5:2b", "--engine", "vllm"]
    )
    assert result.exit_code == 2
    assert "Invalid value" in result.output
