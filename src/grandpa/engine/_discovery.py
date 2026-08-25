"""Engine discovery — probe running engines and aggregate available models."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import EngineRegistry
from grandpa.engine._base import InferenceEngine

logger = logging.getLogger(__name__)

# Map registry keys to config host attribute (None = no host arg)
_HOST_MAP: Dict[str, str | None] = {
    "ollama": "ollama_host",
}


def _make_engine(key: str, config: GrandpaConfig) -> InferenceEngine:
    """Instantiate a registered engine with the appropriate config."""
    if not EngineRegistry.contains(key):
        if key == "native":
            from grandpa.runtime.native_adapter import NativeBackendAdapter

            EngineRegistry.register_or_replace("native", NativeBackendAdapter)
        elif key == "ollama":
            from grandpa.runtime.ollama_adapter import OllamaBackendAdapter

            EngineRegistry.register_or_replace("ollama", OllamaBackendAdapter)

    cls = EngineRegistry.get(key)

    if key == "ollama":
        kwargs: dict[str, Any] = {"num_ctx": config.engine.ollama.num_ctx}
        host = getattr(config.engine, "ollama_host", None) or config.engine.ollama.host
        if host:
            kwargs["host"] = host
        return cls(**kwargs)

    if key == "native":
        kwargs = {
            "n_ctx": config.engine.native.n_ctx,
            "n_threads": config.engine.native.n_threads,
            "n_gpu_layers": config.engine.native.n_gpu_layers,
            "use_mmap": config.engine.native.use_mmap,
            "use_mlock": config.engine.native.use_mlock,
            "verbose": config.engine.native.verbose,
        }
        if config.engine.native.models_dir:
            kwargs["models_dir"] = config.engine.native.models_dir
        return cls(**kwargs)

    host_attr = _HOST_MAP.get(key)
    if host_attr is not None:
        host = getattr(config.engine, host_attr, None)
        if host:
            return cls(host=host)
    return cls()


def discover_engines(config: GrandpaConfig) -> List[Tuple[str, InferenceEngine]]:
    """Probe registered engines and return ``[(key, instance)]`` for healthy ones.

    Results are sorted with the config default engine first.
    """
    healthy: List[Tuple[str, InferenceEngine]] = []
    for key in EngineRegistry.keys():
        try:
            engine = _make_engine(key, config)
            if engine.health():
                healthy.append((key, engine))
        except Exception as exc:
            logger.debug("Engine %r failed during discovery: %s", key, exc)
            continue

    default_key = config.engine.default

    def sort_key(item: Tuple[str, Any]) -> Tuple[int, str]:
        return (0 if item[0] == default_key else 1, item[0])

    healthy.sort(key=sort_key)
    return healthy


def discover_models(
    engines: List[Tuple[str, InferenceEngine]],
) -> Dict[str, List[str]]:
    """Call ``list_models()`` on each engine and return a dict."""
    result: Dict[str, List[str]] = {}
    for key, engine in engines:
        try:
            result[key] = engine.list_models()
        except Exception as exc:
            logger.debug("Failed to list models for engine %r: %s", key, exc)
            result[key] = []
    return result


def get_engine(
    config: GrandpaConfig, engine_key: str | None = None
) -> Tuple[str, InferenceEngine] | None:
    """Get a specific engine by key, or the default with fallback.

    Returns ``(key, engine_instance)`` or ``None`` if no engine is available.
    """
    # Build an ordered list of keys to try, then fall back to full discovery.
    keys_to_try: list[str] = []
    if engine_key:
        keys_to_try.append(engine_key)

    default_key = config.engine.default
    if default_key and default_key not in keys_to_try:
        keys_to_try.append(default_key)

    for key in keys_to_try:
        if not EngineRegistry.contains(key):
            continue
        try:
            engine = _make_engine(key, config)
            if engine.health():
                return (key, engine)
        except Exception as exc:
            logger.debug("Engine %r health check failed: %s", key, exc)

    # Fallback to any healthy engine
    healthy = discover_engines(config)
    return healthy[0] if healthy else None


__all__ = ["discover_engines", "discover_models", "get_engine"]
