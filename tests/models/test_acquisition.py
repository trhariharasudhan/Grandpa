"""Unit and regression tests for Phase 5B Native Model Acquisition & Management."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx
from click.testing import CliRunner

from grandpa.cli.model import models_cmd
from grandpa.core.registry import ModelRegistry
from grandpa.core.types import ModelSpec
from grandpa.models.manager import NativeModelManager, discover_native_models
from grandpa.models.security import (
    ChecksumMismatchError,
    ModelSecurityError,
    validate_gguf_filename,
    validate_safe_destination_path,
    verify_sha256,
)
from grandpa.models.source import (
    HuggingFaceModelSource,
    ResolvedModelArtifact,
)


class TestModelSecurity:
    def test_valid_gguf_filename(self) -> None:
        assert validate_gguf_filename("model.gguf") == "model.gguf"
        assert (
            validate_gguf_filename("qwen2.5-0.5b-instruct-q4_k_m.GGUF")
            == "qwen2.5-0.5b-instruct-q4_k_m.GGUF"
        )

    def test_invalid_extension_raises(self) -> None:
        with pytest.raises(ModelSecurityError, match="must have a .gguf extension"):
            validate_gguf_filename("model.bin")
        with pytest.raises(ModelSecurityError, match="must have a .gguf extension"):
            validate_gguf_filename("model.exe")

    def test_path_traversal_filename_raises(self) -> None:
        with pytest.raises(ModelSecurityError, match="Path traversal"):
            validate_gguf_filename("../model.gguf")
        with pytest.raises(ModelSecurityError, match="Path traversal"):
            validate_gguf_filename("sub/model.gguf")
        with pytest.raises(ModelSecurityError, match="Path traversal"):
            validate_gguf_filename("/root/model.gguf")
        with pytest.raises(ModelSecurityError, match="Path traversal"):
            validate_gguf_filename("C:\\Windows\\System32\\model.gguf")

    def test_empty_filename_raises(self) -> None:
        with pytest.raises(ModelSecurityError, match="cannot be empty"):
            validate_gguf_filename("")

    def test_safe_destination_path_allowed(self, tmp_path: Path) -> None:
        dest = tmp_path / "model.gguf"
        validated = validate_safe_destination_path(dest, tmp_path)
        assert validated == dest.resolve()

    def test_destination_outside_allowed_raises(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "escape.gguf"
        with pytest.raises(ModelSecurityError, match="outside allowed model directory"):
            validate_safe_destination_path(outside, tmp_path)

    def test_verify_sha256_success_and_failure(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.gguf"
        content = b"TEST_GGUF_CONTENT_BYTES"
        test_file.write_bytes(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        assert verify_sha256(test_file, expected_hash) is True

        with pytest.raises(ChecksumMismatchError, match="SHA-256 checksum mismatch"):
            verify_sha256(test_file, "0" * 64)


class TestHuggingFaceModelSource:
    def test_resolve_composite_string(self) -> None:
        source = HuggingFaceModelSource()
        artifact = source.resolve(
            "Qwen/Qwen2.5-0.5B-Instruct-GGUF/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        )
        assert artifact.source_type == "huggingface"
        assert artifact.repo_id == "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
        assert artifact.filename == "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        assert (
            artifact.download_url
            == "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        )

    def test_resolve_explicit_filename(self) -> None:
        source = HuggingFaceModelSource()
        artifact = source.resolve(
            "Qwen/Qwen2.5-0.5B-Instruct-GGUF", filename="model.gguf", revision="v1.0"
        )
        assert artifact.repo_id == "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
        assert artifact.filename == "model.gguf"
        assert (
            artifact.download_url
            == "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/v1.0/model.gguf"
        )

    def test_resolve_missing_filename_raises(self) -> None:
        source = HuggingFaceModelSource()
        with pytest.raises(ValueError, match="GGUF filename must be provided"):
            source.resolve("Qwen/Qwen2.5-0.5B-Instruct-GGUF")

    @respx.mock
    def test_download_success_with_progress_and_hash(self, tmp_path: Path) -> None:
        source = HuggingFaceModelSource()
        artifact = ResolvedModelArtifact(
            source_type="huggingface",
            repo_id="test/repo",
            filename="test-model.gguf",
            download_url="https://huggingface.co/test/repo/resolve/main/test-model.gguf",
        )

        content = b"GGUF_MOCK_PAYLOAD_12345"
        expected_hash = hashlib.sha256(content).hexdigest()

        respx.get(artifact.download_url).respond(
            status_code=200,
            headers={"content-length": str(len(content))},
            content=content,
        )

        progress_calls = []

        def on_progress(down: int, total: int | None) -> None:
            progress_calls.append((down, total))

        dest = source.download(
            artifact,
            tmp_path,
            progress_callback=on_progress,
            expected_sha256=expected_hash,
        )

        assert dest == tmp_path / "test-model.gguf"
        assert dest.is_file()
        assert dest.read_bytes() == content
        assert len(progress_calls) > 0

    @respx.mock
    def test_download_failure_cleans_up_temp_file(self, tmp_path: Path) -> None:
        source = HuggingFaceModelSource()
        artifact = ResolvedModelArtifact(
            source_type="huggingface",
            repo_id="test/repo",
            filename="failed-model.gguf",
            download_url="https://huggingface.co/test/repo/resolve/main/failed-model.gguf",
        )

        respx.get(artifact.download_url).respond(status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            source.download(artifact, tmp_path)

        # Confirm no temp files or final destination left
        assert not (tmp_path / "failed-model.gguf").exists()
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0


class TestNativeModelManager:
    @respx.mock
    def test_install_success_registers_model(self, tmp_path: Path) -> None:
        mgr = NativeModelManager(models_dir=tmp_path)
        content = b"GGUF_VALID_TEST_DATA"
        download_url = (
            "https://huggingface.co/Qwen/Qwen2.5-0.5B-GGUF/resolve/main/model.gguf"
        )

        respx.get(download_url).respond(
            status_code=200,
            headers={"content-length": str(len(content))},
            content=content,
        )

        spec = mgr.install(
            model_id="qwen-0.5b",
            source_ref="Qwen/Qwen2.5-0.5B-GGUF/model.gguf",
            display_name="Qwen 0.5B Test",
            family="qwen",
            capabilities=("chat", "code"),
        )

        assert spec.model_id == "qwen-0.5b"
        assert spec.backend == "native"
        assert spec.status == "ready"
        assert spec.size_bytes == len(content)
        assert Path(spec.local_path).is_file()

        # Check ModelRegistry
        assert ModelRegistry.contains("qwen-0.5b")
        reg_spec = ModelRegistry.get("qwen-0.5b")
        assert reg_spec.local_path == spec.local_path

        # Check manifest file
        manifest_file = tmp_path / "registry.json"
        assert manifest_file.is_file()
        data = json.loads(manifest_file.read_text())
        assert "qwen-0.5b" in data

    @respx.mock
    def test_install_failure_does_not_register_model(self, tmp_path: Path) -> None:
        mgr = NativeModelManager(models_dir=tmp_path)
        download_url = (
            "https://huggingface.co/Qwen/Qwen2.5-0.5B-GGUF/resolve/main/model.gguf"
        )

        respx.get(download_url).respond(status_code=404)

        with pytest.raises(httpx.HTTPStatusError):
            mgr.install(
                model_id="failed-model",
                source_ref="Qwen/Qwen2.5-0.5B-GGUF/model.gguf",
            )

        assert not ModelRegistry.contains("failed-model")

    def test_remove_model_deletes_file_and_manifest(self, tmp_path: Path) -> None:
        mgr = NativeModelManager(models_dir=tmp_path)
        model_file = tmp_path / "test-remove.gguf"
        model_file.write_bytes(b"GGUF")

        ModelRegistry.register_or_replace(
            "test-remove",
            ModelSpec(
                model_id="test-remove",
                name="Test Remove",
                backend="native",
                local_path=str(model_file),
            ),
        )
        mgr._save_manifest_entry(ModelRegistry.get("test-remove"))

        assert model_file.is_file()
        assert mgr.remove("test-remove") is True
        assert not model_file.exists()

        # Check manifest
        data = mgr._load_manifest()
        assert "test-remove" not in data

    def test_discover_local_models(self, tmp_path: Path) -> None:
        (tmp_path / "alpha.gguf").write_bytes(b"GGUF_ALPHA")
        (tmp_path / "beta.gguf").write_bytes(b"GGUF_BETA")
        (tmp_path / ".temp.gguf").write_bytes(b"GGUF_IGNORE")  # Hidden file

        manifest = {
            "alpha": {
                "model_id": "alpha",
                "name": "Alpha Model",
                "family": "llama",
                "capabilities": ["chat"],
            }
        }
        (tmp_path / "registry.json").write_text(json.dumps(manifest))

        discovered = discover_native_models(models_dir=tmp_path)
        disc_ids = [s.model_id for s in discovered]
        assert "alpha" in disc_ids
        assert "beta" in disc_ids
        assert ".temp" not in disc_ids

        assert ModelRegistry.contains("alpha")
        assert ModelRegistry.get("alpha").family == "llama"
        assert ModelRegistry.contains("beta")


class TestCLIModelAcquisition:
    runner = CliRunner()

    @respx.mock
    def test_cli_models_pull_native(self, tmp_path: Path, monkeypatch) -> None:
        content = b"GGUF_MOCK_DATA"
        download_url = "https://huggingface.co/test/repo/resolve/main/model.gguf"
        respx.get(download_url).respond(status_code=200, content=content)

        monkeypatch.setattr("grandpa.core.config.DEFAULT_CONFIG_DIR", tmp_path)

        result = self.runner.invoke(
            models_cmd,
            [
                "pull",
                "test/repo/model.gguf",
                "--backend",
                "native",
                "--model-id",
                "test-model",
            ],
        )

        assert result.exit_code == 0
        assert "Successfully installed test-model" in result.output

    def test_cli_models_remove_native(self, tmp_path: Path, monkeypatch) -> None:
        models_dir = tmp_path / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        gguf_file = models_dir / "target-model.gguf"
        gguf_file.write_bytes(b"GGUF")

        monkeypatch.setattr("grandpa.core.config.DEFAULT_CONFIG_DIR", tmp_path)

        result = self.runner.invoke(
            models_cmd,
            ["remove", "target-model"],
        )

        assert result.exit_code == 0
        assert "Successfully removed" in result.output
        assert not gguf_file.exists()
