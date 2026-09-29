"""CLI commands for locally installed skills."""

from __future__ import annotations

from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.table import Table

from grandpa.cli._tty import require_confirmation
from grandpa.core.events import EventBus
from grandpa.skills.bundled import bundled_dir, refuse_write
from grandpa.skills.manager import (
    SkillManager,
    builtin_tool_executor,
    cli_providers,
)


def _get_skill_paths() -> List[Path]:
    """Workspace, then user-local, then the skills that ship in the package.

    The packaged directory is last because discovery is first-seen-wins: a
    skill of the same name in ~/.grandpa/skills/ shadows the bundled one, which
    is how a user replaces one they cannot edit.

    It was missing entirely, so `skill list` reported "No skills installed" on
    a clean install while eighteen manifests sat inside the package.
    """
    paths: List[Path] = []
    workspace = Path("./skills")
    if workspace.exists():
        paths.append(workspace)
    paths.append(Path("~/.grandpa/skills/").expanduser())
    paths.append(bundled_dir())
    return paths


def _get_manager(*, with_dependencies: bool = False) -> SkillManager:
    """A manager that has both the skills and something to run them with.

    Without the executor the manager had none, and every `skill run` answered
    "Unknown tool: think" -- a third bug sitting behind the two that kept the
    bundled skills invisible, and one that only shows up once they are
    reachable.

    ``interactive`` is True because this is a terminal command: a step naming a
    confirmation-gated tool (shell_exec, code_interpreter) asks, rather than
    being refused for want of anyone to ask.
    """
    manager = SkillManager(bus=EventBus())
    manager.discover(paths=_get_skill_paths())
    unavailable: dict[str, list[str]] = {}
    # Dependencies are resolved only when a skill is about to run. Resolving an
    # inference engine means talking to Ollama, and `skill list` should not wait
    # on that to print a table -- nor should a unit test that builds an executor.
    providers = cli_providers() if with_dependencies else None
    manager.set_tool_executor(
        builtin_tool_executor(
            interactive=True,
            confirm_callback=lambda prompt: click.confirm(prompt, default=False),
            providers=providers,
            unavailable=unavailable,
        )
    )
    manager.unavailable_tools = unavailable
    return manager


def _warn_about_unavailable_tools(manager: SkillManager, skill_name: str) -> None:
    """Say which dependency is missing before the skill runs, not during it.

    ``calendar-prep`` used to reach its second step and answer "No memory backend
    configured." -- true, and useless: nothing said the tool had never been given
    one, or which of the eighteen skills would hit the same wall. What a step
    cannot do is knowable when the tools are built, so it is said then.
    """
    unavailable = getattr(manager, "unavailable_tools", None) or {}
    if not unavailable:
        return
    try:
        manifest = manager.resolve(skill_name)
    except KeyError:
        return
    steps = getattr(manifest, "steps", []) or []
    named = {getattr(step, "tool_name", "") for step in steps}
    affected = {tool: needs for tool, needs in unavailable.items() if tool in named}
    if not affected:
        return
    console = Console()
    for tool, needs in sorted(affected.items()):
        console.print(
            f"[yellow]{tool} is unavailable:[/yellow] no {', '.join(needs)}. "
            f"Steps using it will fail."
        )


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
    manager = _get_manager(with_dependencies=True)
    _warn_about_unavailable_tools(manager, skill_name)
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

    if not result.success:
        # A failed run used to exit 0, so `grandpa skill run ... && next-thing`
        # carried on and any script driving skills read success. The word
        # "Failed" on stdout is not a status a caller can act on. Raised after
        # the step output is printed, so the reason is still shown -- and
        # matching the agent commands, which already exit 1 (agent_cmd.py:46,
        # agent_run_cmd.py:81).
        raise SystemExit(1)


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
    refusal = refuse_write(skill_name)
    if refusal:
        console.print(f"[red]{refusal}[/red]")
        raise SystemExit(1)
    manager = SkillManager(bus=EventBus())
    roots = _get_skill_paths()
    paths = manager.find_installed_paths(skill_name, roots=roots)
    if not paths:
        console.print(f"[red]No installed skill named '{skill_name}' found.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Will remove {len(paths)} location(s):[/bold]")
    for path in paths:
        console.print(f"  - {path}")
    if not require_confirmation("Proceed?", yes=yes, cancelled="Aborted."):
        return

    try:
        removed = manager.remove(skill_name, roots=roots)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    for path in removed:
        console.print(f"[green]Removed:[/green] {path}")


__all__ = ["skill"]
