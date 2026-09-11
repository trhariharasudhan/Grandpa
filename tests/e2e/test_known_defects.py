"""Defects found while building this suite, pinned as strict expected failures.

These are not among the 20 command tests. Each one asserts the behaviour a user
would expect. ``strict=True`` turns a fix into an XPASS failure, so whoever fixes
the defect has to promote the test into the main suite.
"""

from __future__ import annotations

import pytest

from tests.e2e.harness import chat_replies

pytestmark = pytest.mark.e2e


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason='notes delete prints "Delete note ...? [y/N]" but never reads an answer',
)
def test_answering_yes_at_the_notes_delete_prompt_deletes_the_note(
    cli, make_nonce
) -> None:
    title = make_nonce("e2eprompt")
    cli("notes", "create", title)

    cli("notes", "delete", title, stdin="y\n")

    assert title not in cli("notes", "list").text


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason='downloads delete prints "Delete 1 download? [y/N]" but never reads an answer',
)
def test_answering_yes_at_the_downloads_delete_prompt_deletes_the_file(
    cli, make_nonce
) -> None:
    target = cli.home / "Downloads" / f"{make_nonce('prompt-')}.pdf"
    target.write_bytes(b"%PDF")

    cli("downloads", "delete", target.name, stdin="y\n")

    assert not target.exists()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="chat sends 'find files named X' to screen automation, which searches the screen",
)
def test_chat_find_files_finds_a_file_in_documents(cli, e2e_model, make_nonce) -> None:
    stem = make_nonce("quarterly")
    (cli.home / "Documents" / f"{stem}.txt").write_text("numbers", encoding="utf-8")

    run = cli.chat(e2e_model, f"find files named {stem}")

    reply = chat_replies(run.text)[0]
    assert f"{stem}.txt" in reply, reply


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="'remember that ...' is stored in core_brain.db; recall reads personal_memory.db",
)
def test_chat_remember_that_is_recalled(cli, e2e_model, make_nonce) -> None:
    colour = make_nonce("teal")

    run = cli.chat(
        e2e_model,
        f"remember that my favorite color is {colour}",
        "what is my favorite color",
    )

    replies = chat_replies(run.text)
    assert len(replies) == 2 and colour in replies[1], replies
