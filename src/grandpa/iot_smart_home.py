"""Local IoT and smart-home simulation foundation for Grandpa."""

from __future__ import annotations

import ipaddress
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_IOT_DB = DEFAULT_CONFIG_DIR / "iot_smart_home.db"


@dataclass(frozen=True)
class IoTResult:
    status: str
    message: str
    data: dict[str, Any]


class IoTStore:
    def __init__(self, db_path: Path | str = DEFAULT_IOT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS iot_devices (
                    id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    address TEXT,
                    simulated INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'offline'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    value TEXT
                )
                """
            )

    def add_simulated_device(self, name: str, kind: str, address: str = "") -> dict[str, Any]:
        device_id = f"sim-{kind}-{abs(hash((name, kind))) % 100000}"
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO iot_devices(id, created_at, name, kind, address, simulated, status) VALUES (?, ?, ?, ?, ?, 1, 'ready')",
                (device_id, time.time(), name, kind, address),
            )
        return {"id": device_id, "name": name, "kind": kind, "address": address, "simulated": True, "status": "ready"}

    def devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM iot_devices ORDER BY created_at DESC").fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def discovery_plan(cidr: str = "192.168.1.0/24") -> IoTResult:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return IoTResult("blocked", "I blocked invalid LAN discovery range.", {"cidr": cidr})
    if not network.is_private:
        return IoTResult("blocked", "IoT discovery is limited to private LAN ranges.", {"cidr": cidr})
    return IoTResult("handled", "Prepared local LAN device discovery simulation.", {"cidr": str(network), "dry_run": True, "local_lan_only": True})


def raspberry_pi_connection_plan(host: str = "raspberrypi.local") -> IoTResult:
    return IoTResult(
        "requires_confirmation",
        "Prepared Raspberry Pi connection workflow. Approval is required before connecting.",
        {"host": host, "protocols": ["http", "ssh optional"], "approval_required": True},
    )


def device_control_plan(device: str, action: str) -> IoTResult:
    risky = action.lower() in {"unlock", "open", "disable alarm", "turn off camera"}
    return IoTResult(
        "requires_confirmation" if risky else "handled",
        "Prepared smart-device control plan." if not risky else "Risky smart-device action requires approval.",
        {"device": device, "action": action, "approval_required": risky, "simulated": True},
    )


def diagnostics(store: IoTStore | None = None) -> dict[str, Any]:
    store = store or IoTStore()
    if not store.devices():
        store.add_simulated_device("Demo Smart Light", "light")
        store.add_simulated_device("Demo Smart Plug", "plug")
    return {
        "status": "ready",
        "devices": store.devices(),
        "raspberry_pi": {"status": "not_connected", "workflow_ready": True},
        "features": {
            "local_lan_discovery": True,
            "smart_light_plug_simulation": True,
            "cctv_monitoring_abstraction": True,
            "sensor_event_workflows": True,
        },
        "safety": {"local_lan_only_default": True, "no_open_remote_exposure": True, "risky_controls_require_approval": True},
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


__all__ = [
    "IoTResult",
    "IoTStore",
    "device_control_plan",
    "diagnostics",
    "discovery_plan",
    "raspberry_pi_connection_plan",
]
