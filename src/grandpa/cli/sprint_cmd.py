"""CLI group for Autonomous Sprint Runner V1."""

from __future__ import annotations

from pathlib import Path

import click

from grandpa.agent.development.registry import MultiProjectRegistry
from grandpa.agent.development.sprint import SprintRunner


def _get_project_path() -> str:
    try:
        registry = MultiProjectRegistry()
        active = registry.get_active_project()
        if active and Path(active.project_path).exists():
            return active.project_path
    except Exception:
        pass

    default_path = "D:\\Grandpa"
    if Path(default_path).exists():
        return default_path
    return str(Path.cwd())


@click.group("sprint")
def sprint_group() -> None:
    """Grandpa Autonomous Sprint Runner commands."""
    pass


@sprint_group.command("preview")
def sprint_preview() -> None:
    """Preview the next sprint plan without executing writes."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint, msg = runner.preview_sprint()
        if not sprint:
            click.echo(f"Failed to generate sprint preview: {msg}")
            return
        click.echo("Sprint Plan Preview:")
        click.echo(f"  Project: {sprint.project_name}")
        click.echo(f"  Task ID: {sprint.task_id}")
        click.echo(f"  Risk   : {sprint.risk_level.upper()}")
        click.echo("Steps:")
        for step in sprint.sprint_plan:
            click.echo(f"  {step}")
        click.echo(f"\nMessage: {msg}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("start")
@click.option("--approve", is_flag=True, default=False, help="Approve files write execution.")
def sprint_start(approve: bool) -> None:
    """Start or resume the current sprint."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint = runner.load_sprint()

        # Auto-preview if none exists
        if not sprint:
            sprint, _ = runner.preview_sprint()

        if not sprint:
            click.echo("No pending sprint could be created.")
            return

        if not approve and sprint.approval_state != "approved":
            click.echo("Sprint Plan Proposed:")
            for step in sprint.sprint_plan:
                click.echo(f"  {step}")
            if not click.confirm("\nDo you approve executing these tasks and validation checks?"):
                click.echo("Sprint start cancelled (approval denied).")
                return
            sprint.approval_state = "approved"
            runner.save_sprint(sprint)

        click.echo("Starting sprint execution loop...")
        res_sprint, msg = runner.start_sprint(auto_approve=True)
        if res_sprint:
            click.echo(f"Sprint Status: {res_sprint.status.upper()}")
            click.echo(f"Result: {res_sprint.execution_result or 'Running'}")
        click.echo(msg)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("status")
def sprint_status() -> None:
    """Show the status of the current active sprint."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint = runner.load_sprint()
        if not sprint:
            click.echo("No active sprint found.")
            return
        click.echo(f"Sprint Project: {sprint.project_name}")
        click.echo(f"Sprint Status : {sprint.status.upper()}")
        click.echo(f"Task ID       : {sprint.task_id}")
        click.echo(f"Milestone ID  : {sprint.milestone_id}")
        click.echo(f"Approval State: {sprint.approval_state.upper()}")
        click.echo(f"Current Step  : {sprint.current_step_idx}")
        click.echo(f"Retries Left  : {sprint.retries_left}")
        if sprint.execution_result:
            click.echo(f"Last Result   : {sprint.execution_result}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("pause")
def sprint_pause() -> None:
    """Pause the currently running sprint."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint, msg = runner.pause_sprint()
        if sprint:
            click.echo(f"Sprint Status: {sprint.status.upper()}")
        click.echo(msg)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("resume")
def sprint_resume() -> None:
    """Resume the currently paused sprint."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint, msg = runner.resume_sprint()
        if sprint:
            click.echo(f"Sprint Status: {sprint.status.upper()}")
        click.echo(msg)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("cancel")
def sprint_cancel() -> None:
    """Cancel the active sprint and roll back changes."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint, msg = runner.cancel_sprint()
        if sprint:
            click.echo(f"Sprint Status: {sprint.status.upper()}")
        click.echo(msg)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("validate")
def sprint_validate() -> None:
    """Validate sprint tasks and run check commands."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint = runner.load_sprint()
        if not sprint:
            click.echo("No active sprint to validate.")
            return

        click.echo(f"Running focused validation for task {sprint.task_id}...")
        failures = []
        for cmd_str in sprint.validation_commands:
            args = runner._parse_validation_command(cmd_str)
            if not args:
                continue
            from grandpa.agent.execution.command_catalog import (
                DiagnosticCommand,
                run_catalog_command,
            )
            cmd = DiagnosticCommand(args=args, cwd=str(runner.project_path))
            res = run_catalog_command(cmd)
            click.echo(f"  Command '{cmd_str}' -> Exit Code: {res.exit_code}")
            if res.exit_code != 0:
                failures.append(cmd_str)

        if failures:
            click.echo(f"[FAIL] Validation failed for: {failures}")
            raise click.ClickException("Sprint validation failed.")
        else:
            click.echo("[SUCCESS] All validation checks passed successfully.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("report")
def sprint_report() -> None:
    """Produce the final report summary of the active/completed sprint."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        sprint = runner.load_sprint()
        if not sprint:
            click.echo("No active sprint report found.")
            return
        click.echo("========================================")
        click.echo("GRANDPA SPRINT RUNNER V1 REPORT")
        click.echo("========================================")
        click.echo(f"Project Name      : {sprint.project_name}")
        click.echo(f"Sprint Task ID    : {sprint.task_id}")
        click.echo(f"Milestone ID      : {sprint.milestone_id}")
        click.echo(f"Sprint Status     : {sprint.status.upper()}")
        click.echo(f"Approval Status   : {sprint.approval_state.upper()}")
        click.echo(f"Risk Level        : {sprint.risk_level.upper()}")
        click.echo(f"Validation Target : {sprint.validation_commands}")
        click.echo(f"Checkpoint ID     : {sprint.checkpoint_id or 'None'}")
        click.echo(f"Execution Outcome : {sprint.execution_result or 'Pending'}")
        click.echo("========================================")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sprint_group.command("checkpoint")
@click.option("--save", "save_id", default=None, help="Save active state snapshot with ID.")
@click.option("--restore", "restore_id", default=None, help="Restore state snapshot with ID.")
def sprint_checkpoint(save_id: str | None, restore_id: str | None) -> None:
    """Manage sprint checkpoints manually."""
    try:
        path = _get_project_path()
        runner = SprintRunner(path)
        if save_id:
            runner.tracker.checkpoint_manager.save_checkpoint(save_id)
            click.echo(f"Checkpoint '{save_id}' saved successfully.")
        elif restore_id:
            success, msg = runner.tracker.checkpoint_manager.restore_checkpoint(restore_id)
            if success:
                click.echo(f"Checkpoint '{restore_id}' restored successfully.")
            else:
                click.echo(f"Failed to restore checkpoint: {msg}")
        else:
            checkpoints = runner.tracker.checkpoint_manager.list_checkpoints()
            if not checkpoints:
                click.echo("No checkpoints found.")
            else:
                click.echo("Available Checkpoints:")
                for chk in checkpoints:
                    click.echo(f"  - {chk}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
