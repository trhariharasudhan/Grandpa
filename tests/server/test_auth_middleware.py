"""Tests for API key authentication middleware."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="grandpa[server] not installed")

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from grandpa.server.auth_middleware import AuthMiddleware


def _make_app(api_key: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=api_key)

    @app.get("/v1/models")
    async def models():
        return {"models": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/public/ping")
    async def public_ping():
        return {"status": "ok"}

    @app.websocket("/v1/events")
    async def events(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("connected")
        await websocket.close()

    return app


@pytest.fixture
def client():
    return TestClient(_make_app("oj_sk_test123"))


class TestAuthMiddleware:
    def test_rejects_missing_auth_header(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert "missing" in resp.json()["detail"].lower()

    def test_rejects_wrong_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_accepts_valid_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer oj_sk_test123"},
        )
        assert resp.status_code == 200

    def test_health_exempt(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_non_api_route_exempt(self, client):
        resp = client.get("/public/ping")
        assert resp.status_code == 200

    def test_no_key_configured_allows_all(self):
        client = TestClient(_make_app(""))
        resp = client.get("/v1/models")
        assert resp.status_code == 200

    @pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong"}])
    def test_rejects_unauthenticated_websocket(self, client, headers):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/v1/events", headers=headers or {}):
                pass
        assert exc_info.value.code == 1008

    def test_accepts_authenticated_websocket(self, client):
        with client.websocket_connect(
            "/v1/events",
            headers={"Authorization": "Bearer oj_sk_test123"},
        ) as websocket:
            assert websocket.receive_text() == "connected"
