"""FastAPI application factory for the Grandpa API server."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI

from grandpa.server.api_routes import include_all_routes
from grandpa.server.routes import router
from grandpa.server.upload_router import router as upload_router

logger = logging.getLogger(__name__)


def create_app(
    engine,
    model: str,
    *,
    agent=None,
    bus=None,
    engine_name: str = "",
    agent_name: str = "",
    config=None,
    memory_backend=None,
    speech_backend=None,
    agent_manager=None,
    agent_scheduler=None,
    api_key: str = "",
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    engine:
        The inference engine to use for completions.
    model:
        Default model name.
    agent:
        Optional agent instance for agent-mode completions.
    bus:
        Optional event bus for telemetry.
    config:
        Optional GrandpaConfig for other settings.
    """
    app = FastAPI(
        title="Grandpa API",
        description="OpenAI-compatible API server for Grandpa",
        version="0.1.0",
    )

    from fastapi.middleware.cors import CORSMiddleware

    _origins = cors_origins if cors_origins is not None else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store dependencies in app state
    app.state.engine = engine
    app.state.model = model
    app.state.agent = agent
    app.state.bus = bus
    app.state.engine_name = engine_name
    app.state.agent_name = agent_name or (
        getattr(agent, "agent_id", None) if agent else None
    )
    app.state.config = config
    app.state.memory_backend = memory_backend
    app.state.speech_backend = speech_backend
    app.state.agent_manager = agent_manager
    app.state.agent_scheduler = agent_scheduler
    app.state.routine_scheduler_daemon = None
    app.state.session_start = time.time()

    # Wire up trace store if traces are enabled
    app.state.trace_store = None
    try:
        from grandpa.core.config import load_config
        from grandpa.traces.store import TraceStore

        cfg = config if config is not None else load_config()
        if cfg.traces.enabled:
            _trace_store = TraceStore(db_path=cfg.traces.db_path)
            app.state.trace_store = _trace_store
            _bus = getattr(app.state, "bus", None)
            if _bus is not None:
                _trace_store.subscribe_to_bus(_bus)
    except Exception:
        pass  # traces are optional; don't block server startup

    try:
        from grandpa.pc_control import initialize_pc_control_store

        @app.on_event("startup")
        async def _startup_pc_control_store() -> None:
            initialize_pc_control_store()
    except Exception as exc:
        logger.debug("PC control approval store init skipped: %s", exc)

    try:
        from grandpa.scheduler_daemon import BackgroundSchedulerDaemon

        routine_scheduler = BackgroundSchedulerDaemon()
        app.state.routine_scheduler_daemon = routine_scheduler

        @app.on_event("startup")
        async def _startup_routine_scheduler() -> None:
            routine_scheduler.start()

        @app.on_event("shutdown")
        async def _shutdown_routine_scheduler() -> None:
            routine_scheduler.stop()
    except Exception as exc:
        logger.debug("Routine scheduler daemon init skipped: %s", exc)

    app.include_router(router)
    app.include_router(upload_router)
    include_all_routes(app)

    # Add security headers middleware
    try:
        from grandpa.server.middleware import create_security_middleware

        middleware_cls = create_security_middleware()
        if middleware_cls is not None:
            app.add_middleware(middleware_cls)
    except Exception as exc:
        logger.debug("Security middleware init skipped: %s", exc)

    # API key authentication middleware
    if api_key:
        try:
            from grandpa.server.auth_middleware import AuthMiddleware

            app.add_middleware(AuthMiddleware, api_key=api_key)
        except Exception as exc:
            logger.debug("Auth middleware init skipped: %s", exc)

    return app


__all__ = ["create_app"]
