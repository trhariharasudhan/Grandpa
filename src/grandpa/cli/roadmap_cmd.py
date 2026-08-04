"""CLI group for Self-Planning Engine V1."""

from __future__ import annotations

import time
from pathlib import Path

import click

from grandpa.agent.development.registry import MultiProjectRegistry
from grandpa.agent.development.roadmap_generator import (
    RoadmapGenerator,
    validate_roadmap,
)
from grandpa.agent.development.tracker import ProjectStateTracker


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


@click.group("roadmap")
def roadmap_group() -> None:
    """Grandpa Self-Planning Engine commands."""
    pass


@roadmap_group.command("create")
@click.argument("description")
@click.option(
    "--goal", "-g", "goals", multiple=True, help="Goals associated with the roadmap."
)
@click.option(
    "--merge", is_flag=True, default=False, help="Merge into the existing roadmap."
)
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Replace the current roadmap completely.",
)
def roadmap_create(
    description: str, goals: list[str], merge: bool, replace: bool
) -> None:
    """Create a project roadmap based on description and goals."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        if replace:
            if not click.confirm(
                "Are you sure you want to replace the current roadmap?"
            ):
                click.echo("Operation cancelled.")
                return
            state.roadmap.milestones = {}
            state.roadmap.planned_milestones = []
            state.roadmap.completed_milestones = []
            state.roadmap.blocked_milestones = []
            state.tasks = []

        generator = RoadmapGenerator(state)
        generator.generate_roadmap(description, list(goals))
        tracker.save_state(state)

        click.echo("Created roadmap successfully.")
        is_valid, errors = validate_roadmap(state)
        if not is_valid:
            click.echo(f"Warning: Roadmap validation failed: {errors}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("show")
def roadmap_show() -> None:
    """Show the active project roadmap structure."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        click.echo(f"Project: {state.project_name}")
        click.echo("Milestones:")
        for mid, m in state.roadmap.milestones.items():
            click.echo(
                f"  - ({mid}) {m.title} (Status: {m.status.upper()}, Priority: {m.priority.upper()})"
            )
            click.echo(f"    Description: {m.description}")
            if getattr(m, "rationale", None):
                click.echo(f"    Rationale: {m.rationale}")
            if getattr(m, "acceptance_criteria", None) and m.acceptance_criteria:
                click.echo(f"    Acceptance Criteria: {m.acceptance_criteria}")
            if getattr(m, "validation_strategy", None) and m.validation_strategy:
                click.echo(f"    Validation Strategy: {m.validation_strategy}")
            if m.dependencies:
                click.echo(f"    Dependencies: {m.dependencies}")

        click.echo("\nPlanning History:")
        for hist in state.roadmap.planning_history:
            action = hist.get("action", "")
            if action == "generate_roadmap":
                click.echo(
                    f"  - Generated roadmap: {hist.get('description')} with goals {hist.get('goals')}"
                )
            elif action == "expand_milestone":
                click.echo(
                    f"  - Expanded milestone '{hist.get('milestone_id')}': task '{hist.get('task_id')}' - {hist.get('explanation')}"
                )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("milestones")
