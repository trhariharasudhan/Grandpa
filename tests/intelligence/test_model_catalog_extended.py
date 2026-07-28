"""Local-only invariants for the built-in model catalog."""

from __future__ import annotations

from grandpa.intelligence.model_catalog import BUILTIN_MODELS


def test_catalog_contains_recommended_qwen_tiers() -> None:
    model_ids = {spec.model_id for spec in BUILTIN_MODELS}
    assert {"qwen3.5:2b", "qwen3.5:4b", "qwen3.5:9b", "qwen3.5:27b"} <= model_ids


def test_catalog_only_advertises_ollama() -> None:
    assert BUILTIN_MODELS
    assert all(tuple(spec.supported_engines) == ("ollama",) for spec in BUILTIN_MODELS)


def test_catalog_has_no_api_key_models() -> None:
    assert all(not spec.requires_api_key for spec in BUILTIN_MODELS)


def test_catalog_entries_have_runtime_metadata() -> None:
    for spec in BUILTIN_MODELS:
        assert spec.model_id
        assert spec.name
        assert spec.context_length > 0
        assert spec.metadata["architecture"] in {"dense", "moe"}
