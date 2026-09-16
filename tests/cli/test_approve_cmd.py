"""Audit finding 3: an approval code a terminal user can actually spend.

``pc_control`` stages a high-risk action and prints a code to the console. The
only redemption path was an HTTP POST, so the code was unspendable by the person
reading it -- the finding called it a dead end, and noted those actions were
"safe by accident, not by design".

Nothing here actuates anything: the staged action never runs, because every
assertion is about the approval flow.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from grandpa.cli.approve_cmd import approve
from grandpa.pc_control import LocalActionRequest, _create_pending


@pytest.fixture
def staged() -> str:
    request = LocalActionRequest(
        action_type="keyboard_type", target="hello", args={"text": "hello"}
    )
    return _create_pending(request)


def test_pending_actions_are_listed(staged: str) -> None:
    result = CliRunner().invoke(approve, ["--list"])

    assert result.exit_code == 0
    assert staged in result.output


def test_nothing_pending_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("grandpa.pc_control.list_pending_actions", lambda: [])

    result = CliRunner().invoke(approve, ["--list"])

    assert "Nothing is waiting" in result.output


def test_an_action_id_alone_is_not_an_authorisation(staged: str) -> None:
    """The id is in the HTTP response; the code is deliberately out of band."""
    result = CliRunner().invoke(approve, [staged])

    assert result.exit_code != 0
    assert "approval code is required" in result.output


def test_a_wrong_code_is_refused(staged: str) -> None:
    result = CliRunner().invoke(approve, [staged, "--code", "DEADBEEF"])

    assert result.exit_code != 0
    assert "not valid" in result.output


def test_denying_settles_the_action(staged: str) -> None:
    result = CliRunner().invoke(approve, [staged, "--deny"])

    assert result.exit_code == 0
    assert "Rejected" in result.output

    # And it cannot then be approved: a decided action is decided.
    again = CliRunner().invoke(approve, [staged, "--code", "DEADBEEF"])
    assert again.exit_code != 0
