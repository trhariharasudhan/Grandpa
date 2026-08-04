"""Persistent Application Manager registry."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from grandpa.apps.models import ApplicationInfo
from grandpa.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

DEFAULT_APP_REGISTRY_PATH = DEFAULT_CONFIG_DIR / "apps.json"
LEGACY_APP_INVENTORY_PATH = DEFAULT_CONFIG_DIR / "app_inventory.json"
APP_REGISTRY_SCHEMA_VERSION = 2


def load_app_registry(
    *, store_path: Path = DEFAULT_APP_REGISTRY_PATH
) -> list[ApplicationInfo]:
    path = _existing_store_path(store_path)
    if not path.exists():
        logger.info("Application cache missing: %s", path)
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Application cache load failed: %s", exc)
        return []
    if not _supported_schema(payload):
        logger.warning(
            "Application cache schema is stale; run `grandpa apps refresh`: %s", path
        )
        return []
    raw_apps = _raw_app_list(payload)
    apps = [
        ApplicationInfo.from_dict(item) for item in raw_apps if isinstance(item, dict)
    ]
    logger.info("Application cache loaded: %s apps from %s", len(apps), path)
    return apps


def save_app_registry(
    apps: list[ApplicationInfo], *, store_path: Path = DEFAULT_APP_REGISTRY_PATH
) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": APP_REGISTRY_SCHEMA_VERSION,
        "last_scan": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "applications": [app.to_dict() for app in apps],
    }
    store_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    logger.info("Application cache saved: %s apps to %s", len(apps), store_path)


def _existing_store_path(store_path: Path) -> Path:
    if store_path.exists():
        return store_path
    if store_path == DEFAULT_APP_REGISTRY_PATH and LEGACY_APP_INVENTORY_PATH.exists():
        return LEGACY_APP_INVENTORY_PATH
    return store_path


def _raw_app_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        raw = payload.get("applications", payload.get("apps", []))
        return raw if isinstance(raw, list) else []
    return []


def app_registry_needs_refresh(*, store_path: Path = DEFAULT_APP_REGISTRY_PATH) -> bool:
    path = _existing_store_path(store_path)
    if not path.exists():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return not _supported_schema(payload)


def _supported_schema(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == APP_REGISTRY_SCHEMA_VERSION
    )


__all__ = [
    "APP_REGISTRY_SCHEMA_VERSION",
    "DEFAULT_APP_REGISTRY_PATH",
    "LEGACY_APP_INVENTORY_PATH",
    "app_registry_needs_refresh",
    "load_app_registry",
    "save_app_registry",
]
