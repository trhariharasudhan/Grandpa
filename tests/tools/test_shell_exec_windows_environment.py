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
import time
import warnings

import pytest

from grandpa.tools.shell_exec import (
    _BASE_ENV_KEYS,
    _WINDOWS_ENV_KEYS,
    _env_keys,
)

pytestmark = pytest.mark.core

#: Passed explicitly rather than inheriting shell_exec's 30s default, for the
#: reason written out in the asserted test below. Two calls at this ceiling
#: still finish inside the 300s pytest-timeout set in pyproject.toml.
_TIMEOUT_S = 90

#: Above this, the test reports how long the call took instead of only whether
#: it passed. Not an assertion: a slow host is recorded, not failed.
_SLOW_START_S = 5.0


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

    Asserted on the second call, not the first. What this test guards against
    fails fast and loud: with SystemRoot taken back out, powershell exits in
    0.13s with returncode 0xFFFF0000 -- measured, not assumed. So a 30s wall,
    which is what windows-latest gave this call on every run, is never that
    failure. It is the host taking that long to start the process, and 30s was
    not a number this test chose: it passed no timeout at all and inherited
    shell_exec's default. Paying the first-use cost before the asserted call is
    tests/conftest.py's _warm_lazy_backends reasoning applied to a process
    instead of an import -- the assertion is about the environment being
    sufficient, and it should not double as a stopwatch on powershell.exe.

    Both durations go into a warning whenever either is slow, because warming
    only helps if the cost is per-machine. PowerShell keeps its command-analysis
    cache under LOCALAPPDATA and finds modules through PSModulePath, and neither
    is on the allowlist -- deliberately: the sibling test above forbids
    LOCALAPPDATA as user content. If that absence is what costs the time then the
    cache can never be written, every call re-pays it, the second call is as slow
    as the first, and this is a product problem rather than a test one. The two
    numbers in that warning are what will say which it is.
    """
    if sys.platform != "win32":
        pytest.skip("powershell.exe is Windows-only")
    from grandpa.tools.shell_exec import ShellExecTool

    tool = ShellExecTool()
    command = 'powershell -NoProfile -Command "Get-Date -Format yyyy"'

    started = time.perf_counter()
    tool.execute(command=command, timeout=_TIMEOUT_S)
    first_s = time.perf_counter() - started

    started = time.perf_counter()
    result = tool.execute(command=command, timeout=_TIMEOUT_S)
    second_s = time.perf_counter() - started

    if max(first_s, second_s) > _SLOW_START_S:
        warnings.warn(
            f"powershell through shell_exec took {first_s:.1f}s and then "
            f"{second_s:.1f}s under the sanitised environment, against "
            f"{_SLOW_START_S:.0f}s expected. A fast second call means the cost "
            "is per-machine and paying it once is enough. Two slow calls mean "
            "it is per-process, and the answer is LOCALAPPDATA and PSModulePath "
            "on shell_exec's allowlist, so PowerShell can cache its command "
            "analysis instead of redoing it every time.",
            stacklevel=1,
        )

    assert result.success, result.content
    assert "8009001d" not in result.content, (
        "powershell could not load the CLR, so the sanitised environment is "
        "still missing something it needs"
    )
    assert "20" in result.content, result.content
