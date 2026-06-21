"""Extended API routes for agents, workflows, memory, traces, etc."""

from __future__ import annotations

import base64
import inspect
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---- Request/Response models ----


class AgentCreateRequest(BaseModel):
    agent_type: str
    tools: Optional[List[str]] = None
    agent_id: Optional[str] = None


class AgentMessageRequest(BaseModel):
    message: str


class MultiAgentOrchestrateRequest(BaseModel):
    user_request: Optional[str] = None
    request: Optional[str] = None
    goal: Optional[str] = None


class KnowledgeImportRequest(BaseModel):
    source: str = "manual"
    title: Optional[str] = None
    content: Optional[str] = None
    path: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    import_project_docs: bool = False


class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5


class MemoryIndexRequest(BaseModel):
    path: str


class BudgetLimitsRequest(BaseModel):
    max_tokens_per_day: Optional[int] = None
    max_requests_per_hour: Optional[int] = None


class FeedbackScoreRequest(BaseModel):
    trace_id: str
    score: float
    source: str = "api"


class OptimizeRunRequest(BaseModel):
    benchmark: str
    max_trials: int = 20
    optimizer_model: str = "claude-sonnet-4-6"
    max_samples: int = 50


class VoiceSpeakRequest(BaseModel):
    text: str
    interrupt: bool = False
    dry_run: bool = False


class VoiceListenRequest(BaseModel):
    text: Optional[str] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = None


class VoiceCommandRequest(BaseModel):
    text: Optional[str] = None
    transcript: Optional[str] = None
    audio_base64: Optional[str] = None
    speak: bool = False
    speak_response: bool = False
    require_wake_word: bool = False
    confirmed: bool = False


class VoiceConfirmRequest(BaseModel):
    confirmation_token: str


class VoiceWakeWordTestRequest(BaseModel):
    text: str


class VoiceLoopTextRequest(BaseModel):
    text: Optional[str] = None
    transcript: Optional[str] = None


class DesktopOperatorPlanRequest(BaseModel):
    request: Optional[str] = None
    goal: Optional[str] = None
    persist: bool = True


class UserSkillCreateRequest(BaseModel):
    name: Optional[str] = None
    request: Optional[str] = None
    description: Optional[str] = None
    trigger_phrases: Optional[List[str]] = None
    workflow_steps: Optional[List[Dict[str, Any]]] = None
    approval_requirements: Optional[Dict[str, Any]] = None


class UserSkillRunRequest(BaseModel):
    params: Optional[Dict[str, Any]] = None
    dry_run: bool = False


# ---- Agent routes ----

agents_router = APIRouter(prefix="/v1/agents", tags=["agents"])


@agents_router.get("")
async def list_agents(request: Request):
    """List available agent types and running agents."""
    registered = []
    try:
        import grandpa.agents  # noqa: F401 — side-effect registration
        from grandpa.core.registry import AgentRegistry

        for key in sorted(AgentRegistry.keys()):
            cls = AgentRegistry.get(key)
            registered.append(
                {
                    "key": key,
                    "class": cls.__name__,
                    "accepts_tools": getattr(cls, "accepts_tools", False),
                }
            )
    except Exception as exc:
        logger.warning("Failed to list registered agents: %s", exc)

    running = []
    try:
        from grandpa.tools.agent_tools import _SPAWNED_AGENTS

        running = [{"id": k, **v} for k, v in _SPAWNED_AGENTS.items()]
    except ImportError:
        pass

    multi_agent = {}
    try:
        from grandpa.agents.registry import agent_registry_diagnostics

        multi_agent = agent_registry_diagnostics()
    except Exception as exc:
        logger.debug("Multi-agent registry diagnostics unavailable: %s", exc)

    return {"registered": registered, "running": running, "multi_agent": multi_agent}


@agents_router.post("")
async def create_agent(req: AgentCreateRequest, request: Request):
    """Spawn a new agent."""
    try:
        from grandpa.tools.agent_tools import AgentSpawnTool

        tool = AgentSpawnTool()
        params = {"agent_type": req.agent_type}
        if req.tools:
            params["tools"] = ",".join(req.tools)
        if req.agent_id:
            params["agent_id"] = req.agent_id
        result = tool.execute(**params)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.content)
        return {
            "status": "created",
            "content": result.content,
            "metadata": result.metadata,
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.get("/diagnostics")
async def multi_agent_diagnostics_route():
    """Return multi-agent registry and task-store diagnostics."""
    from grandpa.agents.orchestrator import multi_agent_diagnostics

    return multi_agent_diagnostics()


@agents_router.post("/orchestrate")
async def orchestrate_agents(req: MultiAgentOrchestrateRequest):
    """Run a deterministic multi-agent collaboration."""
    from grandpa.agents.orchestrator import orchestrate_goal

    user_request = (req.user_request or req.request or req.goal or "").strip()
    if not user_request:
        raise HTTPException(status_code=400, detail="user_request is required")
    return orchestrate_goal(user_request).to_dict()


@agents_router.get("/tasks")
async def list_multi_agent_tasks_route(limit: int = 50):
    """List persisted multi-agent collaboration tasks."""
    from grandpa.agents.orchestrator import list_multi_agent_tasks

    return {"tasks": list_multi_agent_tasks(limit=max(1, min(limit, 200)))}


@agents_router.get("/tasks/{task_id}")
async def get_multi_agent_task_route(task_id: str):
    """Return one persisted multi-agent task and its event timeline."""
    from grandpa.agents.orchestrator import get_multi_agent_task

    task = get_multi_agent_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Multi-agent task not found")
    return task


@agents_router.delete("/{agent_id}")
async def kill_agent(agent_id: str, request: Request):
    """Kill a running agent."""
    try:
        from grandpa.tools.agent_tools import AgentKillTool

        tool = AgentKillTool()
        result = tool.execute(agent_id=agent_id)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "stopped", "agent_id": agent_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.post("/{agent_id}/message")
async def message_agent(agent_id: str, req: AgentMessageRequest, request: Request):
    """Send a message to a running agent."""
    try:
        from grandpa.tools.agent_tools import AgentSendTool

        tool = AgentSendTool()
        result = tool.execute(agent_id=agent_id, message=req.message)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.content)
        return {"status": "sent", "content": result.content}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


# ---- Memory routes ----

memory_router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _get_memory_backend(request: Request):
    """Return the app-level memory backend, falling back to a fresh SQLiteMemory."""
    backend = getattr(request.app.state, "memory_backend", None)
    if backend is None:
        try:
            from grandpa.tools.storage.sqlite import SQLiteMemory

            backend = SQLiteMemory()
        except Exception:
            return None
    return backend


