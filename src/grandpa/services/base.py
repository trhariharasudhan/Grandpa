"""Small service-layer helpers for API route facades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ServiceState:
    name: str
    ready: bool
    status: str
    message: str = ""
    dependencies: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ready": self.ready,
            "status": self.status,
            "message": self.message,
            "dependencies": self.dependencies or {},
        }


def safe_call(name: str, func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a service diagnostic without letting optional integrations break APIs."""

    try:
        result = func()
        if isinstance(result, dict):
            return result
        return {"status": "ready", "result": result}
    except Exception as exc:  # pragma: no cover - defensive boundary
        return {
            "status": "unavailable",
            "ready": False,
            "service": name,
            "error": exc.__class__.__name__,
            "message": f"{name} diagnostics are unavailable.",
        }


def summarize_ready(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").lower()
    if payload.get("ready") is False:
        return False
    if payload.get("runtime_ready") is False:
        return False
    if status in {"failed", "error", "unavailable", "unsupported"}:
        return False
    return True
