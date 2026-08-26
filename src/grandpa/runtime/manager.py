"""Runtime manager to retrieve and resolve active ModelRuntime instances."""

from __future__ import annotations

from typing import Optional

from grandpa.core.config import GrandpaConfig, load_config
from grandpa.core.registry import EngineRegistry
from grandpa.runtime.interface import ModelRuntime


def get_runtime(
    config: Optional[GrandpaConfig] = None,
    engine_key: Optional[str] = None,
) -> ModelRuntime:
    """Resolve and return the active ModelRuntime backend adapter.

    The core layer and agents interact with the returned ModelRuntime interface
    without depending on provider-specific details.
    """
    cfg = config or load_config()
    key = engine_key or cfg.engine.default or "ollama"

    if not EngineRegistry.contains(key):
        if key == "ollama":
            from grandpa.runtime.ollama_adapter import OllamaBackendAdapter

            EngineRegistry.register_or_replace("ollama", OllamaBackendAdapter)
        elif key == "native":
            from grandpa.runtime.native_adapter import NativeBackendAdapter

            EngineRegistry.register_or_replace("native", NativeBackendAdapter)
        else:
            raise RuntimeError(
                f"Requested model runtime adapter '{key}' is not registered."
            )

    cls = EngineRegistry.get(key)
    if key == "ollama":
        kwargs = {"num_ctx": cfg.engine.ollama.num_ctx}
        if cfg.engine.ollama.host:
            kwargs["host"] = cfg.engine.ollama.host
        return cls(**kwargs)
    if key == "native":
        kwargs = {
            "n_ctx": cfg.engine.native.n_ctx,
            "n_threads": cfg.engine.native.n_threads,
            "n_gpu_layers": cfg.engine.native.n_gpu_layers,
            "use_mmap": cfg.engine.native.use_mmap,
            "use_mlock": cfg.engine.native.use_mlock,
            "verbose": cfg.engine.native.verbose,
        }
        if cfg.engine.native.models_dir:
            kwargs["models_dir"] = cfg.engine.native.models_dir
        return cls(**kwargs)
    return cls()


__all__ = ["get_runtime"]