@memory_router.post("/store")
async def memory_store(req: MemoryStoreRequest, request: Request):
    """Store content in memory."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"status": "stored", "note": "no backend available"}
    try:
        backend.store(req.content, metadata=req.metadata or {})
        return {"status": "stored"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/search")
async def memory_search(req: MemorySearchRequest, request: Request):
    """Search memory for relevant content."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"results": []}
    try:
        results = backend.retrieve(req.query, top_k=req.top_k)
        items = [
            {
                "content": r.content,
                "score": getattr(r, "score", 0.0),
                "metadata": getattr(r, "metadata", {}),
            }
            for r in results
        ]
        return {"results": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/stats")
async def memory_stats(request: Request):
    """Get memory backend statistics."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"entries": 0, "backend": "none", "status": "not_configured"}
    try:
        return {
            "entries": backend.count(),
            "backend": getattr(backend, "backend_id", "unknown"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/config")
async def memory_config(request: Request):
    """Return current memory configuration."""
    try:
        config = getattr(request.app.state, "config", None)
        if config is None:
            from grandpa.core.config import load_config

            config = load_config()
        backend = getattr(request.app.state, "memory_backend", None)
        return {
            "backend_type": (
                backend.backend_id
                if backend is not None
                else config.memory.default_backend
            ),
            "context_top_k": config.memory.context_top_k,
            "context_min_score": config.memory.context_min_score,
            "context_max_tokens": config.memory.context_max_tokens,
            "context_from_memory": config.agent.context_from_memory,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/index")
async def memory_index(req: MemoryIndexRequest, request: Request):
    """Index files from a path into memory."""
    try:
        from pathlib import Path

        from grandpa.tools.storage.ingest import ingest_path

        target = Path(req.path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

        backend = _get_memory_backend(request)
        if backend is None:
            raise HTTPException(status_code=503, detail="No memory backend available")

        chunks = ingest_path(target)
        stored = 0
        for chunk in chunks:
            metadata = {"source": getattr(chunk, "source", str(target))}
            if hasattr(chunk, "metadata") and chunk.metadata:
                metadata.update(chunk.metadata)
            backend.store(chunk.content, metadata=metadata)
            stored += 1

        return {"status": "indexed", "chunks_indexed": stored}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Traces routes ----

traces_router = APIRouter(prefix="/v1/traces", tags=["traces"])


def _serialise_trace(trace) -> dict:
    """Convert a Trace dataclass to a frontend-friendly dict."""
    import datetime
    from dataclasses import asdict

    d = asdict(trace)
    d["id"] = d.pop("trace_id", "")
    started = d.pop("started_at", 0.0)
    d["created_at"] = (
        datetime.datetime.fromtimestamp(started, tz=datetime.timezone.utc).isoformat()
        if started
        else None
    )
    dur = d.pop("total_latency_seconds", 0.0)
    d["duration_ms"] = round(dur * 1000)
    for step in d.get("steps", []):
        st = step.get("step_type")
        if hasattr(st, "value"):
            step["step_type"] = st.value
    return d


@traces_router.get("")
async def list_traces(request: Request, limit: int = 20):
    """List recent traces."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            return {"traces": []}
        traces = store.list_traces(limit=limit)
        items = [_serialise_trace(t) for t in traces]
        return {"traces": items}
    except Exception as exc:
        return {"traces": [], "error": str(exc)}


@traces_router.get("/{trace_id}")
async def get_trace(trace_id: str, request: Request):
    """Get a specific trace by ID."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        trace = store.get(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return _serialise_trace(trace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Telemetry routes ----

telemetry_router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@telemetry_router.get("/stats")
async def telemetry_stats(request: Request):
    """Get aggregated telemetry statistics."""
    try:
        from dataclasses import asdict

        from grandpa.core.config import DEFAULT_CONFIG_DIR
        from grandpa.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {"total_requests": 0, "total_tokens": 0}

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            d = asdict(stats)
            d.pop("per_model", None)
            d.pop("per_engine", None)
            d["total_requests"] = d.pop("total_calls", 0)
            return d
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


@telemetry_router.get("/energy")
async def telemetry_energy(request: Request):
    """Get energy monitoring data."""
    try:
        from grandpa.core.config import DEFAULT_CONFIG_DIR
        from grandpa.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            return {
                "total_energy_j": 0,
                "energy_per_token_j": 0,
                "avg_power_w": 0,
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            total_energy = stats.total_energy_joules
            total_tokens = stats.total_tokens
            total_latency = stats.total_latency
            return {
                "total_energy_j": total_energy,
                "energy_per_token_j": (
                    total_energy / total_tokens if total_tokens > 0 else 0
                ),
                "avg_power_w": (
                    total_energy / total_latency if total_latency > 0 else 0
                ),
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


# ---- Skills routes ----

skills_router = APIRouter(prefix="/v1/skills", tags=["skills"])
user_skills_router = APIRouter(prefix="/v1/user-skills", tags=["user-skills"])
plugins_router = APIRouter(prefix="/v1/plugins", tags=["plugins"])
release_gate_router = APIRouter(prefix="/v1/release-gate", tags=["release-gate"])
burnin_router = APIRouter(prefix="/v1/burnin", tags=["burnin"])
audit_router = APIRouter(prefix="/v1/audit", tags=["audit"])
services_router = APIRouter(prefix="/v1/services", tags=["services"])
actions_router = APIRouter(prefix="/v1/actions", tags=["actions"])
desktop_operator_router = APIRouter(prefix="/v1/desktop/operator", tags=["desktop-operator"])
planner_router = APIRouter(prefix="/v1/planner", tags=["planner"])
agent_runtime_router = APIRouter(prefix="/v1/agent", tags=["agent-runtime"])
mcp_router = APIRouter(prefix="/v1/mcp", tags=["mcp"])
intent_router = APIRouter(prefix="/v1/router", tags=["intent-router"])
knowledge_router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])
coding_router = APIRouter(prefix="/v1/coding", tags=["coding"])


@skills_router.get("")
async def list_skills(request: Request):
    """List installed skills and runtime skill wrappers."""
    try:
        from grandpa.services import skill_service

        return skill_service.list_skills()
    except Exception as exc:
        logger.warning("Failed to list skills: %s", exc)
        return {"skills": [], "runtime": {"status": "unavailable", "error": exc.__class__.__name__}}


@skills_router.get("/categories")
async def skill_categories():
    """List runtime skill categories."""
    from grandpa.services import skill_service

    return skill_service.categories()


@skills_router.get("/{skill_name}")
async def get_runtime_skill(skill_name: str):
    """Return one runtime skill by name or alias."""
    from grandpa.services import skill_service

    try:
        return skill_service.get_skill(skill_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc


@skills_router.post("/execute")
async def execute_runtime_skill(request: Request):
    """Execute a runtime skill through the central registry."""
    from grandpa.services import skill_service

    body = await request.json()
    try:
        return skill_service.execute_skill_from_body(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="'name' field is required")
    except TypeError:
        raise HTTPException(status_code=400, detail="'params' must be an object")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc


@skills_router.post("")
async def install_skill(request: Request):
    """Install a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Use TOML files in ~/.grandpa/skills/",
    }


