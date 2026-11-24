"""Bare-``grandpa`` interactive terminal routing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def needs_first_run() -> bool:
    """A bare ``grandpa`` at a real terminal with no config yet: run the wizard."""
    import os
    import sys

    from grandpa.core.config import DEFAULT_CONFIG_PATH

    if os.environ.get("GRANDPA_TESTING") or not sys.stdin.isatty():
        return False
    return not DEFAULT_CONFIG_PATH.exists()


def check_and_route(ctx: click.Context) -> None:
    """Called from the root group when no subcommand is invoked.

    Returns None and does nothing if a subcommand is being invoked
    (the user typed something specific like ``Grandpa ask``).
    """
    if ctx.invoked_subcommand is not None:
        return

    # Late imports to avoid circular import with cli/__init__.py.
    from grandpa.cli.launcher import launcher as launcher_cmd

    if needs_first_run():
        from grandpa.cli.setup_cmd import setup as setup_cmd

        try:
            ctx.invoke(setup_cmd)
        except SystemExit:
            pass  # the summary already said what to fix; open the menu anyway

    # Bare `grandpa` in a real terminal opens the full-screen interface, the
    # way `claude` or `gemini` do. The numbered menu is still `grandpa launcher`,
    # and it is what a pipe or a script gets.
    import os

    from grandpa.tui.app import can_run_fullscreen

    if can_run_fullscreen() and os.environ.get("GRANDPA_NO_TUI", "") not in {
        "1",
        "true",
    }:
        from grandpa.tui import main as tui_main

        raise SystemExit(tui_main())
    ctx.invoke(launcher_cmd)
