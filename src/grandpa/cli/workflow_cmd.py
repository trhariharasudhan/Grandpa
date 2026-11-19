"""``grandpa workflow``: list, check and run YAML workflows.

A workflow is a ``<name>.yaml`` file in the workflow folder (``~/.grandpa/
workflows`` unless ``GRANDPA_WORKFLOWS_DIR`` says otherwise) whose steps are
catalogued actions. ``run`` is a dry run unless ``--yes`` is given, and even
with ``--yes`` every step whose action needs confirmation still asks on the
terminal -- ``--yes`` means "really run it", never "approve everything".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from grandpa.cli._tty import confirm_destructive


def _parse_vars(values: tuple[str, ...]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise click.BadParameter(f"{item!r} is not NAME=VALUE", param_hint="--var")
        text = value.strip()
        number: Any = text
        try:
            number = int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                number = text
        parsed[key.strip()] = number
    return parsed


def _load(name: str, directory: Path | None):
    from grandpa.workflow.loader import (
        WorkflowFileError,
        find_workflow,
        load_yaml_workflow,
    )

    try:
        path = find_workflow(name, directory)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        return load_yaml_workflow(path)
    except WorkflowFileError as exc:
        click.echo(f"{path} has problems:", err=True)
        for problem in exc.problems:
            click.echo(f"  - {problem}", err=True)
        raise SystemExit(1) from exc


_dir_option = click.option(
    "--dir",
    "directory",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Workflow folder (default: ~/.grandpa/workflows).",
)


@click.group()
def workflow() -> None:
    """Routines made of Grandpa's actions, written as YAML files."""


@workflow.command("list")
@_dir_option
def list_cmd(directory: Path | None) -> None:
    """Show the workflows in the workflow folder."""
    from grandpa.workflow.loader import (
        WorkflowFileError,
        list_workflow_files,
        load_yaml_workflow,
        workflow_dir,
    )

    folder = directory or workflow_dir()
    files = list_workflow_files(folder)
    if not files:
        click.echo(f"No workflows yet. Put <name>.yaml files in {folder}")
        return
    click.echo(f"Workflows in {folder}:")
    for path in files:
        try:
            graph = load_yaml_workflow(path)
        except WorkflowFileError as exc:
            click.echo(f"  {path.stem:<24} INVALID ({len(exc.problems)} problem(s))")
            continue
        about = f" - {graph.description}" if graph.description else ""
        click.echo(f"  {graph.name:<24} {len(graph.nodes)} step(s){about}")


@workflow.command("validate")
@click.argument("name")
@_dir_option
def validate_cmd(name: str, directory: Path | None) -> None:
    """Check a workflow file against the action catalogue."""
    from grandpa.action_layer.catalogue import get as catalogue_get

    graph = _load(name, directory)
    click.echo(f"{graph.name}: OK, {len(graph.nodes)} step(s)")
    for node in graph.nodes:
        spec = catalogue_get(node.action)
        ask = ", asks first" if spec.requires_confirmation else ""
        click.echo(f"  {node.id}: {node.action} [{spec.risk.value}{ask}]")


def _terminal_confirm(action: str, parameters: Any, risk: Any) -> bool:
    shown = ", ".join(f"{k}={v!r}" for k, v in dict(parameters).items())
    answer = confirm_destructive(f"Run {action}({shown}) [{risk}]? [y/N]")
    if answer is None:
        click.echo("  Nobody can answer here, so this step was not run.")
    return answer is True


@workflow.command("run")
@click.argument("name")
@click.option(
    "--yes",
    "execute",
    is_flag=True,
    help="Really run the steps. Without it, nothing is done (dry run).",
)
@click.option("--var", "variables", multiple=True, help="Set a variable: NAME=VALUE.")
@_dir_option
def run_cmd(
    name: str, execute: bool, variables: tuple[str, ...], directory: Path | None
) -> None:
    """Run a workflow (dry run unless --yes)."""
    from grandpa.workflow.engine import WorkflowEngine

    graph = _load(name, directory)
    extra = _parse_vars(variables)
    unknown = sorted(set(extra) - set(graph.variables))
    if unknown:
        raise click.BadParameter(
            f"{', '.join(unknown)} not in this workflow's vars "
            f"({', '.join(sorted(graph.variables)) or 'none'})",
            param_hint="--var",
        )

    if not execute:
        click.echo(f"Dry run of {graph.name} (nothing is done; add --yes to run):")
    result = WorkflowEngine().run(
        graph,
        variables=extra,
        dry_run=not execute,
        confirm_callback=_terminal_confirm if execute else None,
    )
    for step in result.steps:
        meta = step.metadata
        if meta.get("skipped"):
            mark = "skip"
        elif step.success:
            mark = "plan" if meta.get("dry_run") else "ok"
        else:
            mark = "FAIL"
        tries = meta.get("attempts", 1)
        extra_note = f" (after {tries} tries)" if tries > 1 else ""
        click.echo(f"  [{mark}] {step.node_id}: {step.output}{extra_note}")
        if meta.get("when", "").startswith("decided at run time"):
            click.echo(f"         only if {meta['when'].split(': ', 1)[1]}")
    if not result.success:
        click.echo(f"{graph.name} stopped: a step failed.", err=True)
        raise SystemExit(1)
    click.echo(f"{graph.name}: {'done' if execute else 'dry run finished'}.")
