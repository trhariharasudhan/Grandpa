"""Phone pairing over the LAN (D1).

* ``POST /v1/devices/pair`` -- ``{"code": "123456", "name": "Pixel"}`` →
  ``{"device_id", "name", "token"}``. Works only while ``grandpa devices pair``
  has a window open on the PC; the token is shown this once.
* ``GET /v1/devices/me`` -- with ``Authorization: Bearer gp_dev_...``, says
  which device the token belongs to. The phone's "am I still paired?" check.
* ``POST /v1/devices/command`` -- ``{"text": "set volume to 30"}`` (D2).
* ``POST /v1/devices/voice`` -- raw audio body, ``?format=wav`` (D2).

Both run the action-layer tool loop; anything needing a yes is not done,
listed in ``needs_pc_confirmation``, and kept as a request in ``pending``
for someone at the PC to approve (D4).

* ``GET /v1/devices/pending`` -- this phone's requests and what became of
  them (D4). Read-only: there is no route that approves.

* ``GET /v1/devices/notifications?after=<id>`` -- reminders and other
  notifications made since the phone last asked (D3).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from grandpa.devices import DeviceStore, PairingError
from grandpa.devices.commands import (
    MAX_AUDIO_BYTES,
    CommandRefused,
    RateLimiter,
    run_phone_command,
)

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


def _device(request: Request):
    # Checked here as well as in the middleware, so the answer is the same
    # whether or not the server runs with an API key.
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    device = _store(request).authenticate(token) if scheme.lower() == "bearer" else None
    if device is None:
        raise HTTPException(status_code=401, detail="Not a paired device")
    return device


@router.get("/v1/devices/me")
async def device_me(request: Request) -> dict[str, Any]:
    device = _device(request)
    return {"device_id": device.device_id, "name": device.name, "paired": True}


# -- D2: commands and voice from the phone -----------------------------------


class CommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _limiter(request: Request) -> RateLimiter:
    limiter = getattr(request.app.state, "device_rate_limiter", None)
    if limiter is None:
        limiter = RateLimiter()
        request.app.state.device_rate_limiter = limiter
    return limiter


def _run(request: Request, device, text: str) -> dict[str, Any]:
    store = _store(request)
    if not _limiter(request).allow(device.device_id):
        store.log_event(
            "command_refused", device_id=device.device_id, detail="rate limit"
        )
        raise HTTPException(status_code=429, detail="Too many commands. Wait a minute.")
    try:
        result = run_phone_command(
            text,
            engine=getattr(request.app.state, "engine", None),
            model=getattr(request.app.state, "model", "") or "",
            device_id=device.device_id,
            store=store,
        )
    except CommandRefused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return result.as_dict()


# Plain ``def``: the tool loop blocks on the model, so FastAPI runs these in
# its thread pool instead of on the event loop.
@router.post("/v1/devices/command")
def device_command(req: CommandRequest, request: Request) -> dict[str, Any]:
    """``{"text": "set volume to 30"}`` → ``{"reply", "actions", "needs_pc_confirmation"}``."""
    device = _device(request)
    return {"text": req.text, **_run(request, device, req.text)}


@router.get("/v1/devices/notifications")
async def device_notifications(
    request: Request, after: int = 0, limit: int = 50
) -> dict[str, Any]:
    """New notifications for this phone (D3): ``?after=<last id seen>``.

    The phone keeps ``last_id`` and sends it back as ``after`` next time.
    """
    device = _device(request)
    items = _store(request).notifications_for(device, after=after, limit=limit)
    return {
        "notifications": [n.as_dict() for n in items],
        "last_id": items[-1].id if items else max(0, after),
    }


@router.get("/v1/devices/pending")
async def device_pending(request: Request, limit: int = 20) -> dict[str, Any]:
    """This phone's requests that need a yes on the PC, newest first (D4)."""
    from grandpa.devices.approvals import list_pending

    device = _device(request)
    items = list_pending(
        _store(request),
        device_id=device.device_id,
        include_decided=True,
        limit=max(1, min(limit, 50)),
    )
    return {"pending": [p.as_dict() for p in items]}


@router.post("/v1/devices/voice")
async def device_voice(
    request: Request, format: str = "wav", language: str | None = None
) -> dict[str, Any]:
    """Raw audio in the body (``?format=wav``); transcribed, then run as a command."""
    device = _device(request)
    audio = await request.body()
    return await run_in_threadpool(_voice, request, device, audio, format, language)


def _voice(
    request: Request, device, audio: bytes, format: str, language: str | None
) -> dict[str, Any]:
    if not audio:
        raise HTTPException(status_code=400, detail="No audio was sent.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too long.")
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(
            status_code=503, detail="Speech-to-text is not running on the PC."
        )
    fmt = "".join(ch for ch in format.lower() if ch.isalnum())[:8] or "wav"
    try:
        heard = backend.transcribe(audio, format=fmt, language=language or None)
    except Exception as exc:
        _store(request).log_event(
            "voice_failed", device_id=device.device_id, detail=str(exc)
        )
        raise HTTPException(
            status_code=422, detail="Could not understand that recording."
        ) from exc
    text = (getattr(heard, "text", "") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="I did not hear any words.")
    return {"text": text, **_run(request, device, text)}
