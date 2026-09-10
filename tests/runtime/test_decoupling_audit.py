"""Regression tests for Phase 4 decoupling audit across application logic."""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from grandpa.browser_intelligence.models import PageContent
from grandpa.browser_intelligence.summarizer import LocalPageSummarizer
from grandpa.cli.chat_cmd import _get_available_models
from grandpa.cli.input_ui import _installed_models, _model_preview_options
from grandpa.connectors.embeddings import BaseEmbedder
from grandpa.intelligence.grandpa_models import GRANDPA_MODEL_ROLES, get_model_role


class SyntheticEmbedder(BaseEmbedder):
    @property
    def model_version(self) -> str:
        return "synthetic:v1"

    @property
    def dim(self) -> Optional[int]:
        return 256

    def is_available(self) -> bool:
        return True

    def embed(self, text: str) -> Optional[bytes]:
        return b"\x00" * 1024


class TestApplicationDecoupling:
    def test_grandpa_model_roles_have_generic_identifiers(self) -> None:
        for role in GRANDPA_MODEL_ROLES:
            assert role.model_id
            assert role.tag
            assert role.model_id == role.ollama_tag
            assert role.tag == role.ollama_tag

        mini_role = get_model_role("mini")
        assert mini_role is not None
        assert mini_role.model_id == "grandpa-mini:latest"

    def test_base_embedder_allows_non_ollama_implementations(self) -> None:
        embedder: BaseEmbedder = SyntheticEmbedder()
        assert embedder.is_available() is True
        assert embedder.model_version == "synthetic:v1"
        assert embedder.dim == 256
        res = embedder.embed("sample text")
        assert res is not None
        batch = embedder.embed_batch(["text1", "text2"])
        assert len(batch) == 2

    def test_chat_cmd_model_discovery_does_not_spawn_ollama_subprocess(self) -> None:
        with patch("subprocess.run") as mock_subproc:
            models = _get_available_models()
            assert isinstance(models, list)
            assert len(models) > 0
            # Subprocess must never be called for model listing
            mock_subproc.assert_not_called()

    def test_input_ui_model_preview_does_not_spawn_ollama_subprocess(self) -> None:
        with patch("subprocess.run") as mock_subproc:
            installed = _installed_models()
            assert isinstance(installed, list)
            assert len(installed) > 0
            preview = _model_preview_options()
            assert isinstance(preview, list)
            assert len(preview) > 0
            mock_subproc.assert_not_called()

    def test_summarizer_uses_generic_engine(self) -> None:
        summarizer = LocalPageSummarizer()
        mock_engine = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "This is a summarized page."
        mock_engine.generate.return_value = mock_response

        page = PageContent(
            title="Sample Page",
            url="https://example.com",
            domain="example.com",
            visible_text="This is a long webpage content that needs to be summarized by Grandpa in tests.",
            paragraphs=["This is a long webpage content that needs to be summarized by Grandpa in tests."],
        )

        with patch("grandpa.engine.get_engine", return_value=("mock_engine", mock_engine)):
            result = summarizer.summarize_page(page)
            assert result == "This is a summarized page."
            mock_engine.generate.assert_called_once()
