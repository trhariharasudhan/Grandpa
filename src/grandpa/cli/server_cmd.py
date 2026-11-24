"""``grandpa server`` -- the Pironman home server (P2).

* ``grandpa server pair --pc http://192.168.1.20:8000 --code 123456`` --
  pair this node with the Windows PC, the same way a phone pairs (D1).
* ``grandpa server status`` -- is the PC set, paired and reachable?
* ``grandpa server --headless`` -- run the node: API, memory, scheduler,
  devices and workflows. Every model call goes to the PC over the LAN.

The PC runs the normal ``grandpa serve`` and must allow it once with
``grandpa config set server.device_llm true``.
"""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console

logger = logging.getLogger(__name__)

_FIX_PC_URL = (
    "Set the PC address, e.g. GRANDPA_PC_URL=http://192.168.1.20:8000, or pass --pc."
)
_FIX_TOKEN = (
    "Pair first: on the PC run 'grandpa devices pair', then here run "
    "'grandpa server pair --pc <url> --code <code>'."
)


def _pc_url(option: str | None) -> str:
    from grandpa.engine.remote import pc_url_from_env

    return (option or "").strip().rstrip("/") or pc_url_from_env()


@click.group(invoke_without_command=True)
@click.option(
    "--headless",
    is_flag=True,
    help="Run the home-server node (no desktop, model on the PC).",
)
@click.option("--pc", "pc_option", default=None, help="The PC, e.g. http://ip:8000.")
@click.option("--host", default=None, help="Bind address (default: config).")
@click.option("--port", default=None, type=int, help="Port (default: config).")
@click.option("-m", "--model", "model_name", default=None, help="PC model to ask for.")
@click.pass_context
def server(
    ctx: click.Context,
    headless: bool,
    pc_option: str | None,
    host: str | None,
    port: int | None,
    model_name: str | None,
) -> None:
    """The Pironman home server: pair, status, or run with --headless."""
    if ctx.invoked_subcommand is not None:
        return
    console = Console(stderr=True)
    if not headless:
        console.print(
            "On the Windows PC use [cyan]grandpa serve[/cyan].\n"
            "On the home server use [cyan]grandpa server --headless[/cyan] "
            "(pair first: [cyan]grandpa server pair[/cyan])."
        )
        return
    _run_headless(console, _pc_url(pc_option), host, port, model_name)


def _run_headless(
    console: Console,
    pc_url: str,
    host: str | None,
    port: int | None,
    model_name: str | None,
) -> None:
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Server dependencies not installed.[/red bold]\n"
            "  [cyan]uv sync --extra server[/cyan]"
        )
        sys.exit(1)

    from grandpa.core.config import load_config
    from grandpa.core.events import EventBus
    from grandpa.engine.remote import RemotePCEngine, pc_token

    if not pc_url:
        console.print(f"[red]No PC address.[/red] {_FIX_PC_URL}")
        sys.exit(1)
    token = pc_token()
    if not token:
        console.print(f"[red]This node is not paired with the PC.[/red] {_FIX_TOKEN}")
        sys.exit(1)

    config = load_config()
    model = model_name or config.server.model or config.intelligence.default_model
    engine = RemotePCEngine(pc_url, token, model=model or "")
    if engine.health():
        console.print(f"  PC:      [cyan]{pc_url}[/cyan] (paired, reachable)")
    else:
        # Not fatal: the PC may be asleep. Memory, reminders and workflows
        # keep working; chat answers once the PC is back.
        console.print(
            f"  PC:      [yellow]{pc_url} not reachable now[/yellow]; "
            "chat waits for it, the rest runs."
        )

    memory_backend = None
    try:
        from grandpa.tools.storage import load_storage_backends

        load_storage_backends()
        from grandpa.core.registry import MemoryRegistry

        key = config.memory.default_backend
        if MemoryRegistry.contains(key):
            memory_backend = (
                MemoryRegistry.create(key, db_path=config.memory.db_path)
                if key == "sqlite"
                else MemoryRegistry.create(key)
            )
            console.print("  Memory:  [cyan]active[/cyan]")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Memory backend init failed: %s", exc)

    from grandpa.cli.serve import _generate_and_persist_api_key, _resolve_api_key
    from grandpa.server.auth_middleware import check_bind_safety

    # Never unauthenticated: the node is meant to listen on the LAN.
    api_key = _resolve_api_key(config, console) or _generate_and_persist_api_key(
        console
    )
    bind_host = host or config.server.host
    bind_port = port or config.server.port
    check_bind_safety(bind_host, api_key=api_key, allow_insecure_bind=False)

    from grandpa.server.app import create_app

    app = create_app(
        engine,
        model or "pc",
        bus=EventBus(record_history=False),
        engine_name="pc",
        config=config,
        memory_backend=memory_backend,
        api_key=api_key,
        cors_origins=config.server.cors_origins,
        headless=True,
    )
    console.print(
        "[green]Starting the Grandpa home server (headless)[/green]\n"
        "  Serves:  chat, memory, scheduler, devices, workflows\n"
        f"  URL:     [cyan]http://{bind_host}:{bind_port}[/cyan]"
    )
    import uvicorn

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")


