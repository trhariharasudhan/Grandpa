"""Thin intent router in front of legacy local actions."""

from __future__ import annotations

import logging
from collections import Counter, deque
from threading import RLock
from typing import Any

from grandpa.router.route_models import IntentRoute
from grandpa.router.skill_router import (
    execute_skill_route,
    match_skill_route,
    route_table,
)

logger = logging.getLogger(__name__)

_LOCK = RLock()
_RECENT_ROUTES: deque[dict[str, Any]] = deque(maxlen=80)
_COUNTS: Counter[str] = Counter()


def analyze_intent(request_text: str) -> IntentRoute:
    """Classify a request without executing anything."""
    route = match_skill_route(request_text)
    if route is not None:
        return route

    planner_route = _planner_route(request_text)
    if planner_route is not None:
        return planner_route

    return IntentRoute(
        request_text=request_text,
        intent="legacy_or_chat",
        category="legacy",
        confidence=0.25,
        fallback_reason="No high-confidence skill or planner route matched.",
        execution_source="fallback",
    )


def route_local_intent(request_text: str):
    """Execute high-confidence routed intents, or return None for legacy fallback."""
    route = analyze_intent(request_text)
    if route.can_execute_as_skill:
        try:
            result = execute_skill_route(route)
        except Exception:
            logger.debug(
                "Intent skill route failed for %s", route.skill_name, exc_info=True
            )
            _record(route, "fallback", "skill_error")
            return None
        _record(route, result.status, "skill")
        return result

    if route.can_execute_as_planner:
        try:
            from grandpa.agents.goal_mode import create_goal
            from grandpa.router.legacy_adapter import planner_task_to_local_action

            goal = create_goal(route.request_text, execute=True)
            result = planner_task_to_local_action(route, goal)
        except Exception:
            logger.debug("Intent planner route failed", exc_info=True)
            _record(route, "fallback", "planner_error")
            return None
        _record(route, result.status, "planner")
        return result

    _record(route, "fallback", "legacy")
    return None


def router_diagnostics() -> dict[str, Any]:
    """Return read-only router health and routing counters."""
    with _LOCK:
        recent = list(_RECENT_ROUTES)
        counts = dict(_COUNTS)
    return {
        "status": "ready",
        "router": "intent-router-v1",
        "skill_routes": route_table(),
        "skill_routed_count": counts.get("skill", 0),
        "planner_routed_count": counts.get("planner", 0),
        "legacy_routed_count": counts.get("legacy", 0),
        "fallback_count": counts.get("fallback", 0),
        "risky_route_count": counts.get("risky", 0),
        "recent_routes": recent,
        "local_only": True,
    }


def reset_router_diagnostics() -> None:
    """Clear in-memory router diagnostics for tests."""
    with _LOCK:
        _RECENT_ROUTES.clear()
        _COUNTS.clear()


def _planner_route(request_text: str) -> IntentRoute | None:
    try:
        from grandpa.core.config import load_config
        from grandpa.planner import analyze_request

        include_memory = load_config().agent.context_from_memory
        analysis = analyze_request(request_text, include_memory=include_memory)
    except Exception:
        logger.debug("Planner analysis failed during intent routing", exc_info=True)
        return None
    if (
        analysis.confidence < 0.7
        or not analysis.steps
        or analysis.estimated_risk == "BLOCKED"
    ):
        return None
    if not analysis.workflow_suitable and len(analysis.steps) < 2:
        return None
    return IntentRoute(
        request_text=request_text,
        intent=analysis.intent.replace(" ", "_"),
        category="planner",
        confidence=analysis.confidence,
        skill_name="",
        params={
            "required_skills": list(analysis.required_skills),
            "goal_class": analysis.goal_class,
        },
        risk_level=analysis.estimated_risk,
        approval_required=bool(analysis.approval_needed_steps),
        execution_source="planner",
        planner_suitable=analysis.workflow_suitable,
    )


def _record(route: IntentRoute, status: str, source: str) -> None:
    item = route.to_dict()
    item["status"] = status
    item["route_source"] = source
    with _LOCK:
        _RECENT_ROUTES.appendleft(item)
        _COUNTS[source] += 1
        if route.risk_level in {"MEDIUM", "HIGH", "BLOCKED"} or route.approval_required:
            _COUNTS["risky"] += 1


__all__ = [
    "analyze_intent",
    "reset_router_diagnostics",
    "route_local_intent",
    "router_diagnostics",
]
