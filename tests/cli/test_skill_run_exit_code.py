"""A failed `skill run` must exit non-zero.

It printed "Failed" and exited 0, so ``grandpa skill run x && next-thing`` ran
the next thing, and anything driving skills from a script read success. Three of
the four skills that still fail were found only by reading stdout, because the
exit code said they had worked.

The agent commands already exit 1 on failure (``agent_cmd.py:46``,
``agent_run_cmd.py:81``); this matches them. The reason is still printed first --
an exit code with no diagnostic just moves the problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from click.testing import CliRunner

from grandpa.cli import cli

pytestmark = pytest.mark.core


@dataclass
class _StepResult:
    content: str = "the step said why"


@dataclass
class _Result:
    success: bool
    step_results: list = field(default_factory=lambda: [_StepResult()])


class _Manager:
    def __init__(self, result: _Result) -> None:
        self._result = result
        self.unavailable_tools: dict = {}

    def execute(self, name, context):
        return self._result


@pytest.fixture
def manager(monkeypatch):
    def install(result: _Result):
        from grandpa.cli import skill_cmd

        monkeypatch.setattr(skill_cmd, "_get_manager", lambda **_: _Manager(result))
        monkeypatch.setattr(
            skill_cmd, "_warn_about_unavailable_tools", lambda *_a, **_k: None
        )

    return install


def test_a_failed_skill_run_exits_non_zero(manager) -> None:
    manager(_Result(success=False))

    result = CliRunner().invoke(cli, ["skill", "run", "any-skill"])

    assert result.exit_code != 0, (
        "a failed skill run exited 0, so a caller chaining on && continues and a "
        "script reads success"
    )


def test_the_failure_reason_is_still_printed(manager) -> None:
    """Exiting non-zero must not swallow the diagnostic that says why."""
    manager(_Result(success=False))

    result = CliRunner().invoke(cli, ["skill", "run", "any-skill"])

    assert "Failed" in result.output
    assert "the step said why" in result.output


def test_a_successful_skill_run_still_exits_zero(manager) -> None:
    manager(_Result(success=True))

    result = CliRunner().invoke(cli, ["skill", "run", "any-skill"])

    assert result.exit_code == 0, result.output
    assert "Success" in result.output


def test_an_unknown_skill_still_exits_non_zero(monkeypatch) -> None:
    """The path that already exited 1 must keep doing so."""
    from grandpa.cli import skill_cmd

    class _Missing:
        unavailable_tools: dict = {}

        def execute(self, name, context):
            raise KeyError(name)

    monkeypatch.setattr(skill_cmd, "_get_manager", lambda **_: _Missing())
    monkeypatch.setattr(
        skill_cmd, "_warn_about_unavailable_tools", lambda *_a, **_k: None
    )

    result = CliRunner().invoke(cli, ["skill", "run", "no-such-skill"])

    assert result.exit_code != 0
