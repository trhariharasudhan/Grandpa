"""`Grandpa self-update` — upgrade a Grandpa git checkout.

Grandpa is distributed as a git checkout, not as a package. Editable git
installs upgrade with ``git pull && uv sync`` against the user's own remote.

Every other install shape refuses: the PyPI name ``grandpa`` belongs to an
unrelated project, so there is no package this command could safely upgrade
from. See ``_install_detect.NO_DISTRIBUTION_REASON``.
"""

from __future__ import annotations

import subprocess
import sys

import click

import grandpa
from grandpa.cli._install_detect import detect_install


@click.command(
    "self-update",
    help=(
        "Upgrade Grandpa to the latest release. Detects how you "
        "installed (pip, uv tool, editable git) and runs the right "
        "command. Use --check to only print the upgrade command "
        "without running it."
    ),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print the upgrade command that would run, without executing it.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the interactive confirmation prompt.",
)
def self_update(check: bool, yes: bool) -> None:
    info = detect_install()
    current = grandpa.__version__

    click.echo(f"Current Grandpa version: v{current}")
    click.echo(f"Install method: {info.kind}")

    if not info.can_upgrade:
        # No verified source exists for this install shape. Refuse rather than
        # guess — a guess here installs an unrelated PyPI package.
        click.echo("Upgrade command: (none available)")
        click.echo(f"\n{info.unsupported_reason}", err=True)
        if check:
            return
        sys.exit(1)

    click.echo(f"Upgrade command: {info.upgrade_command}")

    if check:
        return

    if not yes:
        if not click.confirm("\nRun the upgrade command now?", default=True):
            click.echo("Aborted.")
            sys.exit(1)

    click.echo(f"\n→ {info.upgrade_command}\n")

    # ``editable-git`` is the only shape that reaches here, and its command
    # chains with ``&&``, so it needs a shell. The command is built from a
    # locally-detected checkout path — no user input flows into it.
    result = subprocess.run(info.upgrade_command, shell=True)

    if result.returncode != 0:
        click.echo(
            f"\nUpgrade command exited with code {result.returncode}. "
            "Inspect the output above for the failure mode.",
            err=True,
        )
        sys.exit(result.returncode)

    click.echo("\nUpgrade complete. Re-run `Grandpa --version` to confirm.")