@skills_router.delete("/{skill_name}")
async def remove_skill(skill_name: str, request: Request):
    """Remove a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Skill removal not yet supported via API",
    }


@user_skills_router.get("/diagnostics")
async def user_skill_diagnostics():
    from grandpa.skill_builder import diagnostics

    return diagnostics()


@user_skills_router.get("")
async def list_user_skills(limit: int = 100, query: str = ""):
    from grandpa.skill_builder import list_user_skills, search_user_skills

    if query:
        return search_user_skills(query, limit=limit)
    return list_user_skills(limit=limit)


@user_skills_router.get("/{skill_id}")
async def get_user_skill(skill_id: str):
    from grandpa.skill_builder import get_user_skill

    try:
        return get_user_skill(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User skill not found") from exc


@user_skills_router.post("/create")
async def create_user_skill_route(payload: UserSkillCreateRequest):
    from grandpa.skill_builder import create_user_skill
    from grandpa.skill_builder.validator import SkillValidationError

    try:
        return create_user_skill(payload.model_dump(exclude_none=True))
    except SkillValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@user_skills_router.post("/{skill_id}/run")
async def run_user_skill_route(skill_id: str, payload: UserSkillRunRequest):
    from grandpa.skill_builder import run_user_skill

    try:
        params = dict(payload.params or {})
        params["dry_run"] = payload.dry_run
        return run_user_skill(skill_id, params=params, source="api")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User skill not found") from exc


@user_skills_router.post("/{skill_id}/delete")
async def delete_user_skill_route(skill_id: str):
    from grandpa.skill_builder import delete_user_skill

    try:
        return delete_user_skill(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User skill not found") from exc


# ---- Coding agent routes ----


@coding_router.get("/projects")
async def coding_projects():
    from grandpa.coding.project_scanner import scan_projects

    return scan_projects()


@coding_router.get("/project-summary")
async def coding_project_summary():
    from grandpa.coding.code_summary import summarize_project

    return summarize_project()


@coding_router.get("/architecture")
async def coding_architecture():
    from grandpa.coding.architecture_analysis import analyze_architecture

    return analyze_architecture()


@coding_router.get("/dependencies")
async def coding_dependencies():
    from grandpa.coding.dependency_analysis import analyze_dependencies

    return analyze_dependencies()


@coding_router.get("/diagnostics")
async def coding_diagnostics_route():
    from grandpa.coding.diagnostics import coding_diagnostics

    return coding_diagnostics()


# ---- Knowledge routes ----


@knowledge_router.post("/import")
async def import_knowledge(req: KnowledgeImportRequest):
    """Import local text, markdown, JSON, notes, or project documentation into the knowledge engine."""
    from grandpa.knowledge.engine import KnowledgeEngine

    engine = KnowledgeEngine()
    try:
        if req.import_project_docs:
            return engine.import_project_docs(req.path or "docs")
        if req.path:
            return engine.import_file(req.path, tags=req.tags)
        if not req.content:
            raise HTTPException(status_code=400, detail="content, path, or import_project_docs is required")
        return engine.import_document(
            source=req.source,
            content=req.content,
            title=req.title,
            tags=req.tags,
            metadata=req.metadata,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@knowledge_router.get("/search")
async def search_knowledge_route(
    q: str = "",
    tag: str = "",
    title: str = "",
    project_only: bool = False,
    limit: int = 20,
):
    """Search local knowledge by keyword, title, tag, recency, or project marker."""
    from grandpa.knowledge.engine import KnowledgeEngine

    return KnowledgeEngine().search(
        q,
        tag=tag,
        title=title,
        project_only=project_only,
        limit=max(1, min(limit, 100)),
    )


@knowledge_router.get("/semantic-search")
async def semantic_search_knowledge_route(q: str, tag: str = "", project_only: bool = False, limit: int = 10):
    """Search local knowledge using stored chunk embeddings when available."""
    from grandpa.knowledge.engine import KnowledgeEngine

    return KnowledgeEngine().semantic_search(q, tag=tag, project_only=project_only, limit=max(1, min(limit, 50)))


@knowledge_router.get("/context")
async def knowledge_context_route(q: str, project_only: bool = False, limit: int = 5):
    """Build a compact local knowledge context packet for planners and agents."""
    from grandpa.knowledge.engine import KnowledgeEngine

    return KnowledgeEngine().context(q, project_only=project_only, limit=max(1, min(limit, 20)))


@knowledge_router.get("/related")
async def related_knowledge_route(document_id: str, limit: int = 8):
    """Return documents related to a local knowledge document."""
    from grandpa.knowledge.engine import KnowledgeEngine

    try:
        return KnowledgeEngine().related(document_id, limit=max(1, min(limit, 50)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge document not found") from exc


@knowledge_router.get("/embedding-status")
async def knowledge_embedding_status_route():
    """Return embedding backend and chunk-vector coverage."""
    from grandpa.knowledge.engine import knowledge_embedding_status

    return knowledge_embedding_status()


@knowledge_router.get("/documents")
async def list_knowledge_documents_route(limit: int = 100):
    """List local indexed knowledge documents."""
    from grandpa.knowledge.engine import list_knowledge_documents

    return list_knowledge_documents(limit=max(1, min(limit, 500)))


@knowledge_router.get("/document/{document_id}")
async def get_knowledge_document_route(document_id: str):
    """Return one local knowledge document."""
    from grandpa.knowledge.engine import KnowledgeEngine

    document = KnowledgeEngine().get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return document


@knowledge_router.get("/summary")
async def knowledge_summary_route(document_id: str = "", topic: str = "", project: bool = False):
    """Generate deterministic local knowledge summaries."""
    from grandpa.knowledge.engine import KnowledgeEngine

    try:
        return KnowledgeEngine().summary(document_id=document_id, topic=topic, project=project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge document not found") from exc


@knowledge_router.get("/diagnostics")
async def knowledge_diagnostics_route():
    """Return knowledge engine readiness and retrieval capabilities."""
    from grandpa.knowledge.engine import knowledge_diagnostics

    return knowledge_diagnostics()


# ---- Plugin runtime routes ----


@plugins_router.get("")
async def list_plugins_route():
    """List local manifest-driven plugins."""
    from grandpa.services import plugin_service

    return plugin_service.diagnostics()


@plugins_router.get("/{plugin_name}")
async def get_plugin_route(plugin_name: str):
    """Return one plugin manifest and status."""
    from grandpa.services import plugin_service

    plugin = plugin_service.get(plugin_name)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@plugins_router.post("/reload")
async def reload_plugins_route():
    """Reload enabled plugin manifests and re-register plugin skills."""
    from grandpa.services import plugin_service

    return plugin_service.reload()


@plugins_router.post("/{plugin_name}/enable")
async def enable_plugin_route(plugin_name: str):
    """Enable a plugin and reload plugin-provided skills."""
    from grandpa.services import plugin_service

    try:
        return plugin_service.enable(plugin_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc


@plugins_router.post("/{plugin_name}/disable")
async def disable_plugin_route(plugin_name: str):
    """Disable a plugin and unregister its provided skills."""
    from grandpa.services import plugin_service

    try:
        return plugin_service.disable(plugin_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc


# ---- Final release gate routes ----


@services_router.get("")
async def services_diagnostics_route():
    """Return registered API service facade diagnostics."""
    from grandpa.services import service_diagnostics

    return service_diagnostics()


@actions_router.get("/diagnostics")
async def actions_diagnostics_route():
    """Return local action decomposition and legacy fallback diagnostics."""
    from grandpa.actions import action_diagnostics

    return action_diagnostics()


@desktop_operator_router.get("/diagnostics")
async def desktop_operator_diagnostics_route():
    """Return Desktop Operator v2 readiness and safety diagnostics."""
    from grandpa.desktop.operator import operator_diagnostics

    return operator_diagnostics()


@desktop_operator_router.post("/plan")
async def desktop_operator_plan_route(req: DesktopOperatorPlanRequest):
    """Build a safe UI navigation plan for a desktop task."""
    from grandpa.desktop.operator import build_ui_navigation_plan

    text = (req.request or req.goal or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="request or goal is required")
    return build_ui_navigation_plan(text, persist=req.persist)


@desktop_operator_router.get("/tasks")
async def desktop_operator_tasks_route(limit: int = 50):
    """List recent persisted Desktop Operator tasks."""
    from grandpa.desktop.operator import list_operator_tasks

    return list_operator_tasks(limit=max(1, min(limit, 200)))


@desktop_operator_router.get("/profiles")
async def desktop_operator_profiles_route():
    """List deterministic app profiles used by Desktop Operator v2."""
    from grandpa.desktop.operator import list_app_profiles

    return list_app_profiles()


@release_gate_router.get("/latest")
async def release_gate_latest():
    """Return the latest full final release gate report."""
    from grandpa.services import release_service

    return release_service.latest()


@release_gate_router.get("/status")
async def release_gate_status_route():
    """Return compact final release gate status."""
    from grandpa.services import release_service

    return release_service.status()


@burnin_router.get("/latest")
async def burnin_latest():
    """Return the latest daily-use burn-in report."""
    from grandpa.services import burnin_service

    return burnin_service.latest()


@burnin_router.get("/status")
async def burnin_status_route():
    """Return compact daily-use burn-in status."""
    from grandpa.services import burnin_service

    return burnin_service.status()


@audit_router.get("/latest")
async def production_audit_latest():
    """Return the latest real-device production audit report."""
    from grandpa.production_audit import latest_report

    return latest_report()


@audit_router.get("/status")
async def production_audit_status_route():
    """Return compact real-device production audit status."""
    from grandpa.production_audit import status as audit_status

    return audit_status()


# ---- Planner / Agent Runtime / Local MCP bridge ----


@planner_router.get("/diagnostics")
async def planner_runtime_diagnostics():
    """Return planner, skill runtime, workflow handoff, and MCP bridge readiness."""
    from grandpa.services import planner_service

    return planner_service.diagnostics()


@planner_router.post("/analyze")
async def planner_analyze(request: Request):
    """Analyze a user request without executing tools."""
    from grandpa.services import planner_service

    body = await request.json()
    text = str(body.get("request") or body.get("query") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="'request' field is required")
    return planner_service.analyze_request(text)


@agent_runtime_router.post("/run")
async def agent_runtime_run(request: Request):
    """Create a native agent task from a planner goal."""
    from grandpa.services import planner_service

    body = await request.json()
    try:
        return planner_service.run_agent_goal_from_body(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="'request' field is required")


@agent_runtime_router.get("/tasks")
async def agent_runtime_tasks(limit: int = 50):
    """List recent native planner-agent tasks."""
    from grandpa.services import planner_service

    return planner_service.list_agent_tasks(limit=limit)


@agent_runtime_router.post("/goals")
async def create_autonomous_agent_goal(request: Request):
    """Create and optionally run a persistent autonomous goal."""
    from grandpa.agents.goal_mode import create_goal

    body = await request.json()
    user_request = str(body.get("user_request") or body.get("request") or "").strip()
    if not user_request:
        raise HTTPException(status_code=400, detail="'user_request' field is required")
    priority = str(body.get("priority") or "normal")
    execute = bool(body.get("execute", True))
    return create_goal(user_request, priority=priority, execute=execute).to_dict()


@agent_runtime_router.get("/goals")
async def list_autonomous_agent_goals(limit: int = 50):
    """List persistent autonomous goals."""
    from grandpa.agents.goal_mode import list_goals

    return {"goals": list_goals(limit=limit)}


@agent_runtime_router.get("/goals/{goal_id}")
async def get_autonomous_agent_goal(goal_id: str):
    """Return one persistent autonomous goal."""
    from grandpa.agents.goal_mode import get_goal

    goal = get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@agent_runtime_router.post("/goals/{goal_id}/continue")
async def continue_autonomous_agent_goal(goal_id: str):
    """Continue a queued or paused autonomous goal."""
    from grandpa.agents.goal_mode import continue_goal

    goal = continue_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal.to_dict()


@agent_runtime_router.post("/goals/{goal_id}/cancel")
async def cancel_autonomous_agent_goal(goal_id: str):
    """Cancel an autonomous goal."""
    from grandpa.agents.goal_mode import cancel_goal

    goal = cancel_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal.to_dict()


@agent_runtime_router.get("/goals/{goal_id}/events")
async def autonomous_agent_goal_events(goal_id: str):
    """Return persistent lifecycle events for one autonomous goal."""
    from grandpa.agents.goal_mode import get_goal, goal_events

    if get_goal(goal_id) is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"events": goal_events(goal_id)}


@agent_runtime_router.get("/diagnostics")
async def autonomous_agent_diagnostics():
    """Return autonomous goal-mode diagnostics."""
    from grandpa.agents.goal_mode import agent_goal_diagnostics

    return agent_goal_diagnostics()


@mcp_router.get("/tools")
async def mcp_tools():
    """Return local MCP-style tool schemas backed by runtime skills."""
    from grandpa.services import planner_service

    return planner_service.mcp_tools()


@intent_router.get("/diagnostics")
async def intent_router_diagnostics():
    """Return intent-router route counts and recent decisions."""
    from grandpa.services import planner_service

    return planner_service.router_diagnostics()


@intent_router.post("/analyze")
async def intent_router_analyze(request: Request):
    """Analyze a local-action request without executing it."""
    from grandpa.services import planner_service

    body = await request.json()
    text = str(body.get("request") or body.get("query") or body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="'request' field is required")
    return planner_service.analyze_intent(text)


# ---- Sessions routes ----

sessions_router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@sessions_router.get("")
async def list_sessions(request: Request, limit: int = 20):
    """List active sessions."""
    try:
        from grandpa.sessions.store import SessionStore

        store = SessionStore()
        sessions = store.recent(limit=limit)
        items = [s.to_dict() if hasattr(s, "to_dict") else str(s) for s in sessions]
        return {"sessions": items}
    except Exception as exc:
        return {"sessions": [], "error": str(exc)}


@sessions_router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get a specific session."""
    try:
        from grandpa.sessions.store import SessionStore

        store = SessionStore()
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict() if hasattr(session, "to_dict") else {"id": session_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Budget routes ----

budget_router = APIRouter(prefix="/v1/budget", tags=["budget"])

_budget_limits: Dict[str, Any] = {
    "max_tokens_per_day": None,
    "max_requests_per_hour": None,
}
_budget_usage: Dict[str, int] = {
    "tokens_today": 0,
    "requests_this_hour": 0,
}


@budget_router.get("")
async def get_budget(request: Request):
    """Get current budget usage and limits."""
    return {"limits": _budget_limits, "usage": _budget_usage}


@budget_router.put("/limits")
async def set_budget_limits(req: BudgetLimitsRequest, request: Request):
    """Update budget limits."""
    if req.max_tokens_per_day is not None:
        _budget_limits["max_tokens_per_day"] = req.max_tokens_per_day
    if req.max_requests_per_hour is not None:
        _budget_limits["max_requests_per_hour"] = req.max_requests_per_hour
    return {"status": "updated", "limits": _budget_limits}


# ---- Prometheus metrics ----

metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus-compatible metrics endpoint."""
    try:
        from grandpa.core.config import DEFAULT_CONFIG_DIR
        from grandpa.telemetry.aggregator import TelemetryAggregator

        db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
        if not db_path.exists():
            from starlette.responses import PlainTextResponse

            return PlainTextResponse(
                "# grandpa: no telemetry data\n",
                media_type="text/plain",
            )

        agg = TelemetryAggregator(db_path)
        stats = agg.summary()

        lines = [
            "# HELP Grandpa_requests_total Total requests processed",
            "# TYPE Grandpa_requests_total counter",
            f"Grandpa_requests_total {stats.get('total_requests', 0)}",
            "# HELP Grandpa_tokens_total Total tokens generated",
            "# TYPE Grandpa_tokens_total counter",
            f"Grandpa_tokens_total {stats.get('total_tokens', 0)}",
            "# HELP Grandpa_latency_avg_ms Average latency in milliseconds",
            "# TYPE Grandpa_latency_avg_ms gauge",
            f"Grandpa_latency_avg_ms {stats.get('avg_latency_ms', 0)}",
        ]
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
    except Exception as exc:
        logger.warning("Failed to collect Prometheus metrics: %s", exc)
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("# No metrics available\n", media_type="text/plain")


# ---- WebSocket streaming routes ----

websocket_router = APIRouter(tags=["websocket"])


@websocket_router.websocket("/v1/chat/stream")
async def websocket_chat_stream(websocket: WebSocket):
    """Stream chat responses over a WebSocket connection.

    Accepts JSON messages of the form::

        {"message": "...", "model": "...", "agent": "..."}

    Sends back JSON chunks::

        {"type": "chunk", "content": "..."}   -- per-token streaming
        {"type": "done",  "content": "..."}   -- final assembled response
        {"type": "error", "detail": "..."}    -- on failure
    """
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON"},
                )
                continue

            message = data.get("message")
            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Missing 'message' field"},
                )
                continue

            model = data.get("model") or getattr(
                websocket.app.state,
                "model",
                "default",
            )
            engine = getattr(websocket.app.state, "engine", None)
            if engine is None:
                await websocket.send_json(
                    {"type": "error", "detail": "No engine configured"},
                )
                continue

            messages = [{"role": "user", "content": message}]

            try:
                # Prefer streaming if the engine supports it
                stream_fn = getattr(engine, "stream", None)
                if stream_fn is not None and (
                    inspect.isasyncgenfunction(stream_fn) or callable(stream_fn)
                ):
                    full_content = ""
                    try:
                        gen = stream_fn(messages, model=model)
                        # Handle both async and sync generators
                        if inspect.isasyncgen(gen):
                            async for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                        else:
                            # Sync generator — iterate in a thread to avoid
                            # blocking the event loop
                            for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                    except TypeError:
                        # stream() didn't return an iterable; fall back to
                        # generate()
                        result = engine.generate(messages, model=model)
                        content = (
                            result.get("content", "")
                            if isinstance(
                                result,
                                dict,
                            )
                            else str(result)
                        )
                        full_content = content
                        await websocket.send_json(
                            {"type": "chunk", "content": content},
                        )
                    await websocket.send_json(
                        {"type": "done", "content": full_content},
                    )
                else:
                    # No stream method — single-shot generate
                    result = engine.generate(messages, model=model)
                    content = (
                        result.get("content", "")
                        if isinstance(
                            result,
                            dict,
                        )
                        else str(result)
                    )
                    await websocket.send_json(
                        {"type": "chunk", "content": content},
                    )
                    await websocket.send_json(
                        {"type": "done", "content": content},
                    )
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                await websocket.send_json(
                    {"type": "error", "detail": str(exc)},
                )
    except WebSocketDisconnect:
        pass  # Client disconnected — nothing to clean up


# ---- Learning routes ----

learning_router = APIRouter(prefix="/v1/learning", tags=["learning"])


@learning_router.get("/stats")
async def learning_stats(request: Request):
    """Return learning system statistics across all sub-policies."""
    result: Dict[str, Any] = {}

    # Skill discovery
    try:
        from grandpa.learning.agents.skill_discovery import SkillDiscovery

        discovery = SkillDiscovery()
        result["skill_discovery"] = {
            "available": True,
            "discovered_count": len(discovery.discovered_skills),
        }
    except Exception as exc:
        logger.warning("Failed to load skill discovery stats: %s", exc)
        result["skill_discovery"] = {"available": False}

    return result


@learning_router.get("/policy")
async def learning_policy(request: Request):
    """Return current routing policy configuration."""
    result: Dict[str, Any] = {}

    # Load config and extract learning section
    try:
        from grandpa.core.config import load_config

        config = load_config()
        lc = config.learning
        result["enabled"] = lc.enabled
        result["update_interval"] = lc.update_interval
        result["auto_update"] = lc.auto_update
        result["routing"] = {
            "policy": lc.routing.policy,
            "min_samples": lc.routing.min_samples,
        }
        result["intelligence"] = {
            "policy": lc.intelligence.policy,
        }
        result["agent"] = {
            "policy": lc.agent.policy,
        }
        result["metrics"] = {
            "accuracy_weight": lc.metrics.accuracy_weight,
            "latency_weight": lc.metrics.latency_weight,
            "cost_weight": lc.metrics.cost_weight,
            "efficiency_weight": lc.metrics.efficiency_weight,
        }
    except Exception as exc:
        logger.warning("Failed to load learning config: %s", exc)
        result["enabled"] = False
        result["routing"] = {"policy": "heuristic", "min_samples": 5}
        result["intelligence"] = {"policy": "none"}
        result["agent"] = {"policy": "none"}
        result["metrics"] = {}

    return result


# ---- Speech routes ----

speech_router = APIRouter(prefix="/v1/speech", tags=["speech"])


@speech_router.post("/transcribe")
async def transcribe_speech(request: Request):
    """Transcribe uploaded audio to text."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")

    form = await request.form()
    audio_file = form.get("file")
    if audio_file is None:
        raise HTTPException(status_code=400, detail="Missing 'file' field")

    audio_bytes = await audio_file.read()
    language = form.get("language")

    # Detect format from filename
    filename = getattr(audio_file, "filename", "audio.wav")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "wav"

    result = backend.transcribe(audio_bytes, format=ext, language=language or None)
    return {
        "text": result.text,
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
    }


