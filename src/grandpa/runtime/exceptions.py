"""Exceptions for Grandpa Model Runtime and Backend Adapters."""

from __future__ import annotations


class RuntimeConnectionError(Exception):
    """Raised when a model runtime backend is unreachable."""


class RuntimeModelNotFoundError(Exception):
    """Raised when a model runtime is reachable but the requested model is missing."""

    def __init__(self, model: str, message: str | None = None) -> None:
        self.model = model
        super().__init__(message or f"Model not found: {model}")


class RuntimeModelLoadError(Exception):
    """Raised when a model runtime cannot load an installed model."""

    def __init__(self, model: str, message: str, *, low_memory: bool = False) -> None:
        self.model = model
        self.low_memory = low_memory
        super().__init__(message)


class RuntimeModelPullError(Exception):
    """Raised when an explicitly requested model installation fails."""

    def __init__(self, model: str, message: str) -> None:
        self.model = model
        super().__init__(message)


__all__ = [
    "RuntimeConnectionError",
    "RuntimeModelLoadError",
    "RuntimeModelNotFoundError",
    "RuntimeModelPullError",
]
