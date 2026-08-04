"""Lightweight AI orchestration helpers for Grandpa.

This module stays intentionally local and deterministic. It does not replace
the existing engine, agent, memory, or workflow systems; it adds a small
planning and routing layer that can explain what Grandpa is about to do and
choose safer model fallbacks when the requested model is unavailable.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from grandpa.learning.routing.complexity import score_complexity

_EMBEDDING_HINTS = ("embed", "embedding", "nomic-embed")
_LOCAL_PRIORITY = (
    "qwen2.5:3b",
    "qwen3:4b",
    "gemma3:4b",
    "llama3.2",
    "mistral",
)


@dataclass(frozen=True)
class ModelRoutingDecision:
    requested_model: str
    selected_model: str
    engine_hint: str
    confidence: float
    reason: str
    fallback_used: bool = False
    local_preferred: bool = True
    cloud_allowed: bool = False
    task_type: str = "general"
    complexity_tier: str = "simple"

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_model": self.requested_model,
            "selected_model": self.selected_model,
            "engine_hint": self.engine_hint,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "local_preferred": self.local_preferred,
            "cloud_allowed": self.cloud_allowed,
            "task_type": self.task_type,
            "complexity_tier": self.complexity_tier,
        }


@dataclass(frozen=True)
class PlanStep:
    name: str
    purpose: str
    tool_hint: str = "chat"
    risk: str = "LOW"
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "tool_hint": self.tool_hint,
            "risk": self.risk,
            "status": self.status,
        }


@dataclass(frozen=True)
class AIPlan:
    query: str
    task_type: str
    priority: float
    complexity: dict[str, Any]
    routing: ModelRoutingDecision
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)
    tool_order: tuple[str, ...] = field(default_factory=tuple)
    memory_queries: tuple[str, ...] = field(default_factory=tuple)
    self_analysis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "task_type": self.task_type,
            "priority": round(self.priority, 3),
            "complexity": self.complexity,
            "routing": self.routing.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "tool_order": list(self.tool_order),
            "memory_queries": list(self.memory_queries),
            "self_analysis": self.self_analysis,
            "local_only": True,
        }


def classify_task(query: str) -> str:
    text = query.lower().strip()
    if not text:
        return "general"
    if re.search(r"\b(browser|webpage|youtube|tab|link|button|download|gmail)\b", text):
        return "browser"
    if re.search(r"\b(screen|screenshot|visible|ocr|error message|popup)\b", text):
        return "screen"
    if re.search(
        r"\b(open|close|minimize|maximize|focus|volume|clipboard|type|click|scroll|window)\b",
        text,
    ):
        return "pc_control"
    if re.search(
        r"\b(file|folder|pdf|document|note|downloads|rename|copy|move)\b", text
    ):
        return "files"
    if re.search(r"\b(remember|recall|preference|project|what did i)\b", text):
        return "memory"
    if re.search(r"\b(routine|remind|schedule|every day|every hour|timer)\b", text):
        return "workflow"
    if re.search(r"\b(code|python|fastapi|bug|test|debug|function|class)\b", text):
        return "developer"
    if re.search(r"\b(research|compare|analyze|summarize|plan|strategy)\b", text):
        return "reasoning"
    return "general"


def score_task_priority(query: str, task_type: str) -> float:
    text = query.lower()
    score = 0.35
    if task_type in {"pc_control", "screen", "browser", "workflow"}:
        score += 0.18
    if any(
        word in text
        for word in ("urgent", "now", "asap", "important", "error", "failed", "crash")
    ):
        score += 0.25
    if any(word in text for word in ("later", "someday", "maybe")):
        score -= 0.12
    if len(query) > 300:
        score += 0.08
    return max(0.0, min(1.0, score))


def choose_model(
    query: str,
    *,
    requested_model: str = "",
    available_models: Iterable[str] = (),
    cloud_allowed: bool = False,
) -> ModelRoutingDecision:
    # Retained as a compatibility argument for API callers. Grandpa's runtime
    # is local-only, so a caller cannot enable cloud routing here.
    del cloud_allowed
    models = [model for model in dict.fromkeys(available_models) if model]
    complexity = score_complexity(query)
    task_type = classify_task(query)
    local_preferred = task_type in {
        "pc_control",
        "screen",
        "files",
        "memory",
        "workflow",
        "browser",
    }
    available = set(models)

    if requested_model and requested_model in available:
        return ModelRoutingDecision(
            requested_model=requested_model,
            selected_model=requested_model,
            engine_hint=_engine_hint(requested_model),
            confidence=0.96,
            reason="Requested model is available.",
            local_preferred=local_preferred,
            cloud_allowed=False,
            task_type=task_type,
            complexity_tier=complexity.tier,
        )

    non_embedding = [
        model
        for model in models
        if not any(hint in model.lower() for hint in _EMBEDDING_HINTS)
    ]
    selected = ""
    reason = ""
    if non_embedding:
        selected = _best_match(non_embedding, _LOCAL_PRIORITY) or non_embedding[0]
        reason = "Local-first routing selected an available local model."

    if selected:
        return ModelRoutingDecision(
            requested_model=requested_model,
            selected_model=selected,
            engine_hint=_engine_hint(selected),
            confidence=0.82 if requested_model != selected else 0.9,
            reason=reason,
            fallback_used=bool(requested_model and requested_model != selected),
            local_preferred=local_preferred,
            cloud_allowed=False,
            task_type=task_type,
            complexity_tier=complexity.tier,
        )

    return ModelRoutingDecision(
        requested_model=requested_model,
        selected_model=requested_model,
        engine_hint=_engine_hint(requested_model),
        confidence=0.2,
        reason="No available model list was provided; keeping the requested model.",
        fallback_used=False,
        local_preferred=local_preferred,
        cloud_allowed=False,
        task_type=task_type,
        complexity_tier=complexity.tier,
    )


def build_plan(
    query: str,
    *,
    requested_model: str = "",
    available_models: Iterable[str] = (),
    cloud_allowed: bool = False,
) -> AIPlan:
    complexity = score_complexity(query)
    routing = choose_model(
        query,
        requested_model=requested_model,
        available_models=available_models,
        cloud_allowed=cloud_allowed,
    )
    task_type = routing.task_type
    steps = tuple(_steps_for_task(query, task_type, complexity.tier))
    tool_order = tuple(_tool_order_for_task(task_type))
    memory_queries = tuple(_memory_queries(query, task_type))
    self_analysis = _self_analysis(task_type, complexity.tier, routing)
    return AIPlan(
        query=query,
        task_type=task_type,
        priority=score_task_priority(query, task_type),
        complexity={
            "score": complexity.score,
            "tier": complexity.tier,
            "suggested_max_tokens": complexity.suggested_max_tokens,
            "signals": complexity.signals,
        },
        routing=routing,
        steps=steps,
        tool_order=tool_order,
        memory_queries=memory_queries,
        self_analysis=self_analysis,
    )


def ai_diagnostics(
    *, engine: Any | None = None, model: str = "", query: str = ""
) -> dict[str, Any]:
    models: list[str] = []
    engine_id = ""
    health = None
    if engine is not None:
        engine_id = str(getattr(engine, "engine_id", type(engine).__name__))
        try:
            models = list(engine.list_models())
        except Exception:
            models = []
        try:
            health = bool(engine.health())
        except Exception:
            health = None
    plan = build_plan(
        query or "What can Grandpa do?",
        requested_model=model,
        available_models=models,
        cloud_allowed=False,
    )
    local_count = sum(
        1 for item in models if not any(h in item.lower() for h in _EMBEDDING_HINTS)
    )
    embedding_count = sum(
        1 for item in models if any(h in item.lower() for h in _EMBEDDING_HINTS)
    )
    return {
        "status": "ready" if models or engine is None else "limited",
        "timestamp": time.time(),
        "engine": {"id": engine_id, "healthy": health},
        "models": {
            "total": len(models),
            "local_chat": local_count,
            "cloud": 0,
            "embedding": embedding_count,
            "available": models[:30],
        },
        "planner": {
            "enabled": True,
            "last_plan": plan.to_dict(),
        },
        "orchestration": {
            "tool_routing": True,
            "workflow_decomposition": True,
            "semantic_memory": _semantic_status(),
            "fallback_model": plan.routing.selected_model,
        },
        "local_only": True,
    }


def _steps_for_task(query: str, task_type: str, tier: str) -> list[PlanStep]:
    if task_type == "pc_control":
        return [
            PlanStep(
                "Classify local action",
                "Check allowlist, risk, and approval policy.",
                "local_actions",
            ),
            PlanStep(
                "Execute or request approval",
                "Run safe actions directly and gate risky ones.",
                "pc_control",
                "MEDIUM",
            ),
            PlanStep(
                "Summarize outcome", "Return a concise truthful confirmation.", "chat"
            ),
        ]
    if task_type == "browser":
        return [
            PlanStep(
                "Read visible browser context",
                "Use localhost extension snapshot when available.",
                "browser_control",
            ),
            PlanStep(
                "Plan visible-page action",
                "Prefer read-only summary before interaction.",
                "browser_control",
            ),
            PlanStep(
                "Gate risky browser action",
                "Require approval for clicks, forms, downloads, and messages.",
                "approvals",
                "MEDIUM",
            ),
        ]
    if task_type == "screen":
        return [
            PlanStep(
                "Capture local screen context",
                "Use active-window, screenshot, and OCR backends.",
                "screen_awareness",
            ),
            PlanStep(
                "Classify visible UI",
                "Detect popups, errors, buttons, fields, and safe suggestions.",
                "screen_awareness",
            ),
            PlanStep(
                "Answer with uncertainty",
                "Avoid claiming exact UI positions without evidence.",
                "chat",
            ),
        ]
    if task_type == "memory":
        return [
            PlanStep(
                "Search personal memory",
                "Use semantic recall first, then keyword fallback.",
                "memory",
            ),
            PlanStep(
                "Score confidence", "Prefer recent and repeated memories.", "memory"
            ),
            PlanStep(
                "Answer or ask for clarification",
                "Do not invent missing memories.",
                "chat",
            ),
        ]
    if task_type == "files":
        return [
            PlanStep(
                "Resolve safe paths",
                "Stay inside allowed local folders unless approved.",
                "file_assistant",
            ),
            PlanStep(
                "Read metadata or content",
                "Summarize supported local documents.",
                "file_assistant",
            ),
            PlanStep(
                "Protect write/delete operations",
                "Require approval for risky filesystem changes.",
                "approvals",
                "MEDIUM",
            ),
        ]
    if task_type == "workflow":
        return [
            PlanStep(
                "Parse routine/reminder intent",
                "Find schedule, actions, and recurrence.",
                "scheduler",
            ),
            PlanStep(
                "Classify routine actions",
                "Block dangerous actions and gate risky ones.",
                "approvals",
                "MEDIUM",
            ),
            PlanStep(
                "Store or run routine",
                "Keep routine state local and auditable.",
                "scheduler",
            ),
        ]
    if task_type == "developer":
        return [
            PlanStep(
                "Inspect context",
                "Prefer repo-aware search and tests before edits.",
                "tools",
            ),
            PlanStep(
                "Plan safe changes", "Keep edits scoped and reversible.", "planner"
            ),
            PlanStep("Validate", "Run focused tests and builds.", "workflow"),
        ]
    steps = [
        PlanStep(
            "Understand request",
            "Classify goal, constraints, and available context.",
            "planner",
        ),
        PlanStep("Recall context", "Use semantic memory when relevant.", "memory"),
        PlanStep(
            "Answer", "Use the selected model with concise grounded output.", "chat"
        ),
    ]
    if tier in {"complex", "very_complex"}:
        steps.insert(
            2,
            PlanStep(
                "Decompose task",
                "Break the work into smaller verifiable steps.",
                "planner",
            ),
        )
    return steps


def _tool_order_for_task(task_type: str) -> list[str]:
    return {
        "pc_control": ["local_actions", "pc_control", "approvals", "memory"],
        "browser": ["browser_control", "approvals", "memory"],
        "screen": ["screen_awareness", "memory"],
        "memory": ["semantic_memory", "keyword_memory"],
        "files": ["file_assistant", "approvals", "memory"],
        "workflow": ["task_scheduler", "local_actions", "approvals", "memory"],
        "developer": ["repo_search", "tests", "planner"],
        "reasoning": ["semantic_memory", "planner", "chat"],
    }.get(task_type, ["semantic_memory", "chat"])


def _memory_queries(query: str, task_type: str) -> list[str]:
    base = [query.strip()] if query.strip() else []
    if task_type == "developer":
        base.append("preferred editor project coding workflow")
    elif task_type == "browser":
        base.append("preferred browser recent browsing task")
    elif task_type == "workflow":
        base.append("routines reminders common workflow")
    elif task_type == "memory":
        base.append("user preferences projects tools")
    return base[:3]


def _self_analysis(task_type: str, tier: str, routing: ModelRoutingDecision) -> str:
    bits = [f"Task type: {task_type}", f"complexity: {tier}"]
    if routing.fallback_used:
        bits.append(
            f"model fallback: {routing.requested_model} -> {routing.selected_model}"
        )
    else:
        bits.append(
            f"model: {routing.selected_model or routing.requested_model or 'not selected'}"
        )
    if routing.local_preferred:
        bits.append("local-first path preferred")
    return "; ".join(bits) + "."


def _best_match(models: list[str], priority: tuple[str, ...]) -> str:
    lowered = {model.lower(): model for model in models}
    for wanted in priority:
        wanted_lower = wanted.lower()
        if wanted_lower in lowered:
            return lowered[wanted_lower]
        for model in models:
            if model.lower().startswith(wanted_lower):
                return model
    return ""


def _engine_hint(model: str) -> str:
    if any(hint in model.lower() for hint in _EMBEDDING_HINTS):
        return "embedding"
    return "local"


def _semantic_status() -> dict[str, Any]:
    try:
        from grandpa.memory_context import MemoryStore

        return MemoryStore().semantic_status()
    except Exception:
        return {"enabled": False, "reason": "semantic memory status unavailable"}


__all__ = [
    "AIPlan",
    "ModelRoutingDecision",
    "PlanStep",
    "ai_diagnostics",
    "build_plan",
    "choose_model",
    "classify_task",
    "score_task_priority",
]
