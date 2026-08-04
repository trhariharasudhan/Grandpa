"""CLI commands for Grandpa local notes."""

from __future__ import annotations

import click

from grandpa.notes import handle_notes_command


@click.group(name="notes")
def notes() -> None:
    """Manage local Grandpa notes."""


@notes.command("list")
def list_notes() -> None:
    click.echo(handle_notes_command("show my notes").message)


@notes.command("recent")
def recent() -> None:
    click.echo(handle_notes_command("list recent notes").message)


@notes.command("search")
@click.argument("query", nargs=-1)
def search(query: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("search notes for " + " ".join(query)).message)


@notes.command("open")
@click.argument("name", nargs=-1)
def open_note(name: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("open my note " + " ".join(name)).message)


@notes.command("create")
@click.argument("name", nargs=-1)
def create(name: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("create a note called " + " ".join(name)).message)


@notes.command("append")
@click.argument("name")
@click.argument("content", nargs=-1)
def append(name: str, content: tuple[str, ...]) -> None:
    click.echo(handle_notes_command(f"notes append {name} {' '.join(content)}").message)


@notes.command("rename")
@click.argument("old_name")
@click.argument("new_name", nargs=-1)
def rename(old_name: str, new_name: tuple[str, ...]) -> None:
    click.echo(
        handle_notes_command(f"rename note {old_name} to {' '.join(new_name)}").message
    )


@notes.command("delete")
@click.argument("name", nargs=-1)
@click.option("--yes", is_flag=True, help="Confirm note deletion.")
def delete(name: tuple[str, ...], yes: bool) -> None:
    click.echo(
        handle_notes_command("delete note " + " ".join(name), confirmed=yes).message
    )


@notes.command("archive")
@click.argument("name", nargs=-1)
def archive(name: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("archive note " + " ".join(name)).message)


@notes.command("restore")
@click.argument("name", nargs=-1)
def restore(name: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("restore note " + " ".join(name)).message)


@notes.command("pin")
@click.argument("name", nargs=-1)
def pin(name: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("pin note " + " ".join(name)).message)


@notes.command("unpin")
@click.argument("name", nargs=-1)
def unpin(name: tuple[str, ...]) -> None:
    click.echo(handle_notes_command("unpin note " + " ".join(name)).message)


__all__ = ["notes"]
