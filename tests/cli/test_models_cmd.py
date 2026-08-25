"""Unit tests for Grandpa-owned ``grandpa models`` CLI commands."""

from __future__ import annotations

import json
from unittest import mock

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import ModelRegistry
from grandpa.core.types import ModelSpec


def _runner() -> CliRunner:
    return CliRunner(env={"COLUMNS": "250"})


def _mock_engine():
    """Create a mock engine for CLI tests."""
    engine = mock.MagicMock()
    engine.engine_id = "mock-engine"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model-1", "test-model-2"]
    return engine


class TestModelsListCmd:
    def test_models_list_shows_models(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        fake = _mock_engine()
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [("mock", fake)])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {"mock": ["test-model-1"]})

        result = _runner().invoke(cli, ["models", "list"])
        assert result.exit_code == 0
        assert "Grandpa Model Registry" in result.output
        assert "test-model-1" in result.output

    def test_models_list_filter_by_family(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        ModelRegistry.clear()
        ModelRegistry.register_value(
            "qwen-test",
            ModelSpec(model_id="qwen-test", name="Qwen Test", family="qwen", capabilities=("chat",)),
        )
        ModelRegistry.register_value(
            "llama-test",
            ModelSpec(model_id="llama-test", name="Llama Test", family="llama", capabilities=("chat",)),
        )

        result = _runner().invoke(cli, ["models", "list", "--family", "qwen"])
        assert result.exit_code == 0
        assert "qwen-test" in result.output
        assert "llama-test" not in result.output

    def test_models_list_filter_by_capability(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        ModelRegistry.clear()
        ModelRegistry.register_value(
            "chat-spec",
            ModelSpec(model_id="chat-spec", name="Chat Only", capabilities=("chat",)),
        )
        ModelRegistry.register_value(
            "code-spec",
            ModelSpec(model_id="code-spec", name="Code Only", capabilities=("code",)),
        )

        result = _runner().invoke(cli, ["models", "list", "-c", "code"])
        assert result.exit_code == 0
        assert "code-spec" in result.output
        assert "chat-spec" not in result.output

    def test_models_list_json_output(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        ModelRegistry.clear()
        ModelRegistry.register_value(
            "json-model",
            ModelSpec(model_id="json-model", name="JSON Model", family="qwen", version="v1.0"),
        )

        result = _runner().invoke(cli, ["models", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert any(m["model_id"] == "json-model" for m in data)

    def test_models_list_no_matches(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        result = _runner().invoke(cli, ["models", "list", "--family", "nonexistent-family-xyz"])
        assert result.exit_code == 0
        assert "No models found" in result.output


class TestModelsInfoCmd:
    def test_models_info_success(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        ModelRegistry.clear()
        ModelRegistry.register_value(
            "test-model",
            ModelSpec(
                model_id="test-model",
                name="Test Display",
                family="qwen",
                parameter_count_b=7.0,
                context_length=32768,
                backend="grandpa-native",
                status="ready",
            ),
        )

        result = _runner().invoke(cli, ["models", "info", "test-model"])
        assert result.exit_code == 0
        assert "Model: Test Display" in result.output
        assert "grandpa-native" in result.output
        assert "32,768" in result.output

    def test_models_info_canonical_role_alias(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        # 'mini' should resolve to 'grandpa-mini:latest'
        result = _runner().invoke(cli, ["models", "info", "mini"])
        assert result.exit_code == 0
        assert "Grandpa Mini" in result.output

    def test_models_info_json_output(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        result = _runner().invoke(cli, ["models", "info", "mini", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["model_id"] == "grandpa-mini:latest"
        assert data["name"] == "Grandpa Mini"

    def test_models_info_missing_model_exits_nonzero(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {})

        result = _runner().invoke(cli, ["models", "info", "nonexistent-model-12345"])
        assert result.exit_code != 0
        assert "Model not found" in result.output

    def test_models_info_invalid_empty_input(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)

        result = _runner().invoke(cli, ["models", "info", "   "])
        assert result.exit_code != 0


class TestModelsStatusCmd:
    def test_models_status_healthy_engine(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        cfg.intelligence.default_model = "grandpa-mini:latest"
        cfg.engine.default = "mock"
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)

        fake = _mock_engine()
        monkeypatch.setattr("grandpa.cli.model.get_engine", lambda c, k: ("mock", fake))
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [("mock", fake)])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {"mock": ["grandpa-mini:latest"]})

        result = _runner().invoke(cli, ["models", "status"])
        assert result.exit_code == 0
        assert "Grandpa Model Platform Status" in result.output
        assert "Healthy" in result.output

    def test_models_status_json_output(self, monkeypatch) -> None:
        cfg = GrandpaConfig()
        monkeypatch.setattr("grandpa.cli.model.load_config", lambda: cfg)
        fake = _mock_engine()
        monkeypatch.setattr("grandpa.cli.model.get_engine", lambda c, k: ("mock", fake))
        monkeypatch.setattr("grandpa.cli.model.discover_engines", lambda c: [("mock", fake)])
        monkeypatch.setattr("grandpa.cli.model.discover_models", lambda e: {"mock": ["grandpa-mini:latest"]})

        result = _runner().invoke(cli, ["models", "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "status" in data
        assert "default_model" in data
        assert "total_registered_models" in data
        assert "backend_healthy" in data
        assert data["backend_healthy"] is True
