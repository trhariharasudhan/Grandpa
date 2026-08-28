"""Unit tests for Grandpa self-owned ModelRegistry and ModelSpec."""

from __future__ import annotations

import pytest

from grandpa.core.registry import ModelRegistry
from grandpa.core.types import ModelSpec, Quantization


@pytest.fixture(autouse=True)
def clean_registry():
    ModelRegistry.clear()
    yield
    ModelRegistry.clear()


class TestModelSpecMetadata:
    def test_required_phase1_fields(self) -> None:
        spec = ModelSpec(
            model_id="grandpa-mini:v1",
            name="Grandpa Mini",
            parameter_count_b=0.5,
            context_length=32768,
            version="v1.0.0",
            family="qwen",
            capabilities=("text", "chat"),
            local_path="/models/grandpa-mini.gguf",
            size_bytes=350_000_000,
            backend="grandpa-native",
            status="ready",
        )

        assert spec.model_id == "grandpa-mini:v1"
        assert spec.name == "Grandpa Mini"
        assert spec.display_name == "Grandpa Mini"
        assert spec.version == "v1.0.0"
        assert spec.tag == "v1.0.0"
        assert spec.family == "qwen"
        assert spec.capability == "text"
        assert spec.capabilities == ("text", "chat")
        assert spec.local_path == "/models/grandpa-mini.gguf"
        assert spec.size_bytes == 350_000_000
        assert spec.backend == "grandpa-native"
        assert spec.status == "ready"

    def test_default_values(self) -> None:
        spec = ModelSpec(
            model_id="qwen3:8b",
            name="Qwen 3 8B",
            parameter_count_b=8.2,
            context_length=32768,
        )
        assert spec.version == "latest"
        assert spec.tag == "latest"
        assert spec.family == ""
        assert spec.capabilities == ("chat",)
        assert spec.capability == "chat"
        assert spec.local_path is None
        assert spec.size_bytes is None
        assert spec.backend == "local"
        assert spec.status == "available"
        assert spec.quantization == Quantization.NONE

    def test_to_dict_serialization(self) -> None:
        spec = ModelSpec(
            model_id="custom:coder",
            name="Custom Coder",
            parameter_count_b=7.0,
            context_length=16384,
            family="deepseek",
            capabilities=("text", "code"),
            backend="llamacpp",
            status="available",
        )
        d = spec.to_dict()
        assert d["model_id"] == "custom:coder"
        assert d["name"] == "Custom Coder"
        assert d["display_name"] == "Custom Coder"
        assert d["family"] == "deepseek"
        assert d["capabilities"] == ["text", "code"]
        assert d["backend"] == "llamacpp"
        assert d["status"] == "available"
        assert d["context_length"] == 16384


class TestModelRegistryQueries:
    def test_register_and_list_models(self) -> None:
        s1 = ModelSpec(
            model_id="m1",
            name="Model 1",
            family="qwen",
            capabilities=("chat",),
            backend="ollama",
            status="available",
        )
        s2 = ModelSpec(
            model_id="m2",
            name="Model 2",
            family="llama",
            capabilities=("code",),
            backend="llamacpp",
            status="ready",
        )

        ModelRegistry.register_value("m1", s1)
        ModelRegistry.register_value("m2", s2)

        models = ModelRegistry.list_models()
        assert len(models) == 2
        assert {m.model_id for m in models} == {"m1", "m2"}

    def test_register_or_replace(self) -> None:
        s1 = ModelSpec(model_id="m1", name="V1", status="downloading")
        s2 = ModelSpec(model_id="m1", name="V2", status="ready")

        ModelRegistry.register_value("m1", s1)
        assert ModelRegistry.get("m1").status == "downloading"

        ModelRegistry.register_or_replace("m1", s2)
        assert ModelRegistry.get("m1").status == "ready"
        assert ModelRegistry.get("m1").name == "V2"

    def test_find_by_capability(self) -> None:
        s1 = ModelSpec(model_id="c1", name="Chat", capabilities=("chat", "text"))
        s2 = ModelSpec(model_id="c2", name="Code", capabilities=("code",))
        s3 = ModelSpec(model_id="c3", name="Vision", capabilities=("image", "text"))

        ModelRegistry.register_value("c1", s1)
        ModelRegistry.register_value("c2", s2)
        ModelRegistry.register_value("c3", s3)

        chat_models = ModelRegistry.find_by_capability("chat")
        assert len(chat_models) == 1
        assert chat_models[0].model_id == "c1"

        text_models = ModelRegistry.find_by_capability("text")
        assert len(text_models) == 2
        assert {m.model_id for m in text_models} == {"c1", "c3"}

        missing = ModelRegistry.find_by_capability("audio")
        assert missing == []

    def test_find_by_family(self) -> None:
        s1 = ModelSpec(model_id="q1", name="Qwen 1", family="qwen")
        s2 = ModelSpec(model_id="q2", name="Qwen 2", family="QWEN")
        s3 = ModelSpec(model_id="l1", name="Llama 1", family="llama")

        ModelRegistry.register_value("q1", s1)
        ModelRegistry.register_value("q2", s2)
        ModelRegistry.register_value("l1", s3)

        qwen_models = ModelRegistry.find_by_family("qwen")
        assert len(qwen_models) == 2
        assert {m.model_id for m in qwen_models} == {"q1", "q2"}

    def test_find_by_backend(self) -> None:
        s1 = ModelSpec(
            model_id="b1",
            name="Ollama Mod",
            backend="ollama",
            supported_engines=("ollama",),
        )
        s2 = ModelSpec(
            model_id="b2",
            name="Native Mod",
            backend="grandpa-native",
            supported_engines=("grandpa-native", "llamacpp"),
        )

        ModelRegistry.register_value("b1", s1)
        ModelRegistry.register_value("b2", s2)

        ollama_models = ModelRegistry.find_by_backend("ollama")
        assert len(ollama_models) == 1
        assert ollama_models[0].model_id == "b1"

        llamacpp_models = ModelRegistry.find_by_backend("llamacpp")
        assert len(llamacpp_models) == 1
        assert llamacpp_models[0].model_id == "b2"

    def test_find_by_status(self) -> None:
        s1 = ModelSpec(model_id="s1", name="Ready", status="ready")
        s2 = ModelSpec(model_id="s2", name="Downloading", status="downloading")

        ModelRegistry.register_value("s1", s1)
        ModelRegistry.register_value("s2", s2)

        assert len(ModelRegistry.find_by_status("ready")) == 1
        assert len(ModelRegistry.find_by_status("downloading")) == 1
        assert len(ModelRegistry.find_by_status("failed")) == 0

    def test_get_or_default(self) -> None:
        s1 = ModelSpec(model_id="s1", name="Present")
        ModelRegistry.register_value("s1", s1)

        assert ModelRegistry.get_or_default("s1") is s1
        assert ModelRegistry.get_or_default("absent") is None
        fallback = ModelSpec(model_id="fb", name="Fallback")
        assert ModelRegistry.get_or_default("absent", default=fallback) is fallback

    def test_to_dict_export(self) -> None:
        s1 = ModelSpec(model_id="s1", name="Export Spec", family="qwen")
        ModelRegistry.register_value("s1", s1)

        exported = ModelRegistry.to_dict()
        assert "s1" in exported
        assert exported["s1"]["family"] == "qwen"
        assert exported["s1"]["name"] == "Export Spec"
