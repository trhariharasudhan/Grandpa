"""Destructive commands whose confirmation prompt was missing or decorative.

Each is checked three ways: a piped "y" is refused (nobody at a terminal
answered), "n" typed at a real console cancels, and "y" typed there proceeds.
"""

from __future__ import annotations

import re

import pytest

from tests.e2e.harness import sqlite_rows

# ...and out of the default-deny actuation fixture (tests/actuation_guard.py).
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_actions(
        reason="runs the real CLI as a subprocess in a throwaway sandbox, which is what this suite is for; the sandbox has its own HOME and the harness records launches and window actions instead of performing them"
    ),
]


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
    # The answer was acted on: the change went ahead and hit the missing account,
    # and a change that did not happen exits non-zero.
    assert re.search(r"Calendar action failed|not configured", accepted.stdout, re.I), (
        accepted.text
    )
    assert accepted.returncode == 1, accepted.text


@pytest.mark.parametrize(
    ("phrase", "cancelled", "done"),
    [
        ("delete note {name}", "Note deletion cancelled.", 'Note deleted: "{name}".'),
        (
            "downloads delete {name}.pdf",
            "Downloads change cancelled.",
            "Deleted 1 download.",
        ),
    ],
    ids=["notes", "downloads"],
)
def test_chat_delete_prompts_read_the_answer(
    cli, e2e_model, make_nonce, phrase, cancelled, done
) -> None:
    """Chat printed "...? [y/N]" and sent the answer to the model instead."""
    from tests.e2e.harness import chat_replies

    name = make_nonce("chatprompt")
    is_note = phrase.startswith("delete note")

    def present() -> bool:
        if is_note:
            return any((cli.grandpa_home / "notes").glob(f"{name}*.md"))
        return (cli.home / "Downloads" / f"{name}.pdf").exists()

    def setup() -> None:
        if is_note:
            cli("notes", "create", name)
        else:
            (cli.home / "Downloads" / f"{name}.pdf").write_bytes(b"%PDF")

    setup()
    declined = cli.chat(e2e_model, phrase.format(name=name), "n")
    assert cancelled in chat_replies(declined.text)[0], declined.tail(400)
    assert present(), "deleted after answering n"

    accepted = cli.chat(e2e_model, phrase.format(name=name), "y")
    assert done.format(name=name) in chat_replies(accepted.text)[0], accepted.tail(400)
    assert not present(), "still there after answering y"


def test_memory_delete_refuses_a_piped_answer(cli, make_nonce) -> None:
    """These prompts used to accept a piped "y" as if a person had typed it."""
    fact = f"e2e keepsake {make_nonce('')}"
    cli("memory", "remember", fact)
    key = fact.replace(" ", "_")

    piped = cli("memory", "delete", key, stdin="y\n")

    assert piped.returncode == 1 and "stdin is not interactive" in piped.stderr, (
        piped.text
    )
    assert fact in cli("memory", "search", fact.split()[-1]).text

    accepted = cli.at_terminal("memory", "delete", key, answer="y")

    assert accepted.returncode == 0, accepted.text
    assert fact not in cli("memory", "search", fact.split()[-1]).text
