"""Application inventory CLI commands."""

from __future__ import annotations

import click

from grandpa.apps.inventory import find_app, list_apps, scan_app_inventory


@click.group("apps")
def apps() -> None:
    """Scan and query the local application inventory."""


@apps.command("scan")
def scan() -> None:
    discovered = scan_app_inventory()
    click.echo(f"Scanned {len(discovered)} apps.")


@apps.command("list")
def list_cmd() -> None:
    records = list_apps()
    if not records:
        click.echo("No app inventory found. Run `grandpa apps scan` first.")
        return
    for record in records:
        click.echo(f"{record.display_name} [{record.source}]")


@apps.command("find")
@click.argument("name", nargs=-1, required=True)
def find(name: tuple[str, ...]) -> None:
    result = find_app(" ".join(name))
    click.echo(result.message)
    if result.status == "found":
        record = result.matches[0]
        click.echo(record.launch_target)


__all__ = ["apps"]
