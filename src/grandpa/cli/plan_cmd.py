"""CLI for safe Executive Planner previews, execution, and inspection."""

from __future__ import annotations

from pathlib import Path

import click

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.planner.executive import ExecutivePlanner
from grandpa.planner.formatter import (
    format_debug_trace,
    format_dump,
    format_graph,
    format_plan,
    format_plan_result,
    format_status,
    format_trace,
)


@click.group()
@click.option("--session", "session_id", default="cli", show_default=True)
@click.pass_context
def plan(ctx: click.Context, session_id: str) -> None:
    """Create and run bounded, verified multi-step plans."""

    ctx.ensure_object(dict)
    ctx.obj["planner"] = ExecutivePlanner(session_id=session_id)


@plan.command("create")
@click.argument("goal")
@click.option("--local-model", is_flag=True, help="Allow bounded local Ollama decomposition.")
@click.pass_context
def create_plan(ctx: click.Context, goal: str, local_model: bool) -> None:
    """Create and validate a plan without executing it."""

    result = _planner(ctx).preview(goal, allow_local_model=local_model)
    click.echo(format_plan_result(result))
    if result.status != "ready":
        raise click.exceptions.Exit(1)


@plan.command("preview")
@click.argument("goal")
@click.option("--local-model", is_flag=True, help="Allow bounded local Ollama decomposition.")
@click.pass_context
def preview(ctx: click.Context, goal: str, local_model: bool) -> None:
    """Preview and validate a plan without executing it."""

    result = _planner(ctx).preview(goal, allow_local_model=local_model)
    click.echo(format_plan_result(result))
    if result.status != "ready":
        raise click.exceptions.Exit(1)


@plan.command("execute")
@click.argument("goal")
@click.option("--dry-run", is_flag=True, help="Evaluate without performing actions.")
@click.option("--local-model", is_flag=True, help="Allow bounded local Ollama decomposition.")
@click.option("--debug", is_flag=True, help="Show sanitized planner diagnostics.")
@click.pass_context
def execute(
    ctx: click.Context,
    goal: str,
    dry_run: bool,
    local_model: bool,
    debug: bool,
) -> None:
    """Create, validate, and execute a plan."""

    planner = _planner(ctx)
    try:
        result = planner.execute(
            goal,
            dry_run=dry_run,
            allow_local_model=local_model,
        )
        result = _resolve_interactive_pauses(planner, result, dry_run=dry_run)
    except (KeyboardInterrupt, EOFError):
        click.echo("The task was cancelled safely.")
        raise click.exceptions.Exit(1) from None
    except Exception as exc:
        if debug:
            raise
        click.echo(f"The planner stopped safely ({exc.__class__.__name__}).")
        raise click.exceptions.Exit(1) from None
    click.echo(result.message)
    if debug:
        click.echo(format_debug_trace(result.plan))
    if result.failure is not None or result.status not in {
        "completed",
        "partially_completed",
        "confirmation_required",
        "clarification_required",
    }:
        raise click.exceptions.Exit(1)


@plan.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current plan progress."""

    click.echo(format_status(_planner(ctx).current()))


@plan.command("show")
@click.pass_context
def show(ctx: click.Context) -> None:
    """Show the current sanitized plan."""

    current = _planner(ctx).current()
    click.echo(format_plan(current) if current is not None else "No plan exists for this session.")


@plan.command("pause")
@click.pass_context
def pause(ctx: click.Context) -> None:
    click.echo(_planner(ctx).pause().message)


@plan.command("resume")
@click.option("--yes", is_flag=True, help="Confirm the current pending planner step.")
@click.pass_context
def resume(ctx: click.Context, yes: bool) -> None:
    click.echo(_planner(ctx).resume(confirmed=yes).message)


@plan.command("clarify")
@click.argument("response")
@click.pass_context
def clarify(ctx: click.Context, response: str) -> None:
    """Answer the current plan's session-owned clarification."""

    click.echo(_planner(ctx).clarify(response).message)


@plan.command("cancel")
@click.pass_context
def cancel(ctx: click.Context) -> None:
    click.echo(_planner(ctx).cancel().message)


@plan.command("retry")
@click.pass_context
def retry(ctx: click.Context) -> None:
    click.echo(_planner(ctx).retry().message)


@plan.command("list")
@click.pass_context
def list_plans(ctx: click.Context) -> None:
    plans = _planner(ctx).store.list()
    if not plans:
        click.echo("No saved plans found.")
        return
    for item in plans:
        click.echo(f"{item.plan_id}  {item.session_id}  {item.status.value}  {item.original_goal}")


@plan.command("dump")
@click.option("--output", type=click.Path(path_type=Path), default=None)
@click.pass_context
def dump(ctx: click.Context, output: Path | None) -> None:
    current = _planner(ctx).current()
    if current is None:
        click.echo("No plan exists for this session.")
        return
    root = DEFAULT_CONFIG_DIR / "plans" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = output or root / f"{current.plan_id}.json"
    path = path.expanduser().resolve()
    if root.resolve() not in path.parents:
        raise click.ClickException("Plan dumps must stay inside Grandpa's plan export directory.")
    path.write_text(format_dump(current), encoding="utf-8")
    click.echo(f"Plan saved: {path}")


@plan.command("trace")
@click.pass_context
def trace(ctx: click.Context) -> None:
    click.echo(format_trace(_planner(ctx).current()))


@plan.command("graph")
@click.option("--mermaid", is_flag=True)
@click.pass_context
def graph(ctx: click.Context, mermaid: bool) -> None:
    click.echo(format_graph(_planner(ctx).current(), mermaid=mermaid))


def _planner(ctx: click.Context) -> ExecutivePlanner:
    return ctx.obj["planner"]


def _resolve_interactive_pauses(
    planner: ExecutivePlanner,
    result,
    *,
    dry_run: bool,
):
    if dry_run:
        return result
    while result.status in {"confirmation_required", "clarification_required"}:
        if result.status == "confirmation_required":
            if not click.confirm(result.message, default=False):
                return planner.cancel()
            result = planner.resume(confirmed=True)
        else:
            response = click.prompt(result.message, type=str)
            result = planner.clarify(response)
    return result


__all__ = ["plan"]
