"""Destructive commands whose confirmation prompt was missing or decorative.

Each is checked three ways: a piped "y" is refused (nobody at a terminal
answered), "n" typed at a real console cancels, and "y" typed there proceeds.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    ("command", "prompt"),
    [
        (["downloads", "archive"], "Archive 1 download (6 B)?"),
        (["downloads", "organize"], "Organize 1 download (6 B)?"),
    ],
    ids=["archive", "organize"],
)
def test_downloads_moves_ask_and_move_only_on_yes(
    cli, make_nonce, command, prompt
) -> None:
    downloads = cli.home / "Downloads"
    target = downloads / f"{make_nonce('bundle-')}.zip"
    target.write_bytes(b"PK e2e")
    args = [*command, target.name] if command[-1] == "archive" else command

    piped = cli(*args, stdin="y\n")
    assert piped.returncode == 1 and "stdin is not interactive" in piped.stderr, (
        piped.text
    )
    declined = cli.at_terminal(*args, answer="n")
    assert f"{prompt} [y/N]" in declined.stdout, declined.text
    assert "Downloads change cancelled." in declined.stdout, declined.text
    assert target.exists(), "moved after a refused or declined prompt"

    accepted = cli.at_terminal(*args, answer="y")

    assert accepted.returncode == 0, accepted.text
    assert not target.exists(), f"still in Downloads after yes: {accepted.text}"
    assert (downloads / "Archives" / target.name).read_bytes() == b"PK e2e", (
        accepted.text
    )
