"""Tests for `Grandpa self-update`.

The important property here is negative: only a git checkout may run an
upgrade. The PyPI name ``grandpa`` belongs to an unrelated project, so any
other install shape must refuse rather than shell out — otherwise
``self-update`` silently installs someone else's package over the user's
environment.

The subprocess call is always mocked; no real upgrade is ever run.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from grandpa.cli._install_detect import NO_DISTRIBUTION_REASON, InstallInfo
from grandpa.cli.self_update_cmd import self_update

#: Install shapes with no verified upgrade source.
UNSUPPORTED_KINDS = ["pypi", "uv-tool", "unknown"]


def _mock_info(kind: str = "editable-git") -> InstallInfo:
    if kind == "editable-git":
        return InstallInfo(
            kind=kind,
            upgrade_command="cd /tmp/repo && git pull && uv sync",
        )
    return InstallInfo(
        kind=kind,
        upgrade_command="",
        unsupported_reason=NO_DISTRIBUTION_REASON,
    )


def _patched(kind: str):
    return patch(
        "grandpa.cli.self_update_cmd.detect_install",
        return_value=_mock_info(kind),
    )


# --------------------------------------------------------------------------
# Supported path: editable git checkout
# --------------------------------------------------------------------------


def test_check_flag_prints_command_and_exits_clean():
    with _patched("editable-git"):
        result = CliRunner().invoke(self_update, ["--check"])
    assert result.exit_code == 0
    assert "git pull" in result.output
    assert "Install method: editable-git" in result.output


def test_check_does_not_invoke_subprocess():
    with (
        _patched("editable-git"),
        patch("grandpa.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        CliRunner().invoke(self_update, ["--check"])
    mock_run.assert_not_called()


def test_editable_git_uses_shell_true():
    """The git path chains with `&&`, so it needs a shell."""
    with (
        _patched("editable-git"),
        patch(
            "grandpa.cli.self_update_cmd.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert kwargs.get("shell") is True
    assert args[0] == "cd /tmp/repo && git pull && uv sync"


def test_failed_upgrade_propagates_exit_code():
    with (
        _patched("editable-git"),
        patch(
            "grandpa.cli.self_update_cmd.subprocess.run",
            return_value=MagicMock(returncode=3),
        ),
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 3


def test_decline_confirmation_exits_nonzero():
    with (
        _patched("editable-git"),
        patch("grandpa.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, input="n\n")
    assert result.exit_code == 1
    assert "Aborted" in result.output
    mock_run.assert_not_called()


# --------------------------------------------------------------------------
# Unsupported paths: must refuse, never execute
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", UNSUPPORTED_KINDS)
def test_unsupported_install_refuses_and_runs_nothing(kind):
    """Regression guard: the supply-chain hazard this replaced.

    Previously these shapes ran ``pip install --upgrade grandpa``, which
    installs an unrelated PyPI project.
    """
    with (
        _patched(kind),
        patch("grandpa.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 1
    mock_run.assert_not_called()
    assert "no published package" in result.output


@pytest.mark.parametrize("kind", UNSUPPORTED_KINDS)
def test_unsupported_install_check_flag_explains_without_failing(kind):
    with (
        _patched(kind),
        patch("grandpa.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["--check"])
    assert result.exit_code == 0
    mock_run.assert_not_called()
    assert "(none available)" in result.output


@pytest.mark.parametrize("kind", UNSUPPORTED_KINDS + ["editable-git"])
@pytest.mark.parametrize("argv", [["-y"], ["--check"], []])
def test_self_update_never_installs_the_pypi_grandpa_package(kind, argv):
    """No invocation, in any mode, may run pip or uv against ``grandpa``."""
    with (
        _patched(kind),
        patch(
            "grandpa.cli.self_update_cmd.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as mock_run,
    ):
        CliRunner().invoke(self_update, argv, input="n\n")

    for call in mock_run.call_args_list:
        command = call.args[0]
        rendered = command if isinstance(command, str) else " ".join(command)
        assert "pip install" not in rendered
        assert "uv tool upgrade" not in rendered
