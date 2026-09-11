"""Defects found while building this suite.

These are not among the 20 command tests. Each one asserts the behaviour a user
would expect. An unfixed defect is marked ``xfail(strict=True)``, so a fix turns
into an XPASS failure; the fix removes the marker and the test keeps guarding it.
"""

from __future__ import annotations

import pytest

from tests.e2e.harness import chat_replies, sqlite_rows

pytestmark = pytest.mark.e2e


# Fixed: notes delete printed "Delete note ...? [y/N]" and never read an answer.
def test_answering_yes_at_the_notes_delete_prompt_deletes_the_note(
    cli, make_nonce
) -> None:
    title = make_nonce("e2eprompt")
    cli("notes", "create", title)

    answered = cli.at_terminal("notes", "delete", title, answer="y")

    assert f'Delete note "{title}"? [y/N]' in answered.stdout, answered.text
    assert f'Note deleted: "{title}".' in answered.stdout, answered.text
    assert title not in cli("notes", "list").text


# Fixed: downloads delete printed "Delete 1 download? [y/N]" and never read an answer.
def test_answering_yes_at_the_downloads_delete_prompt_deletes_the_file(
    cli, make_nonce
) -> None:
    target = cli.home / "Downloads" / f"{make_nonce('prompt-')}.pdf"
    target.write_bytes(b"%PDF")

    answered = cli.at_terminal("downloads", "delete", target.name, answer="y")

    assert "Delete 1 download (4 B)? [y/N]" in answered.stdout, answered.text
    assert "Deleted 1 download." in answered.stdout, answered.text
    assert not target.exists()


# Fixed: chat sent "find files named X" to screen automation, which searched the screen.
def test_chat_find_files_finds_a_file_in_documents(cli, e2e_model, make_nonce) -> None:
    stem = make_nonce("quarterly")
    (cli.home / "Documents" / f"{stem}.txt").write_text("numbers", encoding="utf-8")

    run = cli.chat(e2e_model, f"find files named {stem}")

    reply = chat_replies(run.text)[0]
    assert f"{stem}.txt" in reply, reply


# Fixed alongside it: "search my files for X" opened a Google search instead.
def test_chat_search_my_files_finds_a_file_and_opens_no_browser(
    cli, e2e_model, make_nonce
) -> None:
    stem = make_nonce("budget")
    (cli.home / "Documents" / f"{stem}.txt").write_text("numbers", encoding="utf-8")

    run = cli.chat(e2e_model, f"search my files for {stem}")

    reply = chat_replies(run.text)[0]
    assert f"{stem}.txt" in reply, reply
    assert "google" not in reply.lower(), reply


# Fixed: "remember that ..." was saved to memory.db (MemoryService), but chat
# recalls from personal_memory.db. (The xfail reason wrongly said core_brain.db.)
def test_chat_remember_that_is_recalled(cli, e2e_model, make_nonce) -> None:
    colour = make_nonce("teal")

    run = cli.chat(
        e2e_model,
        f"remember that my favorite color is {colour}",
        "what is my favorite color",
    )

    replies = chat_replies(run.text)
    assert len(replies) == 2 and colour in replies[1], replies
    stored = sqlite_rows(cli.grandpa_home / "personal_memory.db", "memories")
    assert ("favorite_color", colour) in [(r["key"], r["value"]) for r in stored]
