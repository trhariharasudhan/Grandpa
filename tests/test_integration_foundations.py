from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa import (
    communication_integration,
    future_features,
    iot_smart_home,
    mobile_integration,
    real_world_tasks,
)
from grandpa.server.routes import router


def test_mobile_pairing_and_notification_redaction(tmp_path):
    store = mobile_integration.MobileBridgeStore(tmp_path / "mobile.db")
    pairing = store.create_pairing("Pixel")
    assert pairing["local_only"] is True
    assert store.confirm_pairing(pairing["device_id"], pairing["pairing_code"])
    note = store.record_notification(pairing["device_id"], "message", "SMS", "OTP code", "password token")
    assert "redacted" in note["summary"]
    assert mobile_integration.plan_remote_command("send message").status == "requires_confirmation"


def test_communication_reply_and_aggregation(tmp_path):
    store = communication_integration.CommunicationStore(tmp_path / "comm.db")
    store.add_notification("gmail", "Team", "Build status", "All green")
    reply = communication_integration.reply_plan("gmail", "Team", "Looks good", store=store)
    assert reply.status == "requires_confirmation"
    aggregate = communication_integration.aggregate_notifications(store=store)
    assert aggregate.data["unread_counts"]["gmail"] == 1


def test_real_world_purchase_protection(tmp_path):
    store = real_world_tasks.RealWorldStore(tmp_path / "real.db")
    blocked = real_world_tasks.shopping_plan("buy laptop and checkout now", store=store)
    assert blocked.status == "blocked"
    booking = real_world_tasks.booking_plan("flights", "Chennai to Delhi", store=store)
    assert booking.status == "handled"


def test_iot_local_only_discovery_and_simulation(tmp_path):
    store = iot_smart_home.IoTStore(tmp_path / "iot.db")
    assert iot_smart_home.discovery_plan("192.168.1.0/24").status == "handled"
    assert iot_smart_home.discovery_plan("8.8.8.0/24").status == "blocked"
    control = iot_smart_home.device_control_plan("Demo Light", "turn on")
    assert control.data["simulated"] is True
    assert iot_smart_home.diagnostics(store)["devices"]


def test_future_features_are_simulation_marked(tmp_path):
    store = future_features.FutureFeatureStore(tmp_path / "future.db")
    overlay = future_features.overlay_simulation()
    assert overlay.data["simulated"] is True
    diagnostics = future_features.diagnostics(store)
    assert diagnostics["safety"]["no_fake_hardware_claims"] is True
    assert diagnostics["hardware"]["real_hardware_connected"] is False


def test_new_integration_routes():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    for path in [
        "/v1/mobile/diagnostics",
        "/v1/communication/diagnostics",
        "/v1/real-world/diagnostics",
        "/v1/iot/diagnostics",
        "/v1/future/diagnostics",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    assert client.post("/v1/mobile/pairing", json={"name": "Pixel"}).status_code == 200
    assert client.post("/v1/real-world/shopping-plan", json={"query": "checkout payment"}).json()["status"] == "blocked"
    assert client.post("/v1/future/overlay-simulation").json()["simulated"] is True
