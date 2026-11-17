"""Phone pairing over the LAN (D1).

* ``POST /v1/devices/pair`` -- ``{"code": "123456", "name": "Pixel"}`` →
  ``{"device_id", "name", "token"}``. Works only while ``grandpa devices pair``
  has a window open on the PC; the token is shown this once.
* ``GET /v1/devices/me`` -- with ``Authorization: Bearer gp_dev_...``, says
  which device the token belongs to. The phone's "am I still paired?" check.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from grandpa.devices import DeviceStore, PairingError

router = APIRouter()


class PairRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    name: str = Field("Phone", max_length=80)


def _store(request: Request) -> DeviceStore:
    store = getattr(request.app.state, "device_store", None)
    if store is None:
        store = DeviceStore()
        request.app.state.device_store = store
    return store


@router.post("/v1/devices/pair")
async def pair_device(req: PairRequest, request: Request) -> dict[str, Any]:
    try:
        paired = _store(request).complete_pairing(req.code, req.name)
    except PairingError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "device_id": paired.device.device_id,
        "name": paired.device.name,
        "token": paired.token,
    }


@router.get("/v1/devices/me")
async def device_me(request: Request) -> dict[str, Any]:
    # Checked here as well as in the middleware, so the answer is the same
    # whether or not the server runs with an API key.
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    device = _store(request).authenticate(token) if scheme.lower() == "bearer" else None
    if device is None:
        raise HTTPException(status_code=401, detail="Not a paired device")
    return {"device_id": device.device_id, "name": device.name, "paired": True}
