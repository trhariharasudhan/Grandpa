"""Screen Automation V2 CLI commands."""

from __future__ import annotations

import click

from grandpa.automation import ScreenAutomationService, get_automation_service


@click.group("automation")
def automation() -> None:
    """Safely automate visible Windows controls."""


def _run(
    command: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    window: str | None = None,
    service: ScreenAutomationService | None = None,
) -> None:
    service = service or get_automation_service()
    result = (
        service.handle(command, dry_run=dry_run, target_window=window)
        if window is not None
        else service.handle(command, dry_run=dry_run)
    )
    click.echo(result.message)
    if result.status != "needs_confirmation" or not result.confirmation_token:
        return
    if not yes and not click.confirm("Continue?", default=False):
        click.echo(service.reject(result.confirmation_token).message)
        return
    click.echo(service.confirm(result.confirmation_token).message)


def _execution_options(function):
    function = click.option("--yes", is_flag=True, help="Confirm the planned action.")(function)
    return click.option("--dry-run", is_flag=True, help="Plan without sending input.")(function)


@automation.command("click")
@click.argument("target", nargs=-1)
@click.option("--x", type=int, default=None)
@click.option("--y", type=int, default=None)
@click.option("--double", "double_click", is_flag=True)
@click.option("--right", "right_click", is_flag=True)
@click.option("--middle", "middle_click", is_flag=True)
@click.option("--window", help="Window that must own the input.")
@_execution_options
def click_cmd(
    target: tuple[str, ...],
    x: int | None,
    y: int | None,
    double_click: bool,
    right_click: bool,
    middle_click: bool,
    window: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    if (x is None) != (y is None):
        raise click.UsageError("Use --x and --y together.")
    verb = "double click" if double_click else "right click" if right_click else "middle click" if middle_click else "click"
    destination = f"at {x} {y}" if x is not None else " ".join(target).strip()
    if not destination:
        raise click.UsageError("Provide a visible element name or --x/--y coordinates.")
    _run(f"{verb} {destination}", dry_run=dry_run, yes=yes, window=window)


@automation.command("move")
@click.option("--x", type=int, default=None)
@click.option("--y", type=int, default=None)
@click.option("--element", default=None, help="Visible element to move to.")
@click.option("--dry-run", is_flag=True)
def move(x: int | None, y: int | None, element: str | None, dry_run: bool) -> None:
    if element and (x is not None or y is not None):
        raise click.UsageError("Use --element or --x/--y, not both.")
    if (x is None) != (y is None):
        raise click.UsageError("Use --x and --y together.")
    if element:
        _run(f"move mouse to {element}", dry_run=dry_run)
        return
    if x is None:
        raise click.UsageError("Provide --element or --x/--y coordinates.")
    _run(f"move mouse to {x} {y}", dry_run=dry_run)


@automation.command("type")
@click.argument("text", nargs=-1, required=True)
@click.option("--window", help="Window that must own the input.")
@_execution_options
def type_cmd(text: tuple[str, ...], window: str | None, yes: bool, dry_run: bool) -> None:
    _run(f"type {' '.join(text)}", dry_run=dry_run, yes=yes, window=window)


@automation.command("press")
@click.argument("key")
@click.option("--window", help="Window that must own the input.")
@_execution_options
def press(key: str, window: str | None, yes: bool, dry_run: bool) -> None:
    _run(f"press {key}", dry_run=dry_run, yes=yes, window=window)


@automation.command("scroll")
@click.argument("direction", type=click.Choice(["up", "down"], case_sensitive=False))
@click.option("--amount", type=click.IntRange(1, 100), default=5, show_default=True)
@click.option("--window", help="Window that must own the input.")
@click.option("--dry-run", is_flag=True)
def scroll(direction: str, amount: int, window: str | None, dry_run: bool) -> None:
    _run(f"scroll {direction} {amount}", dry_run=dry_run, window=window)


@automation.command("focus")
@click.argument("window", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True)
def focus(window: tuple[str, ...], dry_run: bool) -> None:
    _run(f"focus {' '.join(window)}", dry_run=dry_run)


@automation.command("locate")
@click.argument("target", nargs=-1, required=True)
def locate(target: tuple[str, ...]) -> None:
    _run(f"locate {' '.join(target)}")


@automation.command("highlight")
@click.argument("target", nargs=-1, required=True)
def highlight(target: tuple[str, ...]) -> None:
    _run(f"highlight {' '.join(target)}")


@automation.command("session")
def session() -> None:
    """Run a process-local automation session with a pinned target window."""
    service = ScreenAutomationService()
    click.echo("Grandpa Automation Session")
    click.echo("Target window: none")
    while True:
        try:
            command = click.prompt("automation", prompt_suffix="> ").strip()
        except (EOFError, click.Abort):
            click.echo("Automation session stopped.")
            return
        if not command:
            continue
        normalized = " ".join(command.casefold().split())
        if normalized in {"exit", "quit", "stop"}:
            click.echo("Automation session stopped.")
            return
        if normalized == "status":
            target = service.target_window
            click.echo(f"Target window: {target.label if target else 'none'}")
            continue
        if normalized == "clear target":
            service.clear_target()
            click.echo("Automation target cleared.")
            continue
        if normalized.startswith("target "):
            command = f"focus {command.split(maxsplit=1)[1]}"
        if normalized.startswith("move "):
            parts = command.split()
            if len(parts) == 3 and all(part.lstrip("-").isdigit() for part in parts[1:]):
                command = f"move mouse to {parts[1]} {parts[2]}"
        _run(command, service=service)


__all__ = ["automation"]