@server.command("pair")
@click.option("--pc", "pc_option", default=None, help="The PC, e.g. http://ip:8000.")
@click.option("--code", required=True, help="The 6-digit code from the PC.")
@click.option("--name", default="Pironman", show_default=True, help="Name on the PC.")
def pair(pc_option: str | None, code: str, name: str) -> None:
    """Pair this node with the PC (run 'grandpa devices pair' there first)."""
    import httpx

    from grandpa.engine.remote import PC_TOKEN_ENV, PC_TOKEN_SECRET

    console = Console()
    pc_url = _pc_url(pc_option)
    if not pc_url:
        raise click.ClickException(_FIX_PC_URL)
    try:
        resp = httpx.post(
            f"{pc_url}/v1/devices/pair",
            json={"code": code.strip(), "name": name},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"Could not reach the PC at {pc_url} ({type(exc).__name__}). "
            "Is 'grandpa serve --host 0.0.0.0' running there?"
        ) from exc
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "")
        except ValueError:
            detail = ""
        raise click.ClickException(
            f"The PC refused the code: {detail or resp.status_code}"
        )
    data = resp.json()
    token = data.get("token", "")
    saved = False
    where = ""
    try:
        from grandpa.security.secret_store import SecretStore

        store = SecretStore()
        if store.secure:
            store.set(PC_TOKEN_SECRET, token)
            saved = store.get(PC_TOKEN_SECRET) == token
            where = store.describe()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Secret store unavailable: %s", type(exc).__name__)
    console.print(
        f"[green]Paired[/green] as {data.get('name', name)} ({data.get('device_id', '')})."
    )
    if saved:
        console.print(f"  Token saved in the {where} store.")
    else:
        # No encrypted store on this machine: show it once, like the phone.
        console.print(
            "  No encrypted store here. Put this in the node's environment "
            f"(it is shown once):\n  {PC_TOKEN_ENV}={token}"
        )
    console.print(f"  Next: GRANDPA_PC_URL={pc_url} grandpa server --headless")


@server.command("status")
@click.option("--pc", "pc_option", default=None, help="The PC, e.g. http://ip:8000.")
def status(pc_option: str | None) -> None:
    """Is the PC set, is this node paired, can it reach the PC?"""
    from grandpa.engine.remote import RemotePCEngine, pc_token

    console = Console()
    pc_url = _pc_url(pc_option)
    token = pc_token()
    console.print(f"  PC address: {pc_url or '[red]not set[/red]'}")
    console.print(f"  Paired:     {'yes' if token else '[red]no[/red]'}")
    if not pc_url or not token:
        console.print(f"  Fix: {_FIX_PC_URL if not pc_url else _FIX_TOKEN}")
        sys.exit(1)
    engine = RemotePCEngine(pc_url, token)
    try:
        ok = engine.health()
    finally:
        engine.close()
    console.print(f"  Reachable:  {'yes' if ok else '[red]no[/red]'}")
    if not ok:
        console.print(
            "  Fix: start 'grandpa serve --host 0.0.0.0' on the PC and check "
            "the address."
        )
        sys.exit(1)
