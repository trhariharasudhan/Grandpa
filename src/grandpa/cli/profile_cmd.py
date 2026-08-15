"""Local-only profile management commands."""

from __future__ import annotations

import click
from rich.console import Console

from grandpa.profile import (
    configure_profile,
    format_profile,
    load_profile,
    reset_profile,
)


@click.group(invoke_without_command=True)
@click.pass_context
def profile(ctx: click.Context) -> None:
    """Show or configure Grandpa's local profile."""

    if ctx.invoked_subcommand is None:
        Console().print(format_profile(load_profile()))


@profile.command("edit")
def edit_profile() -> None:
    """Edit one local profile field."""

    console = Console()
    console.print("1. Edit display name")
    console.print("2. Edit preferred title")
    console.print("3. Reset profile")
    console.print("4. Back")
    action = click.prompt(
        "Select profile action",
        type=click.Choice(("1", "2", "3", "4")),
        default="4",
    )
    if action == "1":
        configure_profile(
            console=console, interactive=True, edit_username=True, edit_title=False
        )
    elif action == "2":
        configure_profile(
            console=console, interactive=True, edit_username=False, edit_title=True
        )
    elif action == "3":
        confirmed = click.confirm("Reset local profile?", default=False)
        if confirmed:
            reset_profile(confirmed=True)
            click.echo(
                "Profile reset. Onboarding will run at the next interactive launch."
            )
        else:
            click.echo("Profile reset cancelled.")
    else:
        return
    console.print(format_profile(load_profile()))


@profile.command("reset")
@click.option("--yes", is_flag=True, help="Reset without prompting for confirmation.")
def reset_profile_command(yes: bool) -> None:
    """Reset onboarding while preserving current local preferences."""

    confirmed = yes or click.confirm("Reset local profile?", default=False)
    if not confirmed:
        click.echo("Profile reset cancelled.")
        return
    reset_profile(confirmed=True)
    click.echo("Profile reset. Onboarding will run at the next interactive launch.")


__all__ = ["profile"]
