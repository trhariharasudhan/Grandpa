"""CLI commands for Grandpa Gmail integration."""

from __future__ import annotations

import click

from grandpa.gmail import GmailAuthManager, handle_gmail_command


@click.group(name="gmail")
def gmail() -> None:
    """Manage Gmail integration."""


@gmail.command("setup")
def setup() -> None:
    """Run the explicit Gmail OAuth setup flow."""

    result = handle_gmail_command("gmail setup")
    click.echo(result.message)
    if result.status not in {"handled", "not_configured"}:
        raise click.ClickException(result.message)


@gmail.command("status")
def status() -> None:
    """Show Gmail connection status."""

    auth_status = GmailAuthManager().status()
    click.echo(auth_status.message)
    if auth_status.account:
        click.echo(f"Account: {auth_status.account}")


@gmail.command("disconnect")
def disconnect() -> None:
    """Disconnect Gmail by removing the local OAuth token."""

    result = handle_gmail_command("gmail disconnect")
    click.echo(result.message)


@gmail.command("inbox")
def inbox() -> None:
    click.echo(handle_gmail_command("show inbox").message)


@gmail.command("unread")
def unread() -> None:
    click.echo(handle_gmail_command("show unread emails").message)


@gmail.command("search")
@click.argument("query", nargs=-1)
def search(query: tuple[str, ...]) -> None:
    click.echo(handle_gmail_command("search gmail for " + " ".join(query)).message)


@gmail.command("labels")
def labels() -> None:
    click.echo(handle_gmail_command("show gmail labels").message)


@gmail.command("read")
@click.argument("selector", required=False, default="latest")
def read(selector: str) -> None:
    command = "read latest email" if selector == "latest" else f"read {selector}"
    click.echo(handle_gmail_command(command).message)


@gmail.command("summarize")
@click.argument("selector", required=False, default="latest")
def summarize(selector: str) -> None:
    command = "summarize latest email" if selector == "latest" else f"summarize {selector}"
    click.echo(handle_gmail_command(command).message)


__all__ = ["gmail"]
