"""Built-in metadata for models available through the local Ollama runtime."""

from __future__ import annotations

from typing import List

from grandpa.core.registry import ModelRegistry
from grandpa.core.types import ModelSpec
from grandpa.intelligence.grandpa_models import GRANDPA_MODEL_ROLES


def _infer_family(model_id: str, provider: str = "") -> str:
    mid = model_id.lower()
    if "qwen" in mid:
        return "qwen"
    if "llama" in mid:
        return "llama"
    if "deepseek" in mid:
        return "deepseek"
    if "gemma" in mid:
        return "gemma"
    if "mistral" in mid:
        return "mistral"
    if "granite" in mid:
        return "granite"
    if "phi" in mid:
        return "phi"
    if "nomic" in mid:
        return "nomic"
    if "llava" in mid:
        return "llava"
    if "gpt" in mid:
        return "gpt"
    return provider.lower() if provider else mid.split(":")[0].split("-")[0]


def _infer_version(model_id: str) -> str:
    if ":" in model_id:
        return model_id.split(":", 1)[1]
    return "latest"


def _infer_capabilities(model_id: str) -> tuple[str, ...]:
    mid = model_id.lower()
    if "embed" in mid:
        return ("embeddings",)
    if any(k in mid for k in ("eyes", "vision", "image", "llava")):
        return ("text", "image")
    if any(k in mid for k in ("coder", "code")):
        return ("text", "code")
    return ("text", "chat")


def _local_model(
    model_id: str,
    name: str,
    parameter_count_b: float,
    context_length: int,
    *,
    active_parameter_count_b: float | None = None,
    provider: str = "",
    architecture: str = "dense",
    family: str = "",
    capabilities: tuple[str, ...] | None = None,
    backend: str = "ollama",
    status: str = "available",
) -> ModelSpec:
    derived_family = family or _infer_family(model_id, provider)
    derived_caps = capabilities or _infer_capabilities(model_id)
    derived_version = _infer_version(model_id)
    return ModelSpec(
        model_id=model_id,
        name=name,
        parameter_count_b=parameter_count_b,
        active_parameter_count_b=active_parameter_count_b,
        context_length=context_length,
        supported_engines=(backend,),
        provider=provider,
        metadata={"architecture": architecture},
        version=derived_version,
        family=derived_family,
        capabilities=derived_caps,
        backend=backend,
        status=status,
    )


BUILTIN_MODELS: List[ModelSpec] = [
    *[
        _local_model(
            entry.ollama_tag,
            entry.display_name,
            entry.parameter_count_b,
            entry.context_length,
            provider="grandpa-odin",
            architecture="dense",
            family=entry.base_family.lower().split()[0],
            capabilities=tuple(entry.capabilities),
            backend="ollama",
            status="available",
        )
        for entry in GRANDPA_MODEL_ROLES
        if "embeddings" not in entry.capabilities
    ],
    _local_model("qwen3:0.6b", "Qwen3 0.6B", 0.6, 40960, provider="alibaba"),
    _local_model("qwen3:1.7b", "Qwen3 1.7B", 1.7, 40960, provider="alibaba"),
    _local_model("qwen3:4b", "Qwen3 4B", 4.0, 262144, provider="alibaba"),
    _local_model("qwen3:8b", "Qwen3 8B", 8.2, 32768, provider="alibaba"),
    _local_model("qwen3:14b", "Qwen3 14B", 14.0, 40960, provider="alibaba"),
    _local_model("qwen3:30b", "Qwen3 30B", 30.0, 262144, provider="alibaba"),
    _local_model("qwen3:32b", "Qwen3 32B", 32.0, 32768, provider="alibaba"),
    _local_model(
        "qwen3.5:2b",
        "Qwen3.5 2B",
        2.0,
        131072,
        active_parameter_count_b=0.4,
        provider="alibaba",
        architecture="moe",
    ),
    _local_model(
        "qwen3.5:4b",
        "Qwen3.5 4B",
        4.0,
        131072,
        active_parameter_count_b=0.8,
        provider="alibaba",
        architecture="moe",
    ),
    _local_model(
        "qwen3.5:9b",
        "Qwen3.5 9B",
        9.0,
        131072,
        active_parameter_count_b=1.5,
        provider="alibaba",
        architecture="moe",
    ),
    _local_model(
        "qwen3.5:27b",
        "Qwen3.5 27B",
        27.0,
        131072,
        active_parameter_count_b=3.0,
        provider="alibaba",
        architecture="moe",
    ),
    _local_model(
        "qwen3.5:35b",
        "Qwen3.5 35B",
        35.0,
        131072,
        active_parameter_count_b=3.0,
        provider="alibaba",
        architecture="moe",
    ),
    _local_model(
        "gpt-oss:120b",
        "GPT-OSS 120B",
        117.0,
        131072,
        active_parameter_count_b=5.1,
        provider="open-weight",
        architecture="moe",
    ),
    _local_model(
        "deepseek-coder-v2:16b",
        "DeepSeek Coder V2 Lite",
        16.0,
        128000,
        provider="deepseek",
    ),
    _local_model(
        "llama3.2:3b",
        "Llama 3.2 3B",
        3.0,
        131072,
        provider="meta",
    ),
    _local_model(
        "mistral:7b",
        "Mistral 7B",
        7.0,
        32768,
        provider="mistral",
    ),
    _local_model(
        "granite3.3:8b",
        "Granite 3.3 8B",
        8.0,
        128000,
        provider="ibm",
    ),
]


def register_builtin_models() -> None:
    """Populate ``ModelRegistry`` with known local models."""
    for spec in BUILTIN_MODELS:
        if not ModelRegistry.contains(spec.model_id):
            ModelRegistry.register_value(spec.model_id, spec)


def merge_discovered_models(engine_key: str, model_ids: List[str]) -> None:
    """Create minimal entries for models discovered from the local runtime."""
    for model_id in model_ids:
        if not ModelRegistry.contains(model_id):
            spec = ModelSpec(
                model_id=model_id,
                name=model_id,
                parameter_count_b=0.0,
                context_length=0,
                supported_engines=(engine_key,),
                version=_infer_version(model_id),
                family=_infer_family(model_id),
                capabilities=_infer_capabilities(model_id),
                backend=engine_key,
                status="available",
            )
            ModelRegistry.register_value(model_id, spec)


__all__ = ["BUILTIN_MODELS", "merge_discovered_models", "register_builtin_models"]