@speech_router.get("/health")
async def speech_health(request: Request):
    """Check if a speech backend is available."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        return {"available": False, "reason": "No speech backend configured"}
    return {
        "available": backend.health(),
        "backend": backend.backend_id,
    }


# ---- Voice runtime routes ----

voice_router = APIRouter(prefix="/v1/voice", tags=["voice"])
conversation_router = APIRouter(prefix="/v1/conversation", tags=["conversation"])


@conversation_router.get("/status")
async def conversation_status(request: Request):
    """Return short-term conversation session status."""
    return _get_conversation_session(request).status()


@conversation_router.get("/history")
async def conversation_history(request: Request):
    """Return recent short-term conversation messages."""
    return _get_conversation_session(request).history()


@conversation_router.post("/clear")
async def conversation_clear(request: Request):
    """Clear short-term conversation session messages."""
    return _get_conversation_session(request).clear()


@conversation_router.post("/summary")
async def conversation_summary(request: Request):
    """Summarize recent short-term conversation context without an LLM."""
    return _get_conversation_session(request).summary()


@voice_router.get("/status")
async def voice_status():
    """Return Grandpa voice runtime status and local engine readiness."""
    from grandpa.voice import get_voice_runtime

    return get_voice_runtime().status()


@voice_router.post("/start")
async def voice_start():
    """Start the local voice conversation session."""
    from grandpa.voice import get_voice_runtime

    return get_voice_runtime().start()


@voice_router.post("/stop")
async def voice_stop():
    """Stop listening/speaking state for the local voice session."""
    from grandpa.voice import get_voice_runtime

    return get_voice_runtime().stop()


@voice_router.post("/speak")
async def voice_speak(req: VoiceSpeakRequest):
    """Speak text through the local TTS adapter when available."""
    from grandpa.voice import get_voice_runtime

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    result = get_voice_runtime().speak(req.text, interrupt=req.interrupt, dry_run=req.dry_run)
    _raise_for_expected_voice_error(result)
    return result


@voice_router.post("/listen")
async def voice_listen(request: Request):
    """Capture a voice transcript/audio payload without running an action."""
    from grandpa.voice import get_voice_runtime
    from grandpa.voice.errors import MICROPHONE_UNAVAILABLE_MESSAGE

    payload = await _read_voice_listen_payload(request)
    text = payload.get("text")
    audio_base64 = payload.get("audio_base64")
    audio_format = payload.get("audio_format") or "wav"
    if not (text and text.strip()) and not audio_base64:
        raise HTTPException(status_code=400, detail=MICROPHONE_UNAVAILABLE_MESSAGE)
    result = get_voice_runtime().capture(
        text=text,
        audio_base64=audio_base64,
        audio_format=audio_format,
    )
    _raise_for_expected_voice_error(result)
    return result


@voice_router.get("/stt/status")
async def voice_stt_status():
    """Return local speech-to-text engine/model readiness."""
    from grandpa.voice import get_voice_runtime

    return get_voice_runtime().speech_input.stt_status()


@voice_router.get("/history")
async def voice_history(request: Request):
    """Return recent voice command history."""
    store = _get_voice_history_store(request)
    return {"history": store.list()}


@voice_router.post("/history/clear")
async def voice_history_clear(request: Request):
    """Clear persisted voice command history."""
    store = _get_voice_history_store(request)
    cleared = store.clear()
    return {"status": "cleared", "cleared": cleared}


@voice_router.get("/wake-word/status")
async def voice_wake_word_status(request: Request):
    """Return wake-word foundation status without starting listeners."""
    return _get_wake_word_session(request).status()


@voice_router.post("/wake-word/enable")
async def voice_wake_word_enable(request: Request):
    """Enable mock transcript wake-word detection."""
    return _get_wake_word_session(request).enable()


@voice_router.post("/wake-word/disable")
async def voice_wake_word_disable(request: Request):
    """Disable mock transcript wake-word detection."""
    return _get_wake_word_session(request).disable()


@voice_router.post("/wake-word/test")
async def voice_wake_word_test(req: VoiceWakeWordTestRequest, request: Request):
    """Test wake-word matching against provided text only."""
    return _get_wake_word_session(request).detect_mock(req.text)


@voice_router.get("/loop/status")
async def voice_loop_status(request: Request):
    """Return safe continuous voice loop foundation status."""
    return _get_voice_loop_session(request).status()


@voice_router.post("/loop/enable")
async def voice_loop_enable(request: Request):
    """Enable the text-simulated voice loop foundation."""
    return _get_voice_loop_session(request).enable()


@voice_router.post("/loop/disable")
async def voice_loop_disable(request: Request):
    """Disable and stop the text-simulated voice loop foundation."""
    return _get_voice_loop_session(request).disable()


@voice_router.post("/loop/start")
async def voice_loop_start(request: Request):
    """Start the voice loop only if wake word state is enabled."""
    return _get_voice_loop_session(request).start()


@voice_router.post("/loop/stop")
async def voice_loop_stop(request: Request):
    """Stop the text-simulated voice loop foundation."""
    return _get_voice_loop_session(request).stop()


@voice_router.post("/loop/simulate-wake")
async def voice_loop_simulate_wake(req: VoiceLoopTextRequest, request: Request):
    """Simulate wake-word input without microphone access."""
    text = (req.text or req.transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    return _get_voice_loop_session(request).simulate_wake(text)


@voice_router.post("/loop/simulate-command")
async def voice_loop_simulate_command(req: VoiceLoopTextRequest, request: Request):
    """Simulate a command transcript through the existing safe voice router."""
    transcript = (req.transcript or req.text or "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="I didn't hear anything.")

    loop = _get_voice_loop_session(request)

    def route_command(command_text: str) -> dict[str, Any]:
        result = _route_voice_command_text(command_text, request, confirmed=False)
        result["spoken"] = False
        result["transcript"] = command_text
        result["command_text"] = command_text
        _record_voice_history(request, result)
        if result.get("ok", True):
            _record_conversation_exchange(request, command_text, result.get("assistant_text", ""))
        return result

    return loop.simulate_command(transcript, command_router=route_command)


@voice_router.post("/command")
async def voice_command(req: VoiceCommandRequest, request: Request):
    """Route a transcript through reminders and safe local action permissions."""
    from grandpa.voice import get_voice_runtime

    text = req.transcript if req.transcript is not None else req.text
    if not (text and text.strip()):
        raise HTTPException(status_code=400, detail="I didn't hear anything.")

    runtime = get_voice_runtime()
    transcript = text.strip()
    wake_match = runtime.wake_detector.detect(transcript)
    if req.require_wake_word and runtime.wake_detector.config.enabled and not wake_match.matched:
        assistant_text = "Wake word was not detected. Use push-to-talk or say Hey Grandpa."
        return _voice_command_response(
            transcript=transcript,
            command_text=transcript,
            assistant_text=assistant_text,
            action_type="none",
            action_status="unsupported",
            detail=assistant_text,
            spoken=False,
        )

    command_text = (wake_match.command_text if wake_match.matched else transcript).strip()
    if not command_text:
        raise HTTPException(status_code=400, detail="I didn't hear anything.")

    result = _route_voice_command_text(command_text, request, confirmed=req.confirmed)
    spoken = False
    if req.speak or req.speak_response:
        try:
            speech = runtime.speak(result["assistant_text"], interrupt=True, dry_run=False)
            spoken = speech.get("status") in {"completed", "dry_run"}
        except Exception:
            logger.debug("Voice command speech output failed", exc_info=True)
    result["spoken"] = spoken
    result["transcript"] = transcript
    result["command_text"] = command_text
    _record_voice_history(request, result)
    if result.get("ok", True):
        _record_conversation_exchange(request, command_text, result.get("assistant_text", ""))
    return result


@voice_router.post("/confirm")
async def voice_confirm(req: VoiceConfirmRequest, request: Request):
    """Confirm a previously returned voice command confirmation token."""
    from grandpa.local_actions import approve_pending_action

    token = req.confirmation_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="confirmation_token is required")

    result = approve_pending_action(token)
    action_status = _voice_action_status(result.status)
    if action_status == "unsupported":
        action_status = "blocked"
    assistant_text = _friendly_voice_message(action_status, result.message)
    payload = _voice_command_response(
        transcript=result.pending_action.get("source_text", "") if result.pending_action else "",
        command_text=result.pending_action.get("source_text", "") if result.pending_action else "",
        assistant_text=assistant_text,
        action_type="desktop",
        action_status=action_status,
        detail=result.message or assistant_text,
        spoken=False,
        extra={
            "local_action": {
                "status": result.status,
                "kind": result.kind,
                "target": result.target,
                "permission": result.permission,
                "pending_action": result.pending_action,
            }
        },
    )
    _record_voice_history(request, payload)
    return payload


def _route_voice_command_text(
    command_text: str,
    request: Request,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    lowered = command_text.strip().lower()
    if lowered in {"what is my voice status", "voice status", "what's my voice status"}:
        from grandpa.voice import get_voice_runtime

        status = get_voice_runtime().status()
        assistant_text = status.get("message") or "Voice status is available."
        return _voice_command_response(
            transcript=command_text,
            command_text=command_text,
            assistant_text=assistant_text,
            action_type="none",
            action_status="handled",
            detail=assistant_text,
            spoken=False,
            extra={"voice": status},
        )

    if _looks_like_reminder_command(command_text):
        reminder = _handle_voice_reminder(command_text, request)
        return reminder

    return _handle_voice_local_action(command_text, confirmed=confirmed)


def _looks_like_reminder_command(command_text: str) -> bool:
    return command_text.strip().lower().startswith(("remind me ", "please remind me "))


def _handle_voice_reminder(command_text: str, request: Request) -> dict[str, Any]:
    from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase
    from grandpa.reminders import ReminderStore

    try:
        parsed = parse_reminder_phrase(command_text)
        store = getattr(request.app.state, "reminder_store", None) or ReminderStore()
        reminder = store.create(
            parsed.message,
            parsed.due_at,
            source={"voice_command": True, "transcript": command_text},
        )
    except ReminderParseError as exc:
        assistant_text = str(exc)
        return _voice_command_response(
            transcript=command_text,
            command_text=command_text,
            assistant_text=assistant_text,
            action_type="reminder",
            action_status="unsupported",
            detail=assistant_text,
            spoken=False,
        )
    except Exception as exc:
        assistant_text = "I couldn't create that reminder."
        return _voice_command_response(
            transcript=command_text,
            command_text=command_text,
            assistant_text=assistant_text,
            action_type="reminder",
            action_status="error",
            detail=str(exc),
            spoken=False,
        )

    assistant_text = "Reminder created successfully."
    return _voice_command_response(
        transcript=command_text,
        command_text=command_text,
        assistant_text=assistant_text,
        action_type="reminder",
        action_status="handled",
        detail=assistant_text,
        spoken=False,
        extra={"reminder": reminder.to_dict()},
    )


def _handle_voice_local_action(command_text: str, *, confirmed: bool) -> dict[str, Any]:
    from grandpa.local_actions import approve_pending_action, handle_local_action

    try:
        result = handle_local_action(command_text, execute=True)
        if confirmed and result.status == "requires_confirmation" and result.pending_action:
            result = approve_pending_action(result.pending_action.get("id"))
    except Exception as exc:
        assistant_text = "I couldn't process that desktop command."
        return _voice_command_response(
            transcript=command_text,
            command_text=command_text,
            assistant_text=assistant_text,
            action_type="desktop",
            action_status="error",
            detail=str(exc),
            spoken=False,
        )

    if result.should_fallback:
        assistant_text = "I don't know how to do that yet."
        return _voice_command_response(
            transcript=command_text,
            command_text=command_text,
            assistant_text=assistant_text,
            action_type="chat",
            action_status="unsupported",
            detail=assistant_text,
            spoken=False,
        )

    action_status = _voice_action_status(result.status)
    assistant_text = _friendly_voice_message(
        action_status,
        result.tts_text or result.message or "",
    )
    return _voice_command_response(
        transcript=command_text,
        command_text=command_text,
        assistant_text=assistant_text,
        action_type="desktop",
        action_status=action_status,
        detail=result.message or assistant_text,
        spoken=False,
        extra={
            "local_action": {
                "status": result.status,
                "kind": result.kind,
                "target": result.target,
                "permission": result.permission,
                "pending_action": result.pending_action,
            }
        },
    )


def _voice_action_status(status: str) -> str:
    if status == "requires_confirmation":
        return "needs_confirmation"
    if status in {"handled", "blocked", "unsupported", "error"}:
        return status
    if status == "cancelled":
        return "blocked"
    return "unsupported"


def _friendly_voice_message(action_status: str, fallback: str = "") -> str:
    if action_status == "needs_confirmation":
        return "This action needs confirmation."
    if action_status == "blocked":
        return "That action is blocked for safety."
    if action_status == "unsupported":
        return "I don't know how to do that yet."
    if action_status == "handled":
        return "Done."
    return fallback or "I couldn't process that command."


def _voice_command_response(
    *,
    transcript: str,
    command_text: str,
    assistant_text: str,
    action_type: str,
    action_status: str,
    detail: str,
    spoken: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "transcript": transcript,
        "command_text": command_text,
        "assistant_text": assistant_text,
        "message": assistant_text,
        "action": {
            "type": action_type,
            "status": action_status,
            "message": assistant_text,
            "detail": detail,
        },
        "spoken": spoken,
        "ok": action_status not in {"blocked", "error"},
        "status": action_status,
        "action_status": action_status,
        "approval_required": action_status == "needs_confirmation",
    }
    if extra:
        payload.update(extra)
        local_action = extra.get("local_action")
        if isinstance(local_action, dict):
            pending_action = local_action.get("pending_action")
            confirmation_token = (
                pending_action.get("id")
                if action_status == "needs_confirmation" and isinstance(pending_action, dict)
                else None
            )
            payload["action"].update(
                {
                    "kind": local_action.get("kind"),
                    "target": local_action.get("target"),
                    "permission": local_action.get("permission"),
                    "pending_action": pending_action,
                }
            )
            if confirmation_token:
                payload["confirmation_token"] = confirmation_token
                payload["action"]["confirmation_token"] = confirmation_token
    return payload


def _get_voice_history_store(request: Request):
    from grandpa.voice.history import VoiceCommandHistoryStore

    store = getattr(request.app.state, "voice_history_store", None)
    if store is None:
        store = VoiceCommandHistoryStore()
        request.app.state.voice_history_store = store
    return store


def _get_wake_word_session(request: Request):
    from grandpa.voice.wake_word import WakeWordSession

    session = getattr(request.app.state, "wake_word_session", None)
    if session is None:
        session = WakeWordSession()
        request.app.state.wake_word_session = session
    return session


def _get_voice_loop_session(request: Request):
    from grandpa.voice.loop import VoiceLoopSession

    session = getattr(request.app.state, "voice_loop_session", None)
    if session is None:
        session = VoiceLoopSession(_get_wake_word_session(request))
        request.app.state.voice_loop_session = session
    return session


def _get_conversation_session(request: Request):
    from grandpa.memory.conversation import ConversationSession

    session = getattr(request.app.state, "conversation_session", None)
    if session is None:
        session = ConversationSession()
        request.app.state.conversation_session = session
    return session


def _record_conversation_exchange(request: Request, transcript: str, assistant_text: str) -> None:
    try:
        session = _get_conversation_session(request)
        session.add_user_message(transcript)
        session.add_assistant_message(assistant_text)
    except Exception:
        logger.debug("Failed to record conversation exchange", exc_info=True)


async def _read_voice_listen_payload(request: Request) -> dict[str, str | None]:
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Audio upload support requires multipart form parsing. Install the server dependencies and retry.",
            ) from exc

        text_value = form.get("text") or form.get("transcript")
        audio_value = form.get("audio") or form.get("file")
        audio_base64 = form.get("audio_base64")
        audio_format = form.get("audio_format") or form.get("format")
        if hasattr(audio_value, "read"):
            audio_bytes = await audio_value.read()
            audio_base64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None
            filename = getattr(audio_value, "filename", "")
            audio_format = audio_format or _audio_format_from_filename(filename)
        return {
            "text": str(text_value).strip() if text_value is not None else None,
            "audio_base64": str(audio_base64) if audio_base64 else None,
            "audio_format": str(audio_format).strip().lower().lstrip(".") if audio_format else None,
        }

    if content_type.startswith("application/octet-stream") or content_type.startswith("audio/"):
        audio_bytes = await request.body()
        return {
            "text": None,
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None,
            "audio_format": _audio_format_from_content_type(content_type),
        }

    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    text_value = data.get("text") or data.get("transcript")
    audio_base64 = data.get("audio_base64")
    audio_format = data.get("audio_format") or data.get("format")
    return {
        "text": str(text_value).strip() if text_value is not None else None,
        "audio_base64": str(audio_base64) if audio_base64 else None,
        "audio_format": str(audio_format).strip().lower().lstrip(".") if audio_format else None,
    }


def _audio_format_from_filename(filename: str) -> str | None:
    if "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].strip().lower()


def _audio_format_from_content_type(content_type: str) -> str | None:
    if "webm" in content_type:
        return "webm"
    if "mpeg" in content_type or "mp3" in content_type:
        return "mp3"
    if "mp4" in content_type or "m4a" in content_type:
        return "m4a"
    if "wav" in content_type or "wave" in content_type:
        return "wav"
    return None


def _record_voice_history(request: Request, result: dict[str, Any]) -> None:
    try:
        action = result.get("action") or {}
        _get_voice_history_store(request).add(
            transcript=result.get("transcript") or result.get("command_text") or "",
            assistant_response=result.get("assistant_text") or result.get("message") or "",
            action_type=str(action.get("type") or "none"),
            action_status=str(action.get("status") or result.get("status") or "unsupported"),
        )
    except Exception:
        logger.debug("Failed to record voice command history", exc_info=True)


def _raise_for_expected_voice_error(result: dict[str, Any]) -> None:
    if result.get("ok", True) is not False:
        return
    status = result.get("status")
    if status == "dependency_missing" or status == "tts_unavailable":
        raise HTTPException(status_code=503, detail=result.get("message") or result)
    if status == "microphone_unavailable":
        raise HTTPException(status_code=400, detail=result.get("message") or result)
    if status == "recognition_failed":
        raise HTTPException(status_code=422, detail=result.get("message") or result)


# ---- Feedback routes ----

feedback_router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


@feedback_router.post("")
async def submit_feedback(req: FeedbackScoreRequest, request: Request):
    """Submit feedback for a trace."""
    try:
        from grandpa.core.config import DEFAULT_CONFIG_DIR
        from grandpa.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="No trace database")

        store = TraceStore(db_path)
        updated = store.update_feedback(req.trace_id, req.score)
        store.close()

        if not updated:
            raise HTTPException(
                status_code=404, detail=f"Trace '{req.trace_id}' not found"
            )
        return {"status": "recorded", "trace_id": req.trace_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@feedback_router.get("/stats")
async def feedback_stats(request: Request):
    """Get feedback statistics."""
    return {"total": 0, "mean_score": 0.0}


# ---- Optimize routes ----

optimize_router = APIRouter(prefix="/v1/optimize", tags=["optimize"])


@optimize_router.get("/runs")
async def list_optimize_runs(request: Request):
    """List optimization runs."""
    try:
        from grandpa.core.config import DEFAULT_CONFIG_DIR
        from grandpa.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"runs": []}

        store = OptimizationStore(db_path)
        runs = store.list_runs()
        store.close()
        return {"runs": runs}
    except Exception as exc:
        logger.warning("Failed to list optimization runs: %s", exc)
        return {"runs": []}


@optimize_router.get("/runs/{run_id}")
async def get_optimize_run(run_id: str, request: Request):
    """Get optimization run details."""
    try:
        from grandpa.core.config import DEFAULT_CONFIG_DIR
        from grandpa.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"run_id": run_id, "status": "not_found"}

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        return {
            "run_id": run.run_id,
            "status": run.status,
            "benchmark": run.benchmark,
            "trials": len(run.trials),
            "best_trial_id": (run.best_trial.trial_id if run.best_trial else None),
        }
    except Exception as exc:
        logger.warning("Failed to get optimization run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "not_found"}


@optimize_router.post("/runs")
async def start_optimize_run(req: OptimizeRunRequest, request: Request):
    """Start a new optimization run."""
    return {"status": "started", "run_id": "placeholder"}


def include_all_routes(app) -> None:
    """Include all extended API routers in a FastAPI app."""
    from grandpa.server.approval_routes import (
        router as approval_router,  # noqa: PLC0415
    )

    app.include_router(approval_router)
    app.include_router(agents_router)
    app.include_router(memory_router)
    app.include_router(traces_router)
    app.include_router(telemetry_router)
    app.include_router(skills_router)
    app.include_router(user_skills_router)
    app.include_router(coding_router)
    app.include_router(knowledge_router)
    app.include_router(plugins_router)
    app.include_router(release_gate_router)
    app.include_router(burnin_router)
    app.include_router(audit_router)
    app.include_router(services_router)
    app.include_router(actions_router)
    app.include_router(desktop_operator_router)
    app.include_router(planner_router)
    app.include_router(agent_runtime_router)
    app.include_router(mcp_router)
    app.include_router(intent_router)
    app.include_router(sessions_router)
    app.include_router(budget_router)
    app.include_router(metrics_router)
    app.include_router(websocket_router)
    app.include_router(learning_router)
    app.include_router(speech_router)
    app.include_router(voice_router)
    app.include_router(conversation_router)
    app.include_router(feedback_router)
    app.include_router(optimize_router)

    # Agent Manager routes (if available)
    try:
        if hasattr(app.state, "agent_manager") and app.state.agent_manager:
            from grandpa.server.agent_manager_routes import (  # noqa: PLC0415
                create_agent_manager_router,
            )

            (
                agents_r,
                templates_r,
                global_r,
                tools_r,
                sendblue_r,
            ) = create_agent_manager_router(app.state.agent_manager)
            app.include_router(agents_r)
            app.include_router(templates_r)
            app.include_router(global_r)
            app.include_router(tools_r)
            app.include_router(sendblue_r)
    except ImportError:
        pass

    # WebSocket bridge for real-time agent events
    try:
        from grandpa.core.events import get_event_bus
        from grandpa.server.ws_bridge import create_ws_router

        ws_router = create_ws_router(get_event_bus())
        app.include_router(ws_router)
    except Exception:
        logger.debug("WebSocket bridge not available", exc_info=True)


__all__ = [
    "include_all_routes",
    "agents_router",
    "memory_router",
    "traces_router",
    "telemetry_router",
    "skills_router",
    "user_skills_router",
    "coding_router",
    "knowledge_router",
    "plugins_router",
    "release_gate_router",
    "burnin_router",
    "audit_router",
    "services_router",
    "actions_router",
    "desktop_operator_router",
    "planner_router",
    "agent_runtime_router",
    "mcp_router",
    "intent_router",
    "sessions_router",
    "budget_router",
    "metrics_router",
    "websocket_router",
    "learning_router",
    "speech_router",
    "voice_router",
    "conversation_router",
    "feedback_router",
    "optimize_router",
]
