"""Confirmation helpers for destructive CLI commands (grandpa.cli._tty).

The end-to-end behaviour, typed at a real console, is covered in tests/e2e.
"""

from __future__ import annotations

import click
import pytest

import grandpa.cli._tty as tty


def _no_prompt(*_args, **_kwargs):
    raise AssertionError("click.confirm must not be called without a terminal")


def test_non_interactive_stdin_is_never_asked(monkeypatch) -> None:
    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: False)
    monkeypatch.setattr(click, "confirm", _no_prompt)

    assert tty.confirm_destructive('Delete note "x"? [y/N]') is None


@pytest.mark.parametrize("answer", [True, False])
def test_interactive_stdin_returns_the_answer_to_a_clean_prompt(
    monkeypatch, answer
) -> None:
    asked = []
    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(
        click,
        "confirm",
        lambda prompt, default: asked.append((prompt, default)) or answer,
    )

    assert tty.confirm_destructive('Delete note "x"? [y/N]') is answer
    assert asked == [('Delete note "x"?', False)]


def test_eof_or_ctrl_c_at_the_prompt_is_a_no(monkeypatch) -> None:
    def _abort(*_args, **_kwargs):
        raise click.Abort()

    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(click, "confirm", _abort)

    assert tty.confirm_destructive("Delete?") is False


def test_terminal_confirmation_reports_each_outcome(monkeypatch, capsys) -> None:
    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: False)
    refused = tty.TerminalConfirmation(lambda action: f"Delete {action}? [y/N]")

    assert refused("note") is False
    with pytest.raises(SystemExit) as exit_info:
        refused.finish('Delete note "note"? [y/N]', cancelled="Cancelled.")
    assert exit_info.value.code == 1
    assert "stdin is not interactive" in capsys.readouterr().err

    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(click, "confirm", lambda prompt, default: False)
    declined = tty.TerminalConfirmation(lambda action: f"Delete {action}?")
    declined("note")
    declined.finish("pending message", cancelled="Cancelled.")
    assert capsys.readouterr().out == "Cancelled.\n"

    never_asked = tty.TerminalConfirmation(_no_prompt)
    never_asked.finish("Note not found.", cancelled="Cancelled.")
    assert capsys.readouterr().out == "Note not found.\n"


def test_require_confirmation_skips_the_prompt_with_yes(monkeypatch) -> None:
    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: False)
    monkeypatch.setattr(click, "confirm", _no_prompt)

    assert tty.require_confirmation("Cancel?", yes=True, cancelled="Kept.") is True
    with pytest.raises(SystemExit):
        tty.require_confirmation("Cancel?", yes=False, cancelled="Kept.")
