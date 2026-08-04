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
        console.print(
            "[yellow]Warning: Memory retrieval is disabled for this session.[/yellow]"
        )

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


# ---------------------------------------------------------------------------
# Agent Execution V2 Click Commands
# ---------------------------------------------------------------------------


@agent_group.command("inspect")
@click.argument("goal")
@click.option("--workspace", default="D:\\Grandpa", help="Workspace root directory.")
def inspect(goal: str, workspace: str) -> None:
    """Run read-only workspace and repository inspection."""
    console = Console()
    runtime = AgentRuntime()
    report_res = runtime.inspect_project(goal, workspace)
    from grandpa.agent.execution import generate_sanitized_report

    console.print(generate_sanitized_report(report_res))


@agent_group.command("diagnose")
@click.argument("goal")
@click.option("--workspace", default="D:\\Grandpa", help="Workspace root directory.")
@click.option("--db-path", default="", help="Custom approvals DB path.")
def diagnose(goal: str, workspace: str, db_path: str) -> None:
    """Run diagnostics and generate a safe patch proposal."""
    console = Console()
    runtime = AgentRuntime()
    res = runtime.diagnose(goal, workspace, db_path=db_path)
    if isinstance(res, str):
        console.print(f"[red]Error: {res}[/red]")
        raise SystemExit(1)

    from grandpa.agent.execution import format_proposal_preview

    console.print("[green]Diagnostics complete. Patch proposal generated:[/green]")
    console.print(format_proposal_preview(res))


@agent_group.group("patch")
def patch_group() -> None:
    """Manage patch proposals and approvals."""


@patch_group.command("preview")
@click.option("--db-path", default="", help="Custom approvals DB path.")
def patch_preview(db_path: str) -> None:
    """List and preview all pending patch proposals."""
    console = Console()
    from grandpa.agent.execution import PatchApprovalManager, format_proposal_preview

    mgr = PatchApprovalManager(db_path=db_path)
    pending = mgr.store.list_pending()
    if not pending:
        console.print("[yellow]No pending patch proposals.[/yellow]")
        return
    for act in pending:
        prop = mgr.get_proposal(act.id)
        if prop:
            console.print(format_proposal_preview(prop))
            console.print("=" * 40)


@patch_group.command("show")
@click.argument("proposal_id")
@click.option("--db-path", default="", help="Custom approvals DB path.")
def patch_show(proposal_id: str, db_path: str) -> None:
    """Show details of a specific patch proposal."""
    console = Console()
    from grandpa.agent.execution import PatchApprovalManager, format_proposal_preview

    mgr = PatchApprovalManager(db_path=db_path)
    prop = mgr.get_proposal(proposal_id)
    if not prop:
        console.print(f"[red]Proposal '{proposal_id}' not found.[/red]")
        return
    console.print(format_proposal_preview(prop))


@patch_group.command("approve")
@click.argument("proposal_id")
@click.option("--db-path", default="", help="Custom approvals DB path.")
def patch_approve(proposal_id: str, db_path: str) -> None:
    """Approve a patch proposal."""
    console = Console()
    from grandpa.agent.execution import PatchApprovalManager

    mgr = PatchApprovalManager(db_path=db_path)
    mgr.approve_proposal(proposal_id)
    console.print(f"[green]Approved patch proposal '{proposal_id}'.[/green]")


@patch_group.command("reject")
@click.argument("proposal_id")
@click.option("--db-path", default="", help="Custom approvals DB path.")
def patch_reject(proposal_id: str, db_path: str) -> None:
    """Reject a patch proposal."""
    console = Console()
    from grandpa.agent.execution import PatchApprovalManager

    mgr = PatchApprovalManager(db_path=db_path)
    mgr.reject_proposal(proposal_id)
    console.print(f"[red]Rejected patch proposal '{proposal_id}'.[/red]")


@patch_group.command("apply")
@click.argument("proposal_id")
@click.option("--workspace", default="D:\\Grandpa", help="Workspace root directory.")
@click.option("--db-path", default="", help="Custom approvals DB path.")
def patch_apply(proposal_id: str, workspace: str, db_path: str) -> None:
    """Apply an approved patch proposal to the workspace."""
    console = Console()
    runtime = AgentRuntime()
    report_res = runtime.apply_patch(proposal_id, workspace, db_path=db_path)
    from grandpa.agent.execution import generate_sanitized_report

    console.print(generate_sanitized_report(report_res))


@agent_group.command("validate")
@click.option("--workspace", default="D:\\Grandpa", help="Workspace root directory.")
def validate(workspace: str) -> None:
    """Run lint, compile, and git diff check validations."""
    console = Console()
    from grandpa.agent.execution import DiagnosticCommand, run_catalog_command

    cmd_compile = DiagnosticCommand(
        args=["python", "-m", "compileall", "-q", "src", "tests", "scripts"],
        cwd=workspace,
    )
    res_compile = run_catalog_command(cmd_compile)

    cmd_ruff = DiagnosticCommand(
        args=["uv", "run", "ruff", "check", "src", "tests"],
        cwd=workspace,
    )
    res_ruff = run_catalog_command(cmd_ruff)

    cmd_diff = DiagnosticCommand(
        args=["git", "diff", "--check"],
        cwd=workspace,
    )
    res_diff = run_catalog_command(cmd_diff)

    console.print(f"Compile check exit code: {res_compile.exit_code}")
    console.print(f"Ruff check exit code   : {res_ruff.exit_code}")
    console.print(f"Git diff check exit code: {res_diff.exit_code}")


@agent_group.command("report")
def report() -> None:
    """View the last execution report summary from memory."""
    console = Console()
    svc = MemoryService.get_instance()
    val = svc.preferences.get_preference("last_validation_result")
    if not val:
        console.print("[yellow]No historical execution report found.[/yellow]")
        return
    console.print(f"Last Validation Outcome: [green]{val}[/green]")


@agent_group.command("rollback")
@click.argument("execution_id")
@click.option("--workspace", default="D:\\Grandpa", help="Workspace root directory.")
def rollback(execution_id: str, workspace: str) -> None:
    """Roll back applied changes by restoringpre-existing .bak files."""
    console = Console()
    # Find any .bak files in the workspace and restore them
    import shutil
    from pathlib import Path

    restored = []

    for p in Path(workspace).rglob("*.bak"):
        orig = p.with_suffix("")
        try:
            shutil.copy2(str(p), str(orig))
            p.unlink(missing_ok=True)
            restored.append(str(orig.relative_to(Path(workspace))))
        except Exception as exc:
            console.print(f"[red]Failed to restore '{orig}': {exc}[/red]")

    if restored:
        console.print(
            f"[green]Successfully rolled back changes in: {', '.join(restored)}[/green]"
        )
    else:
        console.print("[yellow]No backups found for rollback.[/yellow]")
