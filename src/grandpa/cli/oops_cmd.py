"""``grandpa oops`` -- one command to record what just broke.

    grandpa oops "voice did not hear me"
    grandpa oops --list
    grandpa oops --export

See :mod:`grandpa.diagnostics.oops` for which context is collected and why
those fields. This module is only the surface, and its one hard rule is that it
cannot fail: no exception from here reaches the user, and a note that cannot be
written to disk is printed instead so it is not lost.
"""

from __future__ import annotations

import click


@click.command("oops")
@click.argument("note", required=False)
@click.option("--list", "show_list", is_flag=True, help="Show what you have logged.")
@click.option(
    "--export",
    "do_export",
    is_flag=True,
    help="Write every note to one file to hand over.",
)
@click.option(
    "--to",
    "export_path",
    default=None,
    type=click.Path(dir_okay=False),
    help="With --export, where to write it. Defaults to beside the log.",
)
@click.option(
    "--context",
    "show_context",
    is_flag=True,
    help="With --list, print the full context of each note rather than a summary.",
)
def oops(
    note: str | None,
    show_list: bool,
    do_export: bool,
    export_path: str | None,
    show_context: bool,
) -> None:
    """Record a problem in one sentence, with the context that makes it
    diagnosable.

    Everything stays on this machine, under GRANDPA_HOME. The note is passed
    through the same redaction the screen pipeline uses, so a transcript
    pasted into it is treated the same way.
    """
    try:
        _run(note, show_list, do_export, export_path, show_context)
    except Exception as exc:  # noqa: BLE001 - this command must never fail
        # Last resort. If even reporting failed, the note is the thing that
        # must survive, so it goes to stdout where the user can see it.
        click.echo(f"grandpa oops could not finish ({type(exc).__name__}).")
        if note:
            click.echo(f"Your note, unsaved: {note}")


def _run(
    note: str | None,
    show_list: bool,
    do_export: bool,
    export_path: str | None,
    show_context: bool,
) -> None:
    from grandpa.diagnostics import oops as store

    if show_list:
        _print_list(store, show_context=show_context)
        return

    if do_export or export_path:
        target = store.export_to(export_path or None)
        found = store.entries()
        click.echo(f"Wrote {len(found)} note(s) to {target}")
        click.echo("Nothing was sent anywhere. Hand that file over as it is.")
        return

    if not note or not note.strip():
        click.echo('Say what went wrong, in quotes:')
        click.echo('  grandpa oops "voice did not hear me"')
        click.echo("")
        click.echo("  grandpa oops --list     what you have logged")
        click.echo("  grandpa oops --export   one file to hand over")
        return

    written, path = store.record(note)
    if written:
        click.echo("Logged. Nothing was sent anywhere.")
        click.echo(f"  {path}")
        click.echo("  grandpa oops --export when you want to hand it over.")
        return
    # The file could not be written. Do not lose the sentence.
    click.echo(f"Could not write to {path}, so here is the note instead:")
    click.echo(f"  {note.strip()}")


def _print_list(store: object, *, show_context: bool) -> None:
    found = store.entries()  # type: ignore[attr-defined]
    if not found:
        click.echo("Nothing logged yet.")
        click.echo('  grandpa oops "what went wrong"')
        return
    click.echo(f"{len(found)} note(s):")
    click.echo("")
    for index, entry in enumerate(found, start=1):
        click.echo(f"{index}. {entry.note or '(no note)'}")
        click.echo(f"   {entry.at or 'unknown time'}")
        context = entry.context or {}
        if show_context:
            for key, value in context.items():
                click.echo(f"   {key}: {value}")
        else:
            click.echo(f"   {_summarise(context)}")
        click.echo("")
    click.echo("Full detail: grandpa oops --list --context")
    click.echo("One file:    grandpa oops --export")


def _summarise(context: dict) -> str:
    """The one line worth seeing without asking for everything."""
    parts: list[str] = []
    command = (context.get("last_command") or {}).get("argv")
    if command:
        parts.append("after: grandpa " + " ".join(str(item) for item in command))
    capture = context.get("last_capture") or {}
    level = capture.get("speech_window_rms")
    if level is not None:
        parts.append(f"speech rms {level}")
    reason = capture.get("reason")
    if reason:
        parts.append(f"capture {reason}")
    error = (context.get("last_error") or {}).get("message")
    if error:
        parts.append(f"last error: {str(error).splitlines()[0][:60]}")
    return "   ".join(parts) or "no context recorded"


__all__ = ["oops"]
