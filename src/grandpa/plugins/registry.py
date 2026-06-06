"""Persistent plugin registry state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

try:
    from grandpa.core.config import DEFAULT_CONFIG_DIR
except Exception:  # pragma: no cover
    DEFAULT_CONFIG_DIR = Path.home() / ".grandpa"

_LOCK = RLock()


def get_plugin_state_path() -> Path:
    configured = os.environ.get("GRANDPA_PLUGIN_STATE")
    if configured:
        return Path(configured)
    return DEFAULT_CONFIG_DIR / "plugins_state.json"


def load_plugin_state() -> dict[str, Any]:
    path = get_plugin_state_path()
    if not path.exists():
        return {"plugins": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"plugins": {}}
    except Exception:
        return {"plugins": {}}


def save_plugin_state(state: dict[str, Any]) -> None:
    path = get_plugin_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def is_plugin_enabled(name: str, default: bool = True) -> bool:
    with _LOCK:
        state = load_plugin_state()
        item = dict(state.get("plugins", {}).get(name, {}))
        if "enabled" in item:
            return bool(item["enabled"])
        return default


def set_plugin_enabled(name: str, enabled: bool) -> None:
    with _LOCK:
        state = load_plugin_state()
        plugins = dict(state.get("plugins", {}))
        item = dict(plugins.get(name, {}))
        item["enabled"] = enabled
        plugins[name] = item
        state["plugins"] = plugins
        save_plugin_state(state)


__all__ = ["get_plugin_state_path", "is_plugin_enabled", "load_plugin_state", "set_plugin_enabled"]