def roadmap_milestones() -> None:
    """List all milestones."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        if not state.roadmap.milestones:
            click.echo("No milestones registered.")
            return

        click.echo("Milestones:")
        for mid, m in state.roadmap.milestones.items():
            click.echo(
                f"({mid}) {m.title} - Status: {m.status.upper()} (Priority: {m.priority.upper()})"
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("tasks")
def roadmap_tasks() -> None:
    """List all roadmap tasks and their milestone associations."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        if not state.tasks:
            click.echo("No tasks registered.")
            return

        click.echo("Task Registry Graph:")
        for t in state.tasks:
            milestone_str = f"Milestone: {t.milestone}" if t.milestone else "Global"
            click.echo(
                f"({t.task_id}) {t.title} - Status: {t.status.upper()} (Priority: {t.priority.upper()}, {milestone_str})"
            )
            if getattr(t, "rationale", None):
                click.echo(f"  Rationale: {t.rationale}")
            if getattr(t, "affected_areas", None) and t.affected_areas:
                click.echo(f"  Affected Areas: {t.affected_areas}")
            if getattr(t, "expected_artifacts", None) and t.expected_artifacts:
                click.echo(f"  Expected Artifacts: {t.expected_artifacts}")
            if getattr(t, "acceptance_criteria", None) and t.acceptance_criteria:
                click.echo(f"  Acceptance Criteria: {t.acceptance_criteria}")
            if getattr(t, "validation_commands", None) and t.validation_commands:
                click.echo(f"  Validation Commands: {t.validation_commands}")
            if t.dependencies:
                click.echo(f"  Dependencies: {t.dependencies}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("expand")
@click.argument("milestone_id")
@click.option(
    "--task-id", "-t", required=True, help="Task ID to expand milestone with."
)
@click.option("--title", required=True, help="Task title.")
@click.option(
    "--dep", "-d", "dependencies", multiple=True, help="Dependencies (task IDs)."
)
@click.option("--priority", "-p", default="medium", help="Priority (high/medium/low).")
@click.option("--desc", default="", help="Task description.")
@click.option(
    "--explanation",
    default="Required for milestone implementation.",
    help="Why this task exists.",
)
def roadmap_expand(
    milestone_id: str,
    task_id: str,
    title: str,
    dependencies: list[str],
    priority: str,
    desc: str,
    explanation: str,
) -> None:
    """Expand a milestone with a new task."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        generator = RoadmapGenerator(state)
        tasks_data = [
            {
                "task_id": task_id,
                "title": title,
                "priority": priority,
                "dependencies": list(dependencies),
                "description": desc,
                "explanation": explanation,
                "rationale": explanation,
            }
        ]
        generator.expand_milestone(milestone_id, tasks_data)
        tracker.save_state(state)

        click.echo(
            f"Successfully expanded milestone '{milestone_id}' with task '{task_id}'."
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.group("regenerate")
def roadmap_regenerate() -> None:
    """Regenerate items in the roadmap."""
    pass


@roadmap_regenerate.command("task")
@click.argument("task_id")
def regenerate_task(task_id: str) -> None:
    """Regenerate a specific task in the roadmap."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        target_task = None
        for t in state.tasks:
            if t.task_id == task_id:
                target_task = t
                break

        if not target_task:
            raise KeyError(f"Task '{task_id}' not found.")

        target_task.completion_state = False
        target_task.status = "pending"
        target_task.rationale = "Regenerated task to re-run validation."
        tracker.save_state(state)

        click.echo(f"Task '{task_id}' regenerated successfully.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("archive")
def roadmap_archive() -> None:
    """Archive the current roadmap and clear active items."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        if not click.confirm("Are you sure you want to archive the current roadmap?"):
            click.echo("Operation cancelled.")
            return

        state.roadmap.planning_history.append(
            {
                "action": "archive_roadmap",
                "timestamp": time.time(),
                "archived_milestones": {
                    mid: m.to_dict() for mid, m in state.roadmap.milestones.items()
                },
                "archived_tasks": [t.to_dict() for t in state.tasks],
            }
        )

        state.roadmap.milestones = {}
        state.roadmap.planned_milestones = []
        state.roadmap.completed_milestones = []
        state.roadmap.blocked_milestones = []
        state.tasks = []
        tracker.save_state(state)

        click.echo("Current roadmap archived successfully.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("graph")
def roadmap_graph() -> None:
    """Output Mermaid dependency graph representation."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        lines = ["graph TD"]

        # Milestones Subgraph
        lines.append("  subgraph Milestones")
        for mid, m in state.roadmap.milestones.items():
            lines.append(f'    {mid}["{m.title}"]')
            for dep in m.dependencies:
                lines.append(f"    {dep} --> {mid}")
        lines.append("  end")

        # Tasks Subgraph
        lines.append("  subgraph Tasks")
        for t in state.tasks:
            lines.append(f'    {t.task_id}["{t.title}"]')
            for dep in t.dependencies:
                lines.append(f"    {dep} --> {t.task_id}")
        lines.append("  end")

        click.echo("\n".join(lines))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("validate")
def roadmap_validate() -> None:
    """Validate roadmap cycles, orphans, and invalid references."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        is_valid, errors = validate_roadmap(state)
        if is_valid:
            click.echo(
                "Roadmap is valid. No circular dependencies, orphan tasks, or invalid references detected."
            )
        else:
            click.echo("Roadmap validation failed with errors:")
            for err in errors:
                click.echo(f"  - {err}")
            raise click.ClickException("Roadmap has validation errors.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@roadmap_group.command("migrate")
@click.option(
    "--preview",
    is_flag=True,
    default=False,
    help="Preview the migration changes without modifying state.",
)
@click.option(
    "--apply",
    "apply_flag",
    is_flag=True,
    default=False,
    help="Apply the migration updates.",
)
def roadmap_migrate(preview: bool, apply_flag: bool) -> None:
    """Migrate legacy generic roadmap template items to goal-aware representations."""
    try:
        path = _get_project_path()
        tracker = ProjectStateTracker(path)
        state = tracker.load_state()

        from grandpa.agent.development.roadmap_generator import (
            is_legacy_roadmap,
            migrate_legacy_roadmap,
        )

        if not is_legacy_roadmap(state):
            click.echo(
                "Active project roadmap is already up-to-date. No migration required."
            )
            return

        import copy

        simulated_state = copy.deepcopy(state)
        _, changes = migrate_legacy_roadmap(simulated_state)

        if preview or (not apply_flag):
            click.echo("Legacy Roadmap Migration Preview:")
            click.echo("The following generic placeholders will be archived/removed:")
            for m in changes["archived_milestones"]:
                click.echo(f"  - Milestone: {m}")
            for t in changes["archived_tasks"]:
                click.echo(f"  - Task: {t}")
            click.echo("\nThe following goal-aware milestones/tasks will be added:")
            for m in changes["added_milestones"]:
                click.echo(f"  + Milestone: {m}")
            for t in changes["added_tasks"]:
                click.echo(f"  + Task: {t}")

            if not apply_flag:
                click.echo(
                    "\nRun 'grandpa roadmap migrate --apply' to perform the migration."
                )
            return

        if apply_flag:
            if not click.confirm(
                "Are you sure you want to apply the roadmap migration?"
            ):
                click.echo("Operation cancelled.")
                return

            migrate_legacy_roadmap(state)
            tracker.save_state(state)
            click.echo("Roadmap migration completed successfully.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
