"""``Grandpa serve`` — OpenAI-compatible API server."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console

from grandpa.core.config import load_config
from grandpa.core.events import EventBus
from grandpa.engine import (
    discover_engines,
    discover_models,
    get_engine,
)
from grandpa.intelligence import (
    merge_discovered_models,
    register_builtin_models,
)

logger = logging.getLogger(__name__)


def _generate_and_persist_api_key(console: Console) -> str:
    """Mint a local API key on first run and write it to ``config.toml``.

    Returns the key. If it cannot be persisted the key is still returned and
    used for this process, so the server stays authenticated either way — the
    operator just has to re-read it from the console next start.
    """
    import tomlkit

    from grandpa.core.config import DEFAULT_CONFIG_DIR
    from grandpa.server.auth_middleware import API_KEY_ENV, generate_api_key

    key = generate_api_key()
    config_path = Path(
        os.environ.get("Grandpa_CONFIG", DEFAULT_CONFIG_DIR / "config.toml")
    )
    persisted = False
    try:
        if config_path.exists():
            doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        else:
            doc = tomlkit.document()
            config_path.parent.mkdir(parents=True, exist_ok=True)
        server_table = doc.get("server")
        if server_table is None:
            server_table = tomlkit.table()
            doc["server"] = server_table
        auth_table = server_table.get("auth")
        if auth_table is None:
            auth_table = tomlkit.table()
            server_table["auth"] = auth_table
        auth_table["api_key"] = key
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        persisted = True
    except OSError as exc:
        logger.debug("Could not persist generated API key: %s", exc)

    console.print(
        "\n[green bold]Generated a local API key[/green bold] "
        "(the API is authenticated by default).\n"
        f"  Key: [cyan]{key}[/cyan]\n"
        "  Use: [cyan]Authorization: Bearer <key>[/cyan]\n"
        + (
            f"  Saved to: [cyan]{config_path}[/cyan]\n"
            if persisted
            else "  [yellow]Could not save it — set "
            f"{API_KEY_ENV} to reuse this key.[/yellow]\n"
        )
        + "  Run with [cyan]--no-auth[/cyan] to serve unauthenticated.\n"
    )
    return key


@click.command()
@click.option("--host", default=None, help="Bind address (default: config).")
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port number (default: config).",
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option(
    "-a",
    "--agent",
    "agent_name",
    default=None,
    help="Agent for non-streaming requests (simple, orchestrator, react).",
)
@click.option(
    "--allow-insecure-bind",
    is_flag=True,
    help="Allow binding non-loopback without an API key (unsafe on untrusted networks).",
)
@click.option(
    "--no-auth",
    is_flag=True,
    help="Serve without an API key. Any local process can then drive the desktop.",
)
def serve(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    allow_insecure_bind: bool,
    no_auth: bool,
) -> None:
    """Start the OpenAI-compatible API server."""
    console = Console(stderr=True)

    # Check for server dependencies
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Server dependencies not installed.[/red bold]\n\n"
            "Install the server extra:\n"
            "  [cyan]uv sync --extra server[/cyan]"
        )
        sys.exit(1)

    config = load_config()

    # Resolve host/port from CLI args or config
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Set up engine
    register_builtin_models()
    bus = EventBus(record_history=False)

    # Set up telemetry
    telem_store = None
    if config.telemetry.enabled:
        try:
            from pathlib import Path

            from grandpa.telemetry.store import TelemetryStore

            db_path = Path(config.telemetry.db_path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            telem_store = TelemetryStore(str(db_path))
            telem_store.subscribe_to_bus(bus)
        except Exception as exc:
            logger.debug("Telemetry store init failed: %s", exc)

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Apply security guardrails
    from grandpa.security import setup_security

    sec = setup_security(config, engine, bus)
    engine = sec.engine

    # Wrap engine with InstrumentedEngine for telemetry recording
    try:
        from grandpa.telemetry.instrumented_engine import InstrumentedEngine

        engine = InstrumentedEngine(engine, bus)
    except Exception as exc:
        logger.debug("Engine instrumentation failed: %s", exc)

    # Discover models
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    # Resolve model
    if model_name is None:
        model_name = config.server.model or config.intelligence.default_model
    if not model_name:
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model_name = engine_models[0]
        else:
            console.print("[red]No model available on engine.[/red]")
            sys.exit(1)

    # Resolve agent
    agent = None
    agent_key = agent_name or config.server.agent
    if agent_key:
        try:
            from grandpa.agents import load_builtin_agents

            load_builtin_agents()
            from grandpa.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                agent_kwargs = {"bus": bus}
                if sec.capability_policy is not None:
                    agent_kwargs["capability_policy"] = sec.capability_policy

                # Load tools for agents that support them
                if getattr(agent_cls, "accepts_tools", False):
                    from grandpa.tools import load_builtin_tools

                    load_builtin_tools()
                    from grandpa.core.registry import ToolRegistry
                    from grandpa.tools._stubs import BaseTool

                    _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                    configured = config.agent.tools
                    if configured:
                        if isinstance(configured, list):
                            allowed = {
                                t.strip()
                                for t in configured
                                if isinstance(t, str) and t.strip()
                            }
                        else:
                            allowed = {
                                t.strip() for t in configured.split(",") if t.strip()
                            }
                    else:
                        allowed = _DEFAULT_TOOLS

                    tools = []
                    for name in ToolRegistry.keys():
                        if name not in allowed:
                            continue
                        tool_cls = ToolRegistry.get(name)
                        if isinstance(tool_cls, type) and issubclass(
                            tool_cls, BaseTool
                        ):
                            tools.append(tool_cls())
                        elif isinstance(tool_cls, BaseTool):
                            tools.append(tool_cls)
                    if tools:
                        agent_kwargs["tools"] = tools

                if getattr(agent_cls, "accepts_tools", False):
                    agent_kwargs["max_turns"] = config.agent.max_turns

                agent = agent_cls(engine, model_name, **agent_kwargs)
        except Exception as exc:
            import traceback

            console.print(f"[yellow]Agent '{agent_key}' failed to load: {exc}[/yellow]")
            traceback.print_exc()

    # Set up speech backend
    speech_backend = None
    try:
        from grandpa.speech._discovery import get_speech_backend

        speech_backend = get_speech_backend(config)
        if speech_backend:
            console.print(f"  Speech: [cyan]{speech_backend.backend_id}[/cyan]")
    except Exception as exc:
        logger.debug("Speech backend discovery failed: %s", exc)

    # Create app
    from grandpa.server.app import create_app

    # Set up agent manager
    agent_manager = None
    if config.agent_manager.enabled:
        try:
            from pathlib import Path

            from grandpa.agents.manager import AgentManager

            am_db = config.agent_manager.db_path or str(
                Path("~/.grandpa/agents.db").expanduser()
            )
            agent_manager = AgentManager(db_path=am_db)
        except Exception as exc:
            logger.debug("Agent manager init failed: %s", exc)

    # Set up agent scheduler for cron/interval agents
    agent_scheduler = None
    if agent_manager is not None:
        try:
            from grandpa.agents.executor import AgentExecutor
            from grandpa.agents.scheduler import AgentScheduler

            _trace_store = None
            try:
                if config.traces.enabled:
                    from grandpa.traces.store import TraceStore

                    _trace_store = TraceStore(db_path=config.traces.db_path)
            except Exception:
                pass

            executor = AgentExecutor(
                manager=agent_manager,
                event_bus=bus,
                trace_store=_trace_store,
            )
            from grandpa.system import SystemBuilder

            system = SystemBuilder(config).build()
            executor.set_system(system)

            agent_scheduler = AgentScheduler(
                manager=agent_manager,
                executor=executor,
                event_bus=bus,
            )
            for ag in agent_manager.list_agents():
                sched_type = ag.get("config", {}).get("schedule_type", "manual")
                if sched_type in ("cron", "interval") and ag["status"] not in (
                    "archived",
                    "error",
                ):
                    agent_scheduler.register_agent(ag["id"])
            agent_scheduler.start()
            console.print("  Scheduler: [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Agent scheduler init failed: %s", exc)

    # Set up memory backend for context injection
    memory_backend = None
    if config.agent.context_from_memory:
        try:
            from grandpa.tools.storage import load_storage_backends

            load_storage_backends()
            from grandpa.core.registry import MemoryRegistry

            mem_key = config.memory.default_backend
            if MemoryRegistry.contains(mem_key):
                # Only the sqlite backend takes db_path; passing it to the
                # others raises TypeError, which the except below turned into
                # memory being silently absent from the server.
                if mem_key == "sqlite":
                    memory_backend = MemoryRegistry.create(
                        mem_key,
                        db_path=config.memory.db_path,
                    )
                else:
                    memory_backend = MemoryRegistry.create(mem_key)
                console.print("  Memory:    [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Memory backend init failed: %s", exc)

    # The API is loopback-first and authenticated by default. Every route under
    # /v1 and /api can read personal memory or drive the desktop, so an
    # unauthenticated bind is opt-in via --no-auth rather than the default.
    from grandpa.server.auth_middleware import (
        api_key_from_env,
        check_bind_safety,
    )

    api_key = api_key_from_env() or config.server.auth.api_key.strip()

    if no_auth:
        if api_key:
            console.print(
                "[yellow]--no-auth: ignoring the configured API key and "
                "serving unauthenticated.[/yellow]"
            )
        api_key = ""
        console.print(
            "[yellow]Warning:[/yellow] authentication is disabled. Any local "
            "process can read memory and drive this desktop through the API."
        )
    elif not api_key:
        api_key = _generate_and_persist_api_key(console)

    check_bind_safety(
        bind_host,
        api_key=api_key,
        allow_insecure_bind=allow_insecure_bind,
    )

    # Log credential status at startup
    from grandpa.core.credentials import TOOL_CREDENTIALS, get_credential_status

    _cred_parts = []
    for _tool_name in sorted(TOOL_CREDENTIALS):
        _status = get_credential_status(_tool_name)
        _set = sum(1 for v in _status.values() if v)
        _total = len(_status)
        if _set > 0:
            _cred_parts.append(f"{_tool_name}: {_set}/{_total} keys")
    if _cred_parts:
        logger.info("Credentials loaded — %s", ", ".join(_cred_parts))

    app = create_app(
        engine,
        model_name,
        agent=agent,
        bus=bus,
        engine_name=engine_name,
        agent_name=agent_key or "",
        config=config,
        memory_backend=memory_backend,
        speech_backend=speech_backend,
        agent_manager=agent_manager,
        agent_scheduler=agent_scheduler,
        api_key=api_key,
        cors_origins=config.server.cors_origins,
    )

    console.print(
        f"[green]Starting Grandpa API server[/green]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]\n"
        f"  Model:  [cyan]{model_name}[/cyan]\n"
        f"  Agent:  [cyan]{agent_key or 'none'}[/cyan]\n"
        f"  URL:    [cyan]http://{bind_host}:{bind_port}[/cyan]"
    )

    # Warn about wildcard CORS on non-loopback
    import ipaddress as _ipa

    try:
        _is_loop = _ipa.ip_address(bind_host).is_loopback
    except ValueError:
        _is_loop = bind_host in ("localhost", "")

    if not _is_loop and "*" in config.server.cors_origins:
        console.print(
            "[yellow bold]WARNING:[/yellow bold] Wildcard CORS with credentials "
            "enabled on non-loopback interface. This allows any website to make "
            "authenticated requests to your instance."
        )

    import uvicorn

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
