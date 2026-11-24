"""``grandpa server --headless``: the Pironman home-server node (P2).

On a Raspberry Pi there is no desktop, no screen, no microphone and no model.
The headless app keeps only these parts of the API:

* chat (``/v1/chat/completions``), answered by the PC's model over the LAN,
* memory (``/v1/memory``, ``/v1/personal-memory``),
* the scheduler and routines (``/v1/routines``), with workflow triggers run
  by the same background daemon as on the PC,
* devices (``/v1/devices``), so phones can pair with the home server,
* workflows, read-only (``/v1/workflows``),
* ``/v1/models`` (read), ``/v1/info`` and ``/health``.

Every other ``/v1/``, ``/api/`` and ``/ingest`` route answers 404, so nothing
that drives a desktop, a browser or files is reachable on the node. This
filter runs in front of authentication and does not replace it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

#: Route prefixes the headless node serves. A prefix matches itself and
#: anything under it after a "/".
HEADLESS_PREFIXES = (
    "/v1/chat/completions",
    "/v1/memory",
    "/v1/personal-memory",
    "/v1/routines",
    "/v1/devices",
    "/v1/workflows",
    "/v1/info",
)

#: Allowed for reading only (GET/HEAD): pulling or deleting a model makes no
#: sense on a node that has none.
HEADLESS_READ_ONLY_PREFIXES = ("/v1/models",)

_FILTERED_ROOTS = ("/v1/", "/api/", "/ingest")


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def headless_allows(path: str, method: str = "GET") -> bool:
    """True when the headless node serves ``method path``."""
    if not any(path == r.rstrip("/") or path.startswith(r) for r in _FILTERED_ROOTS):
        return True
    if any(_matches(path, p) for p in HEADLESS_PREFIXES):
        return True
    if method.upper() in {"GET", "HEAD"} and any(
        _matches(path, p) for p in HEADLESS_READ_ONLY_PREFIXES
    ):
        return True
    return False


class HeadlessRouteFilter:
    """Answer 404 for every API route the headless node does not serve."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        if kind in {"http", "websocket"}:
            path = scope.get("path", "")
            method = scope.get("method", "GET") if kind == "http" else "GET"
            if not headless_allows(path, method):
                if kind == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                response = JSONResponse(
                    {"detail": "Not available on the headless home server."},
                    status_code=404,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


workflow_router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


@workflow_router.get("")
def list_workflows() -> dict[str, Any]:
    """Workflow files and their triggers on this node. Read-only."""
    from grandpa.workflow.loader import list_workflow_files, workflow_dir

    workflows = [p.stem for p in list_workflow_files()]
    triggers: list[dict[str, Any]] = []
    try:
        from grandpa.workflow.triggers import TriggerStore

        for t in TriggerStore().list():
            triggers.append(
                {
                    "id": t.id,
                    "workflow": t.workflow,
                    "kind": t.kind,
                    "when": t.describe(),
                    "enabled": t.enabled,
                    "next_run_at": t.next_run_at,
                    "last_status": t.last_status,
                }
            )
    except Exception:  # noqa: BLE001 - no trigger db yet is not an error
        triggers = []
    return {
        "directory": str(workflow_dir()),
        "workflows": workflows,
        "triggers": triggers,
    }


__all__ = [
    "HEADLESS_PREFIXES",
    "HEADLESS_READ_ONLY_PREFIXES",
    "HeadlessRouteFilter",
    "headless_allows",
    "workflow_router",
]
