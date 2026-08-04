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
    """Run the local profile wizard again."""

    console = Console()
    configure_profile(console=console, interactive=True)
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
