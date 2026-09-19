"""Chat confirms browser actions, and nothing opens until the user says yes.

Every attempt to open a URL or launch a program is recorded instead of done, so
these tests never touch a real browser.
"""

from __future__ import annotations

import pytest

from tests.e2e.harness import run_cli_recording_launches

pytestmark = pytest.mark.e2e

# Phrases that navigate, with the address the user must be shown.
NAVIGATION = [
    ("open example.com", "https://example.com"),
    ("search google for red pandas", "https://www.google.com/search?q=red+pandas"),
    ("open browser history", "chrome://history"),
]


def _chat(cli, model, *lines, answer=None):
    """One chat turn, answering the confirmation prompt with ``answer``."""
    typed = [*lines]
    if answer is not None:
        typed.append(answer)
    typed.append("exit")
    return run_cli_recording_launches(
        cli.sandbox,
        ["chat", "--no-fullscreen", "-m", model],
        cwd=cli.sandbox.root,
        stdin_text="\n".join(typed) + "\n",
        timeout=420,
    )


@pytest.mark.parametrize(("phrase", "address"), NAVIGATION, ids=lambda v: v.split()[0])
def test_chat_asks_before_navigating_and_no_opens_nothing(
    cli, e2e_model, phrase, address
) -> None:
    run, attempts = _chat(cli, e2e_model, phrase, answer="n")

    assert "Confirm browser action:" in run.text, run.tail(400)
    assert address in run.text, run.tail(400)
    assert attempts == [], f"something opened after answering n: {attempts}"


@pytest.mark.parametrize(("phrase", "address"), NAVIGATION, ids=lambda v: v.split()[0])
def test_chat_opens_exactly_what_it_showed_after_yes(
    cli, e2e_model, phrase, address
) -> None:
    run, attempts = _chat(cli, e2e_model, phrase, answer="y")

    assert "Confirm browser action:" in run.text, run.tail(400)
    assert [item["value"] for item in attempts] == [address], run.tail(400)


def test_chat_asks_before_starting_a_browser(cli, e2e_model) -> None:
    declined, attempts = _chat(cli, e2e_model, "open chrome", answer="n")

    assert "Confirm browser action:" in declined.text, declined.tail(400)
    assert attempts == [], f"Chrome started after answering n: {attempts}"

    accepted, attempts = _chat(cli, e2e_model, "open chrome", answer="y")

    assert attempts, "answering y did not try to start Chrome"
    assert any("chrome" in item["value"].lower() for item in attempts), attempts


def test_chat_search_through_local_actions_waits_for_approval(cli, e2e_model) -> None:
    """The other chat path: local_actions' "search <words>".

    It used to be held as a pending action and approved by a "yes" on the next
    turn. Since navigation moved onto the action layer, chat asks inline, as it
    does for every other browser action -- and still shows the address first.
    """
    run, attempts = _chat(cli, e2e_model, "search python packaging", answer="no")

    assert "Confirm" in run.text, run.tail(400)
    assert "https://www.google.com/search?q=python+packaging" in run.text, run.tail(400)
    assert attempts == [], f"search ran before approval: {attempts}"

    approved, attempts = _chat(cli, e2e_model, "search python packaging", answer="yes")

    assert [item["value"] for item in attempts] == [
        "https://www.google.com/search?q=python+packaging"
    ], approved.tail(400)


def test_trusted_domains_open_without_asking(cli, e2e_model) -> None:
    cli.grandpa_home.mkdir(parents=True, exist_ok=True)
    (cli.grandpa_home / "config.toml").write_text(
        f'[intelligence]\ndefault_model = "{e2e_model}"\n\n'
        '[tools.browser]\ntrusted_domains = "example.com"\n',
        encoding="utf-8",
    )

    run, attempts = _chat(cli, e2e_model, "open example.com")

    assert "Confirm browser action:" not in run.text, run.tail(400)
    assert [item["value"] for item in attempts] == ["https://example.com"], run.tail(
        400
    )
