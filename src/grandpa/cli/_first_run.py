"""Bare-``grandpa`` interactive terminal routing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def check_and_route(ctx: click.Context) -> None:
    """Called from the root group when no subcommand is invoked.

    Returns None and does nothing if a subcommand is being invoked
    (the user typed something specific like ``Grandpa ask``).
    """
    if ctx.invoked_subcommand is not None:
        return

    # Late imports to avoid circular import with cli/__init__.py.
    from grandpa.cli.chat_cmd import chat as chat_cmd

    fullscreen = ctx.obj.get("fullscreen")
    ctx.invoke(chat_cmd, tui_mode=True, fullscreen=fullscreen)
