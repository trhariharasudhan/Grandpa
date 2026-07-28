"""CLI commands for locally installed skills."""

from __future__ import annotations

from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.table import Table

from grandpa.core.events import EventBus
from grandpa.skills.manager import SkillManager


def _get_skill_paths() -> List[Path]:
    """Return trusted workspace and user-local skill roots."""
    paths: List[Path] = []
    workspace = Path("./skills")
    if workspace.exists():
        paths.append(workspace)
    paths.append(Path("~/.grandpa/skills/").expanduser())
    return paths


def _get_manager() -> SkillManager:
    manager = SkillManager(bus=EventBus())
    manager.discover(paths=_get_skill_paths())
    return manager


@click.group()
def skill() -> None:
    """Manage available local reusable skills."""


@skill.command("list")
def list_skills() -> None:
    """List locally installed skills."""
    console = Console()
    manager = _get_manager()
    names = manager.skill_names()
    if not names:
        console.print("[dim]No skills installed.[/dim]")
        return

    table = Table(title="Installed Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description", max_width=50)
    table.add_column("Version")
    table.add_column("Tags")
    for name in sorted(names):
        manifest = manager.resolve(name)
        description = manifest.description
        if len(description) > 50:
            description = f"{description[:50]}..."
        table.add_row(
            name,
            description,
            manifest.version,
            ", ".join(manifest.tags) if manifest.tags else "",
        )
    console.print(table)


@skill.command("info")
@click.argument("skill_name")
def info(skill_name: str) -> None:
    """Show detailed information about a local skill."""
    console = Console()
    manager = _get_manager()
    try:
        manifest = manager.resolve(skill_name)
    except KeyError:
        console.print(f"[red]Skill '{skill_name}' not found.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]{manifest.name}[/bold] v{manifest.version}")
    if manifest.author:
        console.print(f"Author: {manifest.author}")
    if manifest.description:
        console.print(f"Description: {manifest.description}")
    if manifest.tags:
        console.print(f"Tags: {', '.join(manifest.tags)}")
    if manifest.required_capabilities:
        console.print(f"Capabilities: {', '.join(manifest.required_capabilities)}")
    if manifest.depends:
        console.print(f"Dependencies: {', '.join(manifest.depends)}")
    if manifest.steps:
        console.print(f"Steps: {len(manifest.steps)}")
    if manifest.markdown_content:
        console.print("Has instructions: yes")
    console.print(f"User invocable: {manifest.user_invocable}")
    console.print(
        "Model invocation: "
        f"{'disabled' if manifest.disable_model_invocation else 'enabled'}"
    )


@skill.command("run")
@click.argument("skill_name")
@click.option("--arg", "-a", multiple=True, help="Arguments as key=value pairs.")
def run(skill_name: str, arg: tuple[str, ...]) -> None:
    """Execute a locally installed skill."""
    console = Console()
    manager = _get_manager()
    context: dict[str, str] = {}
    for item in arg:
        if "=" in item:
            key, value = item.split("=", 1)
            context[key.strip()] = value.strip()

    try:
        result = manager.execute(skill_name, context)
    except KeyError:
        console.print(f"[red]Skill '{skill_name}' not found.[/red]")
        raise SystemExit(1)

    if result.success:
        console.print("[green]Success[/green]")
    else:
        console.print("[red]Failed[/red]")
    if result.step_results:
        console.print(result.step_results[-1].content)


@skill.command("remove")
@click.argument("skill_name")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
def remove(skill_name: str, yes: bool) -> None:
    """Remove a locally installed skill by name."""
    console = Console()
    manager = SkillManager(bus=EventBus())
    roots = _get_skill_paths()
    paths = manager.find_installed_paths(skill_name, roots=roots)
    if not paths:
        console.print(f"[red]No installed skill named '{skill_name}' found.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Will remove {len(paths)} location(s):[/bold]")
    for path in paths:
        console.print(f"  - {path}")
    if not yes and not click.confirm("Proceed?", default=False):
        console.print("[dim]Aborted.[/dim]")
        return

    try:
        removed = manager.remove(skill_name, roots=roots)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    for path in removed:
        console.print(f"[green]Removed:[/green] {path}")


__all__ = ["skill"]
