"""shell_exec's sanitised environment has to be the right shape for the platform.

The allowlist was ``("PATH", "HOME", "USER", "LANG", "TERM")`` -- a POSIX set, in
a Windows-first product. On Windows that is not merely incomplete: without
``SystemRoot``, ``powershell.exe`` cannot load the CLR and exits with "Internal
Windows PowerShell error. Loading managed Windows PowerShell failed with error
8009001d".

That is the reason four bundled skills shipped POSIX command lines. PowerShell
appeared not to work through this tool, so ``date``, ``find``, ``md5sum``, ``file``
and ``head`` looked like the available options -- and ``date`` under cmd.exe is the
built-in that sets the system clock.

Every variable added is a location pointer, not a secret; ``PATH``, always passed,
is more powerful than any of them. A caller wanting anything else still has to
name it in ``env_passthrough``.
"""

from __future__ import annotations

import os
import sys

import pytest

from grandpa.tools.shell_exec import (
    _BASE_ENV_KEYS,
    _WINDOWS_ENV_KEYS,
    _env_keys,
)

pytestmark = pytest.mark.core


def test_systemroot_is_passed_on_windows() -> None:
    """The one variable that is required rather than merely helpful."""
    if os.name != "nt":
        pytest.skip("the Windows allowlist only applies on Windows")

    assert "SystemRoot" in _env_keys()


def test_the_posix_allowlist_is_unchanged_by_this() -> None:
    """Adding Windows keys must not quietly widen POSIX behaviour."""
    assert _BASE_ENV_KEYS == ("PATH", "HOME", "USER", "LANG", "TERM")
    for key in _WINDOWS_ENV_KEYS:
        assert key not in _BASE_ENV_KEYS


def test_no_credential_bearing_variable_was_added() -> None:
    """The additions are OS location pointers, and this says so mechanically.

    A future addition of something like USERNAME, SESSIONNAME or a token-bearing
    variable should have to argue with a test rather than slip in beside
    SystemRoot.
    """
    forbidden = {
        "USERNAME",
        "USERDOMAIN",
        "SESSIONNAME",
        "LOGONSERVER",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
    }

    assert not (set(_WINDOWS_ENV_KEYS) & forbidden), (
        f"these carry user identity or user content, not OS locations: "
        f"{sorted(set(_WINDOWS_ENV_KEYS) & forbidden)}"
    )


@pytest.mark.real_actions(
    reason="runs powershell.exe through the real shell_exec to prove the "
    "environment is sufficient; reads the clock with Get-Date and writes nothing"
)
def test_powershell_actually_runs_through_shell_exec() -> None:
    """The point of the change, asserted against the real subprocess.

    Checking the allowlist contains SystemRoot only proves the declaration. This
    proves the thing that was broken now works, which is what four manifests were
    rewritten to depend on.
    """
    if sys.platform != "win32":
        pytest.skip("powershell.exe is Windows-only")
    from grandpa.tools.shell_exec import ShellExecTool

    result = ShellExecTool().execute(
        command='powershell -NoProfile -Command "Get-Date -Format yyyy"'
    )

    assert result.success, result.content
    assert "8009001d" not in result.content, (
        "powershell could not load the CLR, so the sanitised environment is "
        "still missing something it needs"
    )
    assert "20" in result.content, result.content
