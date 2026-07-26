"""CLI for registered projects and approved developer workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from grandpa.projects.commands import _format_info
from grandpa.projects.errors import ProjectError
from grandpa.projects.service import ProjectService


@click.group("projects")
def projects() -> None:
    """Launch projects and run registered developer workflows."""


def _service() -> ProjectService:
    return ProjectService()


def _guard(operation) -> None:
    try:
        operation()
    except ProjectError as exc:
        raise click.ClickException(str(exc)) from exc


@projects.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
def list_cmd(as_json: bool) -> None:
    def run() -> None:
        records = _service().projects()
        if as_json:
            click.echo(json.dumps([item.to_dict() for item in records], indent=2))
            return
        if not records:
            click.echo("No projects are registered yet.")
            return
        click.echo("Registered projects:")
        for project in records:
            click.echo(f"- {project.name} [{project.id}] - {project.root_path}")

    _guard(run)


@projects.command("register")
@click.argument("path", required=False, type=click.Path(path_type=Path))
@click.option("--name", default=None)
@click.option("--editor", default="visual studio code", show_default=True)
def register(path: Path | None, name: str | None, editor: str) -> None:
    chosen = path or Path(
        click.prompt("Project folder", type=click.Path(path_type=Path))
    )

    def run() -> None:
        project = _service().register(str(chosen), name=name, editor=editor)
        click.echo(f"Registered {project.name} [{project.id}] at {project.root_path}.")
        if project.commands:
            click.echo(f"Suggested workflows: {', '.join(sorted(project.commands))}")

    _guard(run)


@projects.command("discover")
@click.argument("root", type=click.Path(path_type=Path))
@click.option("--max-depth", type=click.IntRange(0, 8), default=3, show_default=True)
def discover(root: Path, max_depth: int) -> None:
    def run() -> None:
        candidates = _service().discover(str(root), max_depth=max_depth)
        if not candidates:
            click.echo("No project candidates found.")
            return
        click.echo("Project candidates:")
        for index, candidate in enumerate(candidates, 1):
            click.echo(f"{index}. {candidate.path} - {candidate.project_type}")
        click.echo("Use: grandpa projects register <path>")

    _guard(run)


@projects.command("show")
@click.argument("project")
def show(project: str) -> None:
    _guard(lambda: click.echo(_format_info(_service().info(project))))


@projects.command("open")
@click.argument("project")
@click.option(
    "--with", "target", default=None, help="Configured editor, vscode, or explorer."
)
def open_cmd(project: str, target: str | None) -> None:
    _guard(lambda: click.echo(_service().open(project, target=target)))


def _lifecycle(action: str, project: str, yes: bool = False) -> None:
    if action in {"stop", "restart"} and not yes:
        click.confirm(f"{action.title()} {project}?", abort=True, default=False)
    _guard(lambda: click.echo(_service().lifecycle(project, action).message))


@projects.command("start")
@click.argument("project")
def start(project: str) -> None:
    _lifecycle("start", project)


@projects.command("stop")
@click.argument("project")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def stop(project: str, yes: bool) -> None:
    _lifecycle("stop", project, yes)


@projects.command("restart")
@click.argument("project")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def restart(project: str, yes: bool) -> None:
    _lifecycle("restart", project, yes)


@projects.command("status")
@click.argument("project")
def status(project: str) -> None:
    _guard(lambda: click.echo(_service().status(project).message))


@projects.command("test")
@click.argument("project")
@click.option("--profile", default=None)
def test(project: str, profile: str | None) -> None:
    def run() -> None:
        service = _service()
        record = service.resolve(project)
        command = (
            record.test_profiles.get(profile.casefold())
            if profile
            else record.commands.get("test")
        )
        if command is not None:
            click.echo(f"Running: {' '.join(command.args)}")
        click.echo(service.run_workflow(project, "test", profile=profile).message)

    _guard(run)


@projects.command("logs")
@click.argument("project")
@click.option("--tail", type=click.IntRange(1, 1000), default=100, show_default=True)
@click.option("--open", "open_file", is_flag=True, help="Open the registered log file.")
def logs(project: str, tail: int, open_file: bool) -> None:
    def run() -> None:
        content, path = _service().logs(project, tail=tail)
        if content:
            click.echo(content)
        if path:
            click.echo(f"Log: {path}")
            if open_file:
                if Path(path).is_file():
                    os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
                else:
                    click.echo("The registered log file does not exist yet.")

    _guard(run)


@projects.command("unregister")
@click.argument("project")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def unregister(project: str, yes: bool) -> None:
    if not yes:
        click.confirm(f"Unregister {project}?", abort=True, default=False)

    def run() -> None:
        removed = _service().unregister(project)
        click.echo(f"Unregistered {removed.name}. Project files were not changed.")

    _guard(run)


project = projects

__all__ = ["project", "projects"]
