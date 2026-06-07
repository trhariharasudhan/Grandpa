from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa import mobile_integration
from grandpa.server.routes import router


def test_pairing_token_heartbeat_and_diagnostics(tmp_path):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    pairing = store.create_pairing("Pixel")
    assert pairing["qr_payload"]["type"] == "grandpa_pairing"
    confirmed = store.confirm_pairing(
        pairing["device_id"],
        pairing["pairing_code"],
        status={"battery": 81, "charging": True, "connectivity": "wifi"},
    )

    assert confirmed["ok"] is True
    assert store.authenticate(pairing["device_id"], confirmed["trusted_token"])
    heartbeat = store.update_status(
        pairing["device_id"],
        {
            "battery": 82,
            "charging": False,
            "connectivity": "wifi",
            "websocket_state": "connected",
            "notification_listener_enabled": True,
            "microphone_ready": True,
            "background_heartbeat": True,
        },
    )
    assert heartbeat["online"] is True
    assert heartbeat["permissions"]["notifications"] is True
    assert heartbeat["permissions"]["voice_relay"] is True

    diagnostics = mobile_integration.diagnostics(store)
    assert diagnostics["connected_devices"] == 1
    assert diagnostics["online_devices"] == 1
    assert diagnostics["websocket"]["status"] == "online"
    assert diagnostics["permission_state"]["notification_listener"] == "ready"
    assert diagnostics["relay_state"]["voice_relay"] == "ready"
    assert diagnostics["features"]["trusted_device_tokens"] is True
    assert diagnostics["features"]["qr_pairing"] is True


def test_notification_redaction_and_clipboard_approval(tmp_path):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    pairing = store.create_pairing("Phone")
    confirmed = store.confirm_pairing(pairing["device_id"], pairing["pairing_code"])
    note = store.record_notification(
        pairing["device_id"],
        "message",
        "SMS",
        "OTP code",
        "password token card",
    )
    clip = mobile_integration.clipboard_sync_plan(pairing["device_id"], "phone_to_desktop")

    assert confirmed["ok"] is True
    assert "redacted" in note["summary"]
    assert clip.status == "requires_confirmation"
    assert clip.data["content_redacted"] is True


def test_remote_command_and_voice_relay_risk_classification(tmp_path):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    safe = mobile_integration.plan_remote_command("run my morning routine", device_id="phone")
    risky = mobile_integration.plan_remote_command("send message to mom", device_id="phone")
    voice = mobile_integration.voice_relay_plan("what routines do I have?", device_id="phone")

    assert safe.status == "queued"
    assert risky.status == "requires_confirmation"
    assert voice.data["voice_relay"] is True
    recorded = store.record_remote_command("phone", "send message to mom", risky)
    assert recorded["approval_required"] is True


def test_mobile_push_queue_redacts_and_marks_delivered(tmp_path):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    pairing = store.create_pairing("Pixel")
    store.confirm_pairing(pairing["device_id"], pairing["pairing_code"])

    queued = store.queue_push_notification(pairing["device_id"], "Grandpa", "token password")
    pending = store.pending_outbox(pairing["device_id"])
    delivered = store.mark_outbox_delivered([queued["id"]])

    assert pending[0]["payload"]["body"] == "[redacted sensitive mobile content]"
    assert delivered == 1
    assert store.pending_outbox(pairing["device_id"]) == []


def test_mobile_http_routes_use_persistent_store(tmp_path, monkeypatch):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    monkeypatch.setattr(mobile_integration, "MobileBridgeStore", lambda: store)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    pairing = client.post("/v1/mobile/pairing", json={"name": "Pixel"}).json()
    confirmed = client.post(
        "/v1/mobile/pairing/confirm",
        json={
            "device_id": pairing["device_id"],
            "pairing_code": pairing["pairing_code"],
            "status": {"battery": 70, "charging": True},
        },
    ).json()
    heartbeat = client.post(
        "/v1/mobile/heartbeat",
        json={
            "device_id": pairing["device_id"],
            "trusted_token": confirmed["trusted_token"],
            "status": {"battery": 71, "charging": False},
        },
    )
    notification = client.post(
        "/v1/mobile/notifications",
        json={
            "device_id": pairing["device_id"],
            "trusted_token": confirmed["trusted_token"],
            "kind": "message",
            "app": "SMS",
            "title": "Hello",
            "summary": "OTP token",
        },
    )

    assert heartbeat.status_code == 200
    assert notification.status_code == 200
    push = client.post(
        "/v1/mobile/push",
        json={
            "device_id": pairing["device_id"],
            "title": "Grandpa",
            "body": "Routine finished",
        },
    )
    assert push.status_code == 200
    assert client.get(f"/v1/mobile/outbox/{pairing['device_id']}").json()["items"]
    diagnostics = client.get("/v1/mobile/diagnostics").json()
    assert diagnostics["connected_devices"] == 1
    assert diagnostics["online_devices"] == 1
    assert "redacted" in diagnostics["notifications"][0]["summary"]


def test_mobile_websocket_pairing_and_remote_command(tmp_path, monkeypatch):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    monkeypatch.setattr(mobile_integration, "MobileBridgeStore", lambda: store)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with client.websocket_connect("/v1/mobile/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "pair_request", "device_name": "Pixel"})
        pairing = ws.receive_json()
        assert pairing["type"] == "pairing_code"
        ws.send_json(
            {
                "type": "pair_confirm",
                "device_id": pairing["device_id"],
                "pairing_code": pairing["pairing_code"],
                "status": {"battery": 66, "charging": True},
            }
        )
        paired = ws.receive_json()
        assert paired["type"] == "paired"
        ws.send_json({"type": "heartbeat", "status": {"battery": 67, "charging": False}})
        assert ws.receive_json()["type"] == "heartbeat_ack"
        ws.send_json({"type": "remote_command", "command": "desktop status"})
        result = ws.receive_json()
        assert result["type"] == "remote_command_result"
        assert result["status"] == "queued"
