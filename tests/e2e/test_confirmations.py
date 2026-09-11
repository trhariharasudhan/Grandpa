"""Destructive commands whose confirmation prompt was missing or decorative.

Each is checked three ways: a piped "y" is refused (nobody at a terminal
answered), "n" typed at a real console cancels, and "y" typed there proceeds.
"""

from __future__ import annotations

import re

import pytest

from tests.e2e.harness import sqlite_rows

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


def test_agents_delete_asks_and_archives_only_on_yes(cli, make_nonce) -> None:
    name = make_nonce("e2e-archive-")
    created = cli("agents", "create", "--name", name, "--type", "simple")
    agent_id = re.search(r"Created agent: (\w+)", created.text).group(1)
    db = cli.grandpa_home / "agents.db"

    def status() -> str:
        (agent,) = sqlite_rows(db, "managed_agents")
        return agent["status"]

    piped = cli("agents", "delete", agent_id, stdin="y\n")
    assert piped.returncode == 1 and "stdin is not interactive" in piped.stderr, (
        piped.text
    )
    assert status() == "idle"

    declined = cli.at_terminal("agents", "delete", agent_id, answer="n")
    assert f"Archive agent {agent_id} ({name})? [y/N]" in declined.stdout, declined.text
    assert "Agent archive cancelled." in declined.stdout, declined.text
    assert status() == "idle"

    accepted = cli.at_terminal("agents", "delete", agent_id, answer="y")
    assert accepted.returncode == 0, accepted.text
    assert status() == "archived", accepted.text

    missing = cli("agents", "delete", "no-such-agent", "--yes")
    assert missing.returncode == 1 and "Agent not found" in missing.text, missing.text


@pytest.mark.parametrize(
    ("args", "prompt"),
    [
        (
            ["calendar", "create", "team sync tomorrow at 3pm"],
            "Create this Calendar event?",
        ),
        (["calendar", "update", "tomorrow at 4pm"], "Update this Calendar event?"),
        (["calendar", "delete", "team sync"], "Delete this Calendar event?"),
    ],
    ids=["create", "update", "delete"],
)
def test_calendar_changes_read_the_answer_to_their_prompt(cli, args, prompt) -> None:
    """No Google account is configured in the sandbox, so "y" can only fail to connect."""
    piped = cli(*args, stdin="y\n")
    assert piped.returncode == 1 and "stdin is not interactive" in piped.stderr, (
        piped.text
    )

    declined = cli.at_terminal(*args, answer="n")
    assert f"{prompt} [y/N]" in declined.stdout, declined.text
    assert "Calendar change cancelled." in declined.stdout, declined.text

    accepted = cli.at_terminal(*args, answer="y")
    assert f"{prompt} [y/N]" in accepted.stdout, accepted.text
    assert "cancelled" not in accepted.stdout, accepted.text
    # The answer was acted on: the change went ahead and hit the missing account.
    assert re.search(r"Calendar action failed|not configured", accepted.stdout, re.I), (
        accepted.text
    )
