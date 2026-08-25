"""Decorator-based registry for runtime discovery of pluggable components.

Adapted from IPW's ``src/ipw/core/registry.py``.  Each typed subclass gets its
own isolated storage so registrations in one registry never leak into another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Generic, Tuple, Type, TypeVar

if TYPE_CHECKING:
    from grandpa.agents._stubs import BaseAgent
    from grandpa.engine._stubs import InferenceEngine
    from grandpa.tools.storage._stubs import MemoryBackend

T = TypeVar("T")


class RegistryBase(Generic[T]):
    """Generic registry base class with class-specific entry isolation."""

    @classmethod
    def _entries(cls) -> Dict[str, T]:
        attr_name = f"_registry_entries_{cls.__name__}"
        storage = getattr(cls, attr_name, None)
        if storage is None:
            storage: Dict[str, T] = {}
            setattr(cls, attr_name, storage)
        return storage

    @classmethod
    def register(cls, key: str) -> Callable[[T], T]:
        """Decorator that registers *entry* under *key*."""

        def decorator(entry: T) -> T:
            entries = cls._entries()
            if key in entries:
                raise ValueError(f"{cls.__name__} already has an entry for '{key}'")
            entries[key] = entry
            return entry

        return decorator

    @classmethod
    def register_value(cls, key: str, value: T) -> T:
        """Imperatively register a *value* under *key*."""
        entries = cls._entries()
        if key in entries:
            raise ValueError(f"{cls.__name__} already has an entry for '{key}'")
        entries[key] = value
        return value

    @classmethod
    def register_or_replace(cls, key: str, value: T) -> T:
        """Imperatively register or update a *value* under *key*."""
        entries = cls._entries()
        entries[key] = value
        return value

    @classmethod
    def get(cls, key: str) -> T:
        """Retrieve the entry for *key*, raising ``KeyError`` if missing."""
        try:
            return cls._entries()[key]
        except KeyError as exc:
            raise KeyError(
                f"{cls.__name__} does not have an entry for '{key}'"
            ) from exc

    @classmethod
    def create(cls, key: str, *args: Any, **kwargs: Any) -> Any:
        """Look up *key* and instantiate it with the given arguments."""
        entry = cls.get(key)
        if not callable(entry):
            raise TypeError(
                f"{cls.__name__} entry '{key}' is not callable"
                " and cannot be instantiated"
            )
        return entry(*args, **kwargs)

    @classmethod
    def items(cls) -> Tuple[Tuple[str, T], ...]:
        """Return all ``(key, entry)`` pairs as a tuple."""
        return tuple(cls._entries().items())

    @classmethod
    def keys(cls) -> Tuple[str, ...]:
        """Return all registered keys as a tuple."""
        return tuple(cls._entries().keys())

    @classmethod
    def contains(cls, key: str) -> bool:
        """Check whether *key* is registered."""
        return key in cls._entries()

    @classmethod
    def clear(cls) -> None:
        """Remove all entries (useful in tests)."""
        cls._entries().clear()


# ---------------------------------------------------------------------------
# Typed subclass registries — one per primitive
# ---------------------------------------------------------------------------


class ModelRegistry(RegistryBase[Any]):
    """Registry for ``ModelSpec`` objects."""

    @classmethod
    def list_models(cls) -> list[Any]:
        """Return all registered model specifications."""
        return list(cls._entries().values())

    @classmethod
    def find_by_capability(cls, capability: str) -> list[Any]:
        """Find models supporting the given capability (e.g. 'chat', 'code', 'image', 'embeddings')."""
        cap = capability.lower().strip()
        results = []
        for spec in cls._entries().values():
            caps = getattr(spec, "capabilities", ()) or ()
            if any(str(c).lower().strip() == cap for c in caps):
                results.append(spec)
        return results

    @classmethod
    def find_by_family(cls, family: str) -> list[Any]:
        """Find models belonging to a specific model family (e.g. 'qwen', 'llama', 'deepseek')."""
        fam = family.lower().strip()
        return [
            spec
            for spec in cls._entries().values()
            if getattr(spec, "family", "").lower().strip() == fam
        ]

    @classmethod
    def find_by_backend(cls, backend: str) -> list[Any]:
        """Find models supported by or assigned to a specific backend."""
        b = backend.lower().strip()
        results = []
        for spec in cls._entries().values():
            spec_backend = getattr(spec, "backend", "").lower().strip()
            supported = getattr(spec, "supported_engines", ()) or ()
            if spec_backend == b or any(str(e).lower().strip() == b for e in supported):
                results.append(spec)
        return results

    @classmethod
    def find_by_status(cls, status: str) -> list[Any]:
        """Find models matching a specific status."""
        st = status.lower().strip()
        return [
            spec
            for spec in cls._entries().values()
            if getattr(spec, "status", "").lower().strip() == st
        ]

    @classmethod
    def get_or_default(cls, key: str, default: Any = None) -> Any:
        """Safely retrieve model spec or return default if missing."""
        return cls._entries().get(key, default)

    @classmethod
    def to_dict(cls) -> dict[str, dict[str, Any]]:
        """Export all registered models as a dictionary of metadata."""
        out = {}
        for key, spec in cls._entries().items():
            if hasattr(spec, "to_dict"):
                out[key] = spec.to_dict()
            elif isinstance(spec, dict):
                out[key] = dict(spec)
            else:
                out[key] = {"model_id": key, "name": str(spec)}
        return out


class EngineRegistry(RegistryBase[Type["InferenceEngine"]]):
    """Registry for inference engine backends."""


class MemoryRegistry(RegistryBase[Type["MemoryBackend"]]):
    """Registry for memory / retrieval backends."""


class AgentRegistry(RegistryBase[Type["BaseAgent"]]):
    """Registry for agent implementations."""


class ToolRegistry(RegistryBase[Any]):
    """Registry for tool specifications."""


class RouterPolicyRegistry(RegistryBase[Any]):
    """Registry for router policy implementations."""


class LearningRegistry(RegistryBase[Any]):
    """Registry for learning policies."""


class SkillRegistry(RegistryBase[Any]):
    """Registry for skill manifests."""


class SpeechRegistry(RegistryBase[Any]):
    """Registry for speech backend implementations."""


class CompressionRegistry(RegistryBase[Any]):
    """Registry for context compression strategies."""


class TTSRegistry(RegistryBase[Any]):
    """Registry for text-to-speech backend implementations."""


class ConnectorRegistry(RegistryBase[Any]):
    """Registry for local document sources."""


__all__ = [
    "AgentRegistry",
    "CompressionRegistry",
    "ConnectorRegistry",
    "EngineRegistry",
    "LearningRegistry",
    "MemoryRegistry",
    "ModelRegistry",
    "RegistryBase",
    "RouterPolicyRegistry",
    "SkillRegistry",
    "SpeechRegistry",
    "TTSRegistry",
    "ToolRegistry",
]
