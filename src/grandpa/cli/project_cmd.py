"""CLI group for Multi-Project Memory V1 and Autonomous Development Workflow V1."""

from __future__ import annotations

from pathlib import Path

import click

from grandpa.agent.development.engine import ContinuationEngine
from grandpa.agent.development.registry import MultiProjectRegistry
from grandpa.agent.development.tracker import ProjectStateTracker


def _get_project_path() -> str:
    # Try registry first
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


@click.group("project")
def project_group() -> None:
    """Manage multiple software projects and track milestones/tasks."""
    pass


@project_group.command("create")
@click.argument("name")
@click.argument("path", type=click.Path())
@click.option("--desc", default="", help="Description of the project.")
def create_project_cmd(name: str, path: str, desc: str) -> None:
    """Create a new project folder and register it."""
    try:
        registry = MultiProjectRegistry()
        pinfo = registry.create_project(name, path, desc)
        click.echo(
            f"Created and registered project '{pinfo.project_name}' [{pinfo.project_id}] at {pinfo.project_path}."
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("register")
@click.argument("name")
@click.argument("path", type=click.Path())
@click.option("--desc", default="", help="Description of the project.")
def register_project_cmd(name: str, path: str, desc: str) -> None:
    """Register an existing project path."""
    try:
        registry = MultiProjectRegistry()
        pinfo = registry.register_project(name, path, desc)
        click.echo(
            f"Registered project '{pinfo.project_name}' [{pinfo.project_id}] at {pinfo.project_path}."
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("list")
def list_cmd() -> None:
    """List all registered projects."""
    try:
        registry = MultiProjectRegistry()
        projects = registry.list_projects()
        if not projects:
            click.echo("No projects registered.")
            return

        active_id = registry.active_project_id
        click.echo("Registered Projects:")
        for p in projects:
            active_marker = "*" if p.project_id == active_id else " "
            click.echo(
                f"{active_marker} {p.project_name} [{p.project_id}] - {p.project_path} ({p.repository_health})"
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("switch")
@click.argument("identifier")
def switch_cmd(identifier: str) -> None:
    """Switch active project context using name or ID."""
    try:
        registry = MultiProjectRegistry()
        pinfo = registry.switch_project(identifier)
        click.echo(
            f"Switched active project context to '{pinfo.project_name}' [{pinfo.project_id}]."
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("current")
def current_cmd() -> None:
    """Show the currently active project context name."""
    try:
        registry = MultiProjectRegistry()
        active = registry.get_active_project()
        if active:
            click.echo(f"Active Project: {active.project_name} [{active.project_id}]")
        else:
            click.echo("No active project set.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("context")
def context_cmd() -> None:
    """Show detailed status and context for the active project."""
    try:
        registry = MultiProjectRegistry()
        active = registry.get_active_project()
        if not active:
            click.echo("No active project context found.")
            return

        path = active.project_path
        tracker = ProjectStateTracker(path, project_name=active.project_name)
        state = tracker.load_state()

        engine = ContinuationEngine(path, project_name=active.project_name)
        branch, health = engine.inspect_repository()
        state.active_branch = branch
        state.repository_health = health
        tracker.save_state(state)

        # Sync active status back to registry representation
        active.active_branch = branch
        active.repository_health = health
        registry.save()

        click.echo(f"Active Project    : {state.project_name} [{active.project_id}]")
        click.echo(f"Description       : {active.description or 'None'}")
        click.echo(f"Project Path      : {state.project_path}")
        click.echo(f"Active Branch     : {state.active_branch}")
        click.echo(f"Repository Health : {state.repository_health.upper()}")
        click.echo(f"Current Milestone : {state.current_milestone or 'None'}")
        click.echo(f"Next Milestone    : {state.next_milestone or 'None'}")

        next_task = engine.identify_next_task(state)
        next_task_str = (
            f"[{next_task.task_id}] {next_task.title}" if next_task else "None"
        )
        click.echo(f"Next Task         : {next_task_str}")
        click.echo(
            f"Completed Tasks   : {len([t for t in state.tasks if t.completion_state])}"
        )
        click.echo(
            f"Pending Tasks     : {len([t for t in state.tasks if not t.completion_state])}"
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("plan")
def plan_cmd() -> None:
    """Generate an engineering plan for the next milestone."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        engine = ContinuationEngine(path, project_name=state.project_name)
        branch, health = engine.inspect_repository()
        state.active_branch = branch
        state.repository_health = health
        tracker.save_state(state)

        from grandpa.agent.development.planner import EngineeringPlanner

        planner = EngineeringPlanner(state)
        milestone, task, reason = planner.analyze_milestone_and_task()

        click.echo(f"Recommended Milestone: {milestone or 'None'}")
        click.echo(f"Reasoning: {reason}")
        if task:
            click.echo(f"Next Task  : [{task.task_id}] {task.title}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("next-task")
def next_task_cmd() -> None:
    """Identify and show the next task to work on."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        engine = ContinuationEngine(path, project_name=state.project_name)
        branch, health = engine.inspect_repository()
        state.active_branch = branch
        state.repository_health = health
        tracker.save_state(state)

        from grandpa.agent.development.planner import EngineeringPlanner
        from grandpa.agent.development.roadmap_generator import is_legacy_roadmap

        if is_legacy_roadmap(state):
            click.echo(
                "Legacy roadmap detected. Run `grandpa roadmap migrate --preview`."
            )
            return

        planner = EngineeringPlanner(state)
        _, task, reason = planner.analyze_milestone_and_task()
        if task:
            click.echo(f"Next Task: ({task.task_id}) {task.title}")
            click.echo(f"Reason   : {reason}")
        else:
            click.echo("No tasks currently available.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("work-package")
def work_package_cmd() -> None:
    """Generate a structured engineering work package."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        engine = ContinuationEngine(path, project_name=state.project_name)
        branch, health = engine.inspect_repository()
        state.active_branch = branch
        state.repository_health = health
        tracker.save_state(state)

        from grandpa.agent.development.planner import EngineeringPlanner

        planner = EngineeringPlanner(state)
        wp = planner.generate_work_package()
        click.echo(planner.format_work_package_text(wp))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("blockers")
def blockers_cmd() -> None:
    """List all active blockers for milestones or tasks."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        blocked_milestones = state.roadmap.blocked_milestones
        blocked_tasks = [t for t in state.tasks if t.status == "blocked"]

        click.echo("Blocked Milestones:")
        if blocked_milestones:
            for m in blocked_milestones:
                click.echo(f"  - {m}")
        else:
            click.echo("  (None)")

        click.echo("Blocked Tasks:")
        if blocked_tasks:
            for t in blocked_tasks:
                click.echo(f"  - [{t.task_id}] {t.title}")
        else:
            click.echo("  (None)")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@project_group.command("status")
def status_cmd() -> None:
    """Show the current project state tracker status."""
    path = _get_project_path()
    tracker = ProjectStateTracker(path)
    state = tracker.load_state()

    engine = ContinuationEngine(path, project_name=state.project_name)
    branch, health = engine.inspect_repository()
    state.active_branch = branch
    state.repository_health = health
    tracker.save_state(state)

    click.echo(f"Project Name      : {state.project_name}")
    click.echo(f"Project Path      : {state.project_path}")
    click.echo(f"Active Branch     : {state.active_branch}")
    click.echo(f"Repository Health : {state.repository_health.upper()}")
    click.echo(f"Current Milestone : {state.current_milestone or 'None'}")
    click.echo(f"Next Milestone    : {state.next_milestone or 'None'}")
    click.echo(
        f"Completed Tasks   : {len([t for t in state.tasks if t.completion_state])}"
    )
    click.echo(
        f"Pending Tasks     : {len([t for t in state.tasks if not t.completion_state])}"
    )


@project_group.command("roadmap")
def roadmap_cmd() -> None:
    """Show the project roadmap and milestones."""
    path = _get_project_path()
    tracker = ProjectStateTracker(path)
    state = tracker.load_state()
    roadmap = state.roadmap

    click.echo("Completed Milestones:")
    if roadmap.completed_milestones:
        for m in roadmap.completed_milestones:
            click.echo(f"  - {m}")
    else:
        click.echo("  (None)")

    click.echo(f"Current Milestone: {roadmap.current_milestone or 'None'}")

    click.echo("Planned Milestones:")
    if roadmap.planned_milestones:
        for m in roadmap.planned_milestones:
            click.echo(f"  - {m}")
    else:
        click.echo("  (None)")

    click.echo("Blocked Milestones:")
    if roadmap.blocked_milestones:
        for m in roadmap.blocked_milestones:
            click.echo(f"  - {m}")
    else:
        click.echo("  (None)")


@project_group.command("next")
def next_cmd() -> None:
    """Identify the next task to work on."""
    path = _get_project_path()
    engine = ContinuationEngine(path)
    state = engine.tracker.load_state()

    branch, health = engine.inspect_repository()
    state.active_branch = branch
    state.repository_health = health
    engine.tracker.save_state(state)

    from grandpa.agent.development.roadmap_generator import is_legacy_roadmap

    if is_legacy_roadmap(state):
        click.echo("Legacy roadmap detected. Run `grandpa roadmap migrate --preview`.")
        return

    next_task = engine.identify_next_task(state)
    if next_task:
        click.echo(f"Next Task: [{next_task.task_id}] {next_task.title}")
        click.echo(f"Priority : {next_task.priority.upper()}")
        click.echo(f"Depends  : {next_task.dependencies or 'None'}")
    else:
        click.echo("No pending tasks available.")


@project_group.group("checkpoint")
def checkpoint_group() -> None:
    """Save, load, and validate project checkpoints."""
    pass


@checkpoint_group.command("save")
@click.option(
    "--id", "checkpoint_id", default=None, help="Custom checkpoint identifier."
)
def checkpoint_save(checkpoint_id: str | None) -> None:
    """Save a snapshot checkpoint of the current project state."""
    path = _get_project_path()
    tracker = ProjectStateTracker(path)
    state = tracker.load_state()

    engine = ContinuationEngine(path, project_name=state.project_name)
    branch, health = engine.inspect_repository()
    state.active_branch = branch
    state.repository_health = health
    tracker.save_state(state)

    checkpoint = tracker.checkpoint_manager.save_checkpoint(state, checkpoint_id)
    click.echo(f"Saved checkpoint '{checkpoint.checkpoint_id}' successfully.")


@checkpoint_group.command("load")
@click.argument("checkpoint_id")
def checkpoint_load(checkpoint_id: str) -> None:
    """Load and restore a project checkpoint."""
    path = _get_project_path()
    tracker = ProjectStateTracker(path)

    engine = ContinuationEngine(path)
    branch, health = engine.inspect_repository()

    checkpoint = tracker.checkpoint_manager.load_checkpoint(checkpoint_id)
    is_valid = tracker.checkpoint_manager.validate_checkpoint(
        checkpoint, branch, health
    )
    if not is_valid:
        click.echo(
            f"Warning: Checkpoint branch ({checkpoint.active_branch}) or health ({checkpoint.repository_health}) "
            f"mismatches current workspace branch ({branch}) or health ({health})."
        )

    tracker.save_state(checkpoint.state)
    click.echo(f"Restored project state from checkpoint '{checkpoint_id}'.")


@project_group.command("resume")
def resume_cmd() -> None:
    """Resume work on the current project."""
    path = _get_project_path()
    engine = ContinuationEngine(path)
    result = engine.continue_project()
    click.echo(f"Resuming project '{result['project_name']}'.")
    click.echo(result["execution_plan"])
