"""Future-facing Grandpa feature abstractions and simulation diagnostics."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_FUTURE_DB = DEFAULT_CONFIG_DIR / "future_features.db"


@dataclass(frozen=True)
class FutureResult:
    status: str
    message: str
    data: dict[str, Any]


class FutureFeatureStore:
    def __init__(self, db_path: Path | str = DEFAULT_FUTURE_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS future_connectors (
                    id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )

    def ensure_demo_connectors(self) -> None:
        for item in [
            ("avatar_presence", "avatar", "Grandpa Presence", "simulation", "ready"),
            ("ar_overlay", "overlay", "AR Overlay", "simulation", "foundation"),
            ("wearable_bridge", "wearable", "Wearable Bridge", "simulation", "foundation"),
            ("drone_connector", "device", "Drone Connector", "simulation", "placeholder"),
            ("car_connector", "device", "Car Connector", "simulation", "placeholder"),
        ]:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO future_connectors(id, created_at, kind, name, mode, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (item[0], time.time(), item[1], item[2], item[3], item[4]),
                )

    def connectors(self) -> list[dict[str, Any]]:
        self.ensure_demo_connectors()
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM future_connectors ORDER BY created_at ASC").fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def overlay_simulation() -> FutureResult:
    return FutureResult(
        "handled",
        "Prepared assistant-presence overlay simulation.",
        {
            "avatar_state": "idle",
            "overlay_channels": ["desktop HUD", "screen hints", "voice state"],
            "simulated": True,
        },
    )


def connector_plan(kind: str) -> FutureResult:
    return FutureResult(
        "handled",
        f"Prepared {kind} connector abstraction in simulation mode.",
        {"kind": kind, "real_hardware_connected": False, "simulated": True, "approval_required_for_control": True},
    )


def diagnostics(store: FutureFeatureStore | None = None) -> dict[str, Any]:
    store = store or FutureFeatureStore()
    return {
        "status": "ready",
        "avatar": {"state": "idle", "personality": "Grandpa", "simulated": True},
        "overlay": {"desktop_hud": True, "ar_overlay": "simulation only", "assistant_presence": True},
        "connectors": store.connectors(),
        "hardware": {"wearables": "abstraction", "drone": "simulation", "car": "simulation", "real_hardware_connected": False},
        "safety": {"simulation_marked": True, "no_fake_hardware_claims": True, "device_control_requires_approval": True},
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


__all__ = [
    "FutureFeatureStore",
    "FutureResult",
    "connector_plan",
    "diagnostics",
    "overlay_simulation",
]
