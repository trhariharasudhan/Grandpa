"""Canonical Grandpa Odin model roles and legacy model compatibility."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GrandpaModelRole:
    """Product-facing metadata for one Grandpa model role."""

    role: str
    ollama_tag: str
    display_name: str
    description: str
    capabilities: frozenset[str]
    base_family: str
    parameter_count_b: float
    minimum_memory_gb: float
    recommended_memory_gb: float
    context_length: int = 32768
    fallback_role: str | None = None
    user_visible: bool = True
    specialized: bool = False
    legacy_aliases: tuple[str, ...] = ()

    @property
    def model_id(self) -> str:
        """Backend-independent model identifier."""
        return self.ollama_tag

    @property
    def tag(self) -> str:
        """Version tag / model tag alias."""
        return self.ollama_tag


GRANDPA_MODEL_ROLES: tuple[GrandpaModelRole, ...] = (
    GrandpaModelRole(
        role="mini",
        ollama_tag="grandpa-mini:latest",
        display_name="Grandpa Mini",
        description="Default / Fastest",
        capabilities=frozenset({"text", "chat"}),
        base_family="Qwen2.5",
        parameter_count_b=0.5,
        minimum_memory_gb=1.0,
        recommended_memory_gb=2.0,
        context_length=32768,
        legacy_aliases=("qwen2.5:0.5b-instruct-q4_K_M",),
    ),
    GrandpaModelRole(
        role="fast",
        ollama_tag="grandpa-fast:latest",
        display_name="Grandpa Fast",
        description="Better general responses",
        capabilities=frozenset({"text", "chat"}),
        base_family="Qwen3",
        parameter_count_b=4.0,
        minimum_memory_gb=4.0,
        recommended_memory_gb=6.0,
        context_length=32768,
        fallback_role="mini",
        legacy_aliases=("qwen:latest", "grandpa-light:latest", "gemma3:4b"),
    ),
    GrandpaModelRole(
        role="coder",
        ollama_tag="grandpa-coder:latest",
        display_name="Grandpa Coder",
        description="Coding specialist",
        capabilities=frozenset({"text", "code"}),
        base_family="DeepSeek Coder",
        parameter_count_b=6.7,
        minimum_memory_gb=6.0,
        recommended_memory_gb=8.0,
        context_length=16384,
        fallback_role="fast",
        specialized=True,
    ),
    GrandpaModelRole(
        role="eyes",
        ollama_tag="grandpa-eyes:latest",
        display_name="Grandpa Eyes",
        description="Vision specialist",
        capabilities=frozenset({"text", "image"}),
        base_family="LLaVA",
        parameter_count_b=7.2,
        minimum_memory_gb=6.0,
        recommended_memory_gb=8.0,
        context_length=4096,
        fallback_role="fast",
        specialized=True,
    ),
    GrandpaModelRole(
        role="embeddings",
        ollama_tag="nomic-embed-text:latest",
        display_name="Nomic Embed Text",
        description="Internal semantic memory embeddings",
        capabilities=frozenset({"embeddings"}),
        base_family="Nomic BERT",
        parameter_count_b=0.137,
        minimum_memory_gb=0.5,
        recommended_memory_gb=1.0,
        context_length=8192,
        user_visible=False,
        specialized=True,
        legacy_aliases=("nomic-embed-text",),
    ),
)

DEFAULT_MODEL_ROLE = "mini"
DEFAULT_MODEL_TAG = "grandpa-mini:latest"
EMBEDDING_MODEL_TAG = "nomic-embed-text:latest"
VISION_MODEL_TAG = "grandpa-eyes:latest"

_BY_ROLE = {entry.role: entry for entry in GRANDPA_MODEL_ROLES}
_BY_TAG = {entry.ollama_tag.casefold(): entry for entry in GRANDPA_MODEL_ROLES}
_BY_ALIAS = {
    alias.casefold(): entry
    for entry in GRANDPA_MODEL_ROLES
    for alias in entry.legacy_aliases
}


def get_model_role(value: str | None) -> GrandpaModelRole | None:
    """Resolve a role, canonical tag, or legacy alias to registry metadata."""

    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    return (
        _BY_ROLE.get(normalized) or _BY_TAG.get(normalized) or _BY_ALIAS.get(normalized)
    )


def canonical_model_tag(value: str | None) -> str:
    """Return the canonical tag for known roles/aliases, preserving unknown tags."""

    entry = get_model_role(value)
    return entry.ollama_tag if entry else str(value or "").strip()


def canonical_installed_tag(
    value: str | None, installed: list[str] | tuple[str, ...]
) -> str:
    """Prefer a canonical tag only when it is installed; otherwise preserve input."""

    original = str(value or "").strip()
    canonical = canonical_model_tag(original)
    names = {str(item).strip() for item in installed}
    if canonical in names or canonical.removesuffix(":latest") in names:
        return canonical
    return original


def user_visible_models(*, capability: str = "chat") -> tuple[GrandpaModelRole, ...]:
    """Return product roles suitable for a user-facing capability selector."""

    return tuple(
        entry
        for entry in GRANDPA_MODEL_ROLES
        if entry.user_visible and capability in entry.capabilities
    )


__all__ = [
    "DEFAULT_MODEL_ROLE",
    "DEFAULT_MODEL_TAG",
    "EMBEDDING_MODEL_TAG",
    "GRANDPA_MODEL_ROLES",
    "GrandpaModelRole",
    "VISION_MODEL_TAG",
    "canonical_installed_tag",
    "canonical_model_tag",
    "get_model_role",
    "user_visible_models",
]
