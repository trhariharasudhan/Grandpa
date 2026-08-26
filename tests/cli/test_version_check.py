"""Tests for the update-check shim.

The PyPI poll this module used to perform targeted ``grandpa`` on PyPI, which
is an unrelated project. It has been removed: the check compared Grandpa's
version against a stranger's releases and pointed users at a pip command that
would install that project. These tests pin the removal — the shim must stay
inert and must never touch the network.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from grandpa.cli import _version_check
from grandpa.cli._version_check import UPDATE_CHECKS_AVAILABLE, check_for_updates


def test_update_checks_are_disabled():
    """Grandpa has no verified distribution channel to check against."""
    assert UPDATE_CHECKS_AVAILABLE is False


@pytest.mark.parametrize(
    "command_name",
    ["ask", "chat", "serve", "doctor", "init", "_bootstrap", "daemon", ""],
)
def test_check_for_updates_is_a_silent_no_op(command_name, capsys):
    assert check_for_updates(command_name) is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("command_name", ["ask", "chat", "doctor"])
def test_check_for_updates_makes_no_network_call(command_name):
    """Regression guard: the poll hit pypi.org on nearly every CLI run."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        check_for_updates(command_name)
    mock_urlopen.assert_not_called()


def test_module_exposes_no_pypi_endpoint():
    """Nothing should remain that names the unrelated PyPI package."""
    source_names = dir(_version_check)
    assert "_PYPI_API" not in source_names
    assert "_fetch_latest_stable" not in source_names
    assert "_get_latest_version" not in source_names


def test_check_for_updates_never_raises():
    """The CLI calls this on every command; it must not be able to fail."""
    assert check_for_updates(None) is None  # type: ignore[arg-type]
