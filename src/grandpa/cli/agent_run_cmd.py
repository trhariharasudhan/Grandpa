"""CLI commands for Grandpa Agent Runtime V1."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from grandpa.agent.runtime import AgentRuntime
from grandpa.memory.service import MemoryService


@click.group("agent")
def agent_group() -> None:
    """Grandpa Agent Runtime V1 commands."""


@agent_group.command("preview")
@click.argument("goal")
def preview(goal: str) -> None:
    """Preview the execution plan for a goal without executing actions."""
    console = Console()
    runtime = AgentRuntime()
    result = runtime.run(goal, dry_run=True)

    console.print(runtime.format_output(result))


@agent_group.command("run")
@click.argument("goal")
@click.option(
    "--yes/--no",
    "auto_approve",
    default=False,
    help="Auto-approve risky commands.",
)
def run(goal: str, auto_approve: bool) -> None:
    """Run the Agent Runtime for a specific goal."""
    console = Console()

    svc = MemoryService.get_instance()
    # Check if memory retrieval is enabled
    if not svc.session_memory_enabled():
        console.print("[yellow]Warning: Memory retrieval is disabled for this session.[/yellow]")

    # Setup safety confirmation callback
    def confirm_callback(prompt: str) -> bool:
        if auto_approve:
            return True
        return click.confirm(prompt, default=False)

    # Setup progress reporting callback
    def progress_callback(msg: str) -> None:
        console.print(f"[cyan]●[/cyan] {msg}")

    # Set state as running in DB
    svc.preferences.set_preference("agent_active_status", "running")
    svc.preferences.set_preference("agent_cancel_request", "false")

    runtime = AgentRuntime(
        confirm_callback=confirm_callback,
        progress_callback=progress_callback,
    )

    try:
        # Run execution loop
        result = runtime.run(goal, dry_run=False)
        formatted = runtime.format_output(result)

        # Save trace and status
        svc.preferences.set_preference("agent_active_status", result.state.value)
        svc.preferences.set_preference("agent_last_trace", formatted)

        console.print()
        console.print(formatted)
    except Exception as exc:
        svc.preferences.set_preference("agent_active_status", "failed")
        console.print(f"[red]Error: {exc}[/red]")
        raise SystemExit(1)


@agent_group.command("status")
def status() -> None:
    """Show the status of the active or last agent execution."""
    console = Console()
    svc = MemoryService.get_instance()
    status_val = svc.preferences.get_preference("agent_active_status")

    if not status_val:
        console.print("[yellow]No active or historical agent run found.[/yellow]")
        return

    table = Table(title="Agent Runtime Status")
    table.add_column("Attribute", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Execution State", status_val.upper())

    console.print(table)


@agent_group.command("trace")
def trace() -> None:
    """Show the trace logs of the last agent execution."""
    console = Console()
    svc = MemoryService.get_instance()
    trace_val = svc.preferences.get_preference("agent_last_trace")

    if not trace_val:
        console.print("[yellow]No historical trace found.[/yellow]")
        return

    console.print("[bold cyan]Last Agent Execution Trace:[/bold cyan]")
    console.print(trace_val)


@agent_group.command("cancel")
def cancel() -> None:
    """Request cancellation of the active running agent task."""
    console = Console()
    svc = MemoryService.get_instance()
    svc.preferences.set_preference("agent_cancel_request", "true")
    svc.preferences.set_preference("agent_active_status", "cancelled")

    console.print("[red]Cancellation request sent to active agent run.[/red]")
