"""`Grandpa self-update` — upgrade Grandpa to the latest release.

Runs the right upgrade command for how the user installed Grandpa:

- PyPI installs get ``pip install --upgrade Grandpa``.
- uv-tool installs get ``uv tool upgrade Grandpa``.
- Editable git checkouts get ``git pull && uv sync`` in the checkout.

The detection logic is shared with the post-command "new version
available" hint in ``_version_check.py`` so both surfaces stay in sync.
"""

from __future__ import annotations

import shlex
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
    click.echo(f"Upgrade command: {info.upgrade_command}")

    if check:
        return

    if info.kind == "unknown":
        click.echo(
            "\nCould not determine install method with confidence. The "
            "command above is a best guess; verify it matches how you "
            "installed before running.",
            err=True,
        )

    if not yes:
        if not click.confirm("\nRun the upgrade command now?", default=True):
            click.echo("Aborted.")
            sys.exit(1)

    click.echo(f"\n→ {info.upgrade_command}\n")

    # ``editable-git`` uses shell features (``&&``); the others are
    # simple argv-style commands. Use ``shell=True`` only for the
    # editable case to keep the surface small. The command itself is
    # constructed from a trusted, locally-detected path — no user
    # input flows into it.
    if info.kind == "editable-git":
        result = subprocess.run(info.upgrade_command, shell=True)
    else:
        result = subprocess.run(shlex.split(info.upgrade_command))

    if result.returncode != 0:
        click.echo(
            f"\nUpgrade command exited with code {result.returncode}. "
            "Inspect the output above for the failure mode.",
            err=True,
        )
        sys.exit(result.returncode)

    click.echo("\nUpgrade complete. Re-run `Grandpa --version` to confirm.")
