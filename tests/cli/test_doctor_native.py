"""Unit tests for native backend diagnostics in Grandpa Doctor."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from grandpa.cli.doctor_cmd import (
    _check_native_backend_diagnostics,
    doctor,
)
from grandpa.core.config import GrandpaConfig


class TestDoctorNativeDiagnostics:
    def test_native_diagnostics_when_llama_cpp_missing(self, tmp_path: Path) -> None:
        cfg = GrandpaConfig()
        cfg.engine.default = "native"
        cfg.engine.native.models_dir = str(tmp_path)

        with patch.dict(sys.modules, {"llama_cpp": None}):
            checks = _check_native_backend_diagnostics(cfg)

        names = {c.name: c for c in checks}
        assert "llama-cpp-python runtime" in names
        assert names["llama-cpp-python runtime"].status == "warn"
        assert "Not installed" in names["llama-cpp-python runtime"].message

    def test_native_diagnostics_when_models_dir_empty(self, tmp_path: Path) -> None:
        cfg = GrandpaConfig()
        cfg.engine.default = "native"
        cfg.engine.native.models_dir = str(tmp_path)

        mock_llama = MagicMock()
        with patch.dict(sys.modules, {"llama_cpp": mock_llama}):
            checks = _check_native_backend_diagnostics(cfg)

        names = {c.name: c for c in checks}
        assert names["llama-cpp-python runtime"].status == "ok"
        assert names["Native models directory"].status == "ok"
        assert names["Native GGUF models"].status == "warn"
        assert "No GGUF files found" in names["Native GGUF models"].message

    def test_native_diagnostics_with_installed_models(self, tmp_path: Path) -> None:
        cfg = GrandpaConfig()
        cfg.engine.default = "native"
        cfg.engine.native.models_dir = str(tmp_path)
        cfg.intelligence.default_model = "grandpa-mini"

        (tmp_path / "grandpa-mini.gguf").write_bytes(b"GGUF_TEST_HEADER_DATA")

        mock_llama = MagicMock()
        with patch.dict(sys.modules, {"llama_cpp": mock_llama}):
            checks = _check_native_backend_diagnostics(cfg)

        names = {c.name: c for c in checks}
        assert names["Native GGUF models"].status == "ok"
        assert "1 installed" in names["Native GGUF models"].message

        assert "Selected native model" in names
        assert names["Selected native model"].status == "ok"
        assert "Ready (grandpa-mini" in names["Selected native model"].message

    def test_native_diagnostics_with_missing_selected_model(self, tmp_path: Path) -> None:
        cfg = GrandpaConfig()
        cfg.engine.default = "native"
        cfg.engine.native.models_dir = str(tmp_path)
        cfg.intelligence.default_model = "non-existent-model"

        mock_llama = MagicMock()
        with patch.dict(sys.modules, {"llama_cpp": mock_llama}):
            checks = _check_native_backend_diagnostics(cfg)

        names = {c.name: c for c in checks}
        assert "Selected native model" in names
        assert names["Selected native model"].status in ("warn", "fail")

    def test_cli_doctor_runs_cleanly_with_native(self, tmp_path: Path, monkeypatch) -> None:
        runner = CliRunner()
        monkeypatch.setattr("grandpa.core.config.DEFAULT_CONFIG_DIR", tmp_path)

        result = runner.invoke(doctor, ["--json"])
        assert result.exit_code == 0
