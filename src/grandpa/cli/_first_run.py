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

    ctx.invoke(launcher_cmd)
