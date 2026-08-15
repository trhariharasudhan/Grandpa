from grandpa.intelligence.grandpa_models import (
    DEFAULT_MODEL_TAG,
    EMBEDDING_MODEL_TAG,
    canonical_installed_tag,
    canonical_model_tag,
    get_model_role,
    user_visible_models,
)


def test_canonical_registry_exposes_odin_roles() -> None:
    assert DEFAULT_MODEL_TAG == "grandpa-mini:latest"
    assert get_model_role("mini").ollama_tag == DEFAULT_MODEL_TAG
    assert get_model_role("fast").base_family == "Qwen3"
    assert get_model_role("coder").capabilities == frozenset({"text", "code"})
    assert get_model_role("eyes").capabilities == frozenset({"text", "image"})


def test_legacy_tiny_qwen_resolves_to_grandpa_mini() -> None:
    assert canonical_model_tag("qwen2.5:0.5b-instruct-q4_K_M") == "grandpa-mini:latest"


def test_legacy_alias_is_preserved_until_canonical_tag_is_installed() -> None:
    legacy = "qwen2.5:0.5b-instruct-q4_K_M"
    assert canonical_installed_tag(legacy, [legacy]) == legacy
    assert (
        canonical_installed_tag(legacy, [legacy, DEFAULT_MODEL_TAG])
        == DEFAULT_MODEL_TAG
    )


def test_embedding_model_is_internal_not_chat_selectable() -> None:
    assert EMBEDDING_MODEL_TAG == "nomic-embed-text:latest"
    assert all(entry.role != "embeddings" for entry in user_visible_models())


def test_unknown_model_is_not_rewritten() -> None:
    assert canonical_model_tag("custom-model:latest") == "custom-model:latest"
