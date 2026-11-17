"""D1: pairing over HTTP, and what a device token can and cannot open."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="grandpa[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.devices import DeviceStore
from grandpa.server.auth_middleware import AuthMiddleware
from grandpa.server.device_routes import router as device_router

API_KEY = "gp_sk_test_master"


@pytest.fixture
def store(tmp_path):
    return DeviceStore(tmp_path / "devices.db")


@pytest.fixture
def client(store):
    app = FastAPI()
    app.state.device_store = store
    app.include_router(device_router)

    @app.post("/v1/approvals/{action_id}/approve")
    async def approve(action_id: str):
        return {"approved": action_id}

    @app.get("/v1/models")
    async def models():
        return {"models": []}

    app.add_middleware(AuthMiddleware, api_key=API_KEY, device_store=store)
    return TestClient(app)


def _pair(client, store, name="Pixel"):
    code = store.start_pairing().code
    resp = client.post("/v1/devices/pair", json={"code": code, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_phone_pairs_without_the_api_key(client, store):
    body = _pair(client, store)
    assert body["token"].startswith("gp_dev_")
    me = client.get("/v1/devices/me", headers=_bearer(body["token"]))
    assert me.status_code == 200
    assert me.json() == {
        "device_id": body["device_id"],
        "name": "Pixel",
        "paired": True,
    }


def test_pairing_refused_without_an_open_window(client):
    resp = client.post("/v1/devices/pair", json={"code": "123456", "name": "x"})
    assert resp.status_code == 403
    assert "not open" in resp.json()["detail"]


def test_wrong_code_is_403(client, store):
    code = store.start_pairing().code
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    resp = client.post("/v1/devices/pair", json={"code": wrong, "name": "x"})
    assert resp.status_code == 403


def test_device_token_does_not_open_other_routes(client, store):
    token = _pair(client, store)["token"]
    assert client.get("/v1/models", headers=_bearer(token)).status_code == 401
    resp = client.post("/v1/approvals/abc/approve", headers=_bearer(token))
    assert resp.status_code == 401


def test_only_post_pair_is_open(client):
    # The pairing exemption is the POST alone, not the path for every method.
    assert client.get("/v1/devices/pair").status_code == 401


def test_api_key_still_works_everywhere(client):
    assert client.get("/v1/models", headers=_bearer(API_KEY)).status_code == 200


def test_me_refuses_missing_bad_and_revoked_tokens(client, store):
    assert client.get("/v1/devices/me").status_code == 401
    assert (
        client.get("/v1/devices/me", headers=_bearer("gp_dev_fake")).status_code == 401
    )
    body = _pair(client, store)
    store.revoke(body["device_id"])
    assert (
        client.get("/v1/devices/me", headers=_bearer(body["token"])).status_code == 401
    )


def test_me_with_api_key_is_not_a_device(client):
    # The key passes the middleware, but it is not a paired phone.
    assert client.get("/v1/devices/me", headers=_bearer(API_KEY)).status_code == 401
