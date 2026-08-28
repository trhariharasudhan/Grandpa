"""Grandpa Model Runtime subsystem — interface, adapters, and manager."""

from __future__ import annotations

from grandpa.runtime.adapter import BackendAdapter
from grandpa.runtime.interface import ModelRuntime, ResponseFormat, StreamChunk
from grandpa.runtime.manager import get_runtime
from grandpa.runtime.native_adapter import NativeBackendAdapter
from grandpa.runtime.ollama_adapter import OllamaBackendAdapter, normalize_ollama_host

__all__ = [
    "BackendAdapter",
    "ModelRuntime",
    "NativeBackendAdapter",
    "OllamaBackendAdapter",
    "ResponseFormat",
    "StreamChunk",
    "get_runtime",
    "normalize_ollama_host",
]
