"""Action-module router used by the legacy local action facade."""

from __future__ import annotations

from collections import Counter, deque
from threading import RLock
from typing import Any, Callable

from grandpa.actions import (
    browser_actions,
    desktop_actions,
    fallback_actions,
    memory_actions,
    planner_actions,
    plugin_actions,
    vision_actions,
    workflow_actions,
)

_LOCK = RLock()
_COUNTS: Counter[str] = Counter()
_RECENT: deque[dict[str, Any]] = deque(maxlen=80)

Handler = Callable[[str], Any]
_HANDLERS: tuple[tuple[str, Handler, int], ...] = (
    ("desktop", desktop_actions.try_handle, len(desktop_actions.HANDLERS)),
    ("browser", browser_actions.try_handle, len(browser_actions.HANDLERS)),
    ("vision", vision_actions.try_handle, len(vision_actions.HANDLERS)),
    ("workflow", workflow_actions.try_handle, len(workflow_actions.HANDLERS)),
    ("planner", planner_actions.try_handle, len(planner_actions.HANDLERS)),
    ("plugins", plugin_actions.try_handle, len(plugin_actions.HANDLERS)),
    ("memory", memory_actions.try_handle, len(memory_actions.HANDLERS)),
    ("fallback", fallback_actions.try_handle, 0),
)


def route_action(command: str):
    """Return a migrated local-action result, or None for legacy fallback."""

    for domain, handler, _count in _HANDLERS:
        result = handler(command)
        if result is not None:
            _record(command, domain, "migrated", getattr(result, "kind", "unknown"))
            return result
    _record(command, "legacy", "fallback", "")
    return None


def action_diagnostics() -> dict[str, Any]:
    with _LOCK:
        counts = dict(_COUNTS)
        recent = list(_RECENT)
    migrated_handlers = {
        domain: count
        for domain, _handler, count in _HANDLERS
        if domain != "fallback" and count > 0
    }
    migrated_count = sum(migrated_handlers.values())
    legacy_count = _legacy_handler_estimate()
    total = migrated_count + legacy_count
    coverage = round(migrated_count / total, 3) if total else 0.0
    return {
        "status": "ready",
        "router": "local-actions-decomposition-v1",
        "migrated_handlers": migrated_handlers,
        "migrated_count": migrated_count,
        "legacy_handlers": {
            "desktop": "apps, windows, clipboard write/read execution, file operations",
            "browser": "navigation, DOM commands, form/click/media actions",
            "vision": "screen context and screenshot execution",
            "workflow": "routine/reminder creation and workflow execution",
            "planner": "multi-step agent plan execution",
            "memory": "conversation memory commands",
            "communication": "communication/mobile/IoT foundations",
            "fallback": "LLM fallback and unsupported commands",
        },
        "legacy_count": legacy_count,
        "routing_coverage": coverage,
        "fallback_count": counts.get("fallback", 0),
        "migrated_route_count": counts.get("migrated", 0),
        "recent_routes": recent,
        "local_only": True,
    }


def action_audit_summary() -> dict[str, Any]:
    diagnostics = action_diagnostics()
    return {
        "desktop": "partially migrated: summary, monitors, diagnostics, clipboard history",
        "browser": "partially migrated: diagnostics only",
        "vision": "partially migrated: screen and visual diagnostics",
        "workflow": "partially migrated: status/diagnostics",
        "planner": "partially migrated: diagnostics",
        "memory": "legacy",
        "plugins": "partially migrated: skills/plugins diagnostics",
        "communication": "legacy",
        "fallback": "legacy fallback preserved",
        "coverage": diagnostics["routing_coverage"],
    }


def reset_action_diagnostics() -> None:
    with _LOCK:
        _COUNTS.clear()
        _RECENT.clear()


def _record(command: str, domain: str, source: str, kind: str) -> None:
    with _LOCK:
        _COUNTS[source] += 1
        if source == "fallback":
            _COUNTS["fallback"] += 1
        _RECENT.appendleft(
            {
                "request": command,
                "domain": domain,
                "source": source,
                "kind": kind,
            }
        )


def _legacy_handler_estimate() -> int:
    # Conservative, documented estimate of branches intentionally left in
    # local_actions.py during this low-risk migration phase.
    return 46


__all__ = [
    "action_audit_summary",
    "action_diagnostics",
    "reset_action_diagnostics",
    "route_action",
]
