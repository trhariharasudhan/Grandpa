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


def _powershell_startup_diagnosis() -> str:
    """Why the sanitised run did not finish, measured rather than guessed.

    A bare "Command timed out after 30 seconds." says nothing about whether the
    environment is wrong, the host is slow, or the process is blocked -- and
    those want three different fixes. This re-runs the same command with the
    full environment, and with the sanitised one plus the variables PowerShell
    startup is documented to use, so the failure names its own cause:

    * full environment fast, sanitised slow  -> the allowlist is missing
      something, and the delta below says which candidates exist to add.
    * both slow                              -> the host, not the allowlist.
    * stdin=DEVNULL fast, inherited slow     -> blocked reading stdin, which
      has bitten this tool before (see the comment in
      ``skills/data/backup-files.toml`` about cmd.exe's ``date`` prompting).
    """
    import subprocess
    import time

    from grandpa.tools.shell_exec import _env_keys

    command = 'powershell -NoProfile -Command "Get-Date -Format yyyy"'
    sanitised = {
        key: os.environ[key] for key in _env_keys() if os.environ.get(key) is not None
    }
    # Variables PowerShell 5.1 reads at startup that the allowlist omits. The
    # module analysis cache lives under LOCALAPPDATA and the module search path
    # comes from PSModulePath, so without them a cold start can enumerate every
    # module on the machine -- which on a CI image is a great many.
    candidates = (
        "PSModulePath",
        "LOCALAPPDATA",
        "APPDATA",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "PROCESSOR_ARCHITECTURE",
        "COMPUTERNAME",
        "OS",
    )
    present = [key for key in candidates if os.environ.get(key) is not None]

    def timed(label: str, env: dict[str, str] | None, stdin: object) -> str:
        start = time.time()
        try:
            done = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=40,
                env=env,
                stdin=stdin,
            )
            return (
                f"  {label:34s} {time.time() - start:6.2f}s "
                f"rc={done.returncode} out={(done.stdout or '').strip()[:30]!r}"
            )
        except subprocess.TimeoutExpired:
            return f"  {label:34s} {time.time() - start:6.2f}s TIMED OUT"
        except Exception as exc:  # pragma: no cover - diagnosis must not raise
            return f"  {label:34s} {type(exc).__name__}: {exc}"

    widened = dict(sanitised)
    for key in present:
        widened[key] = os.environ[key]

    lines = [
        "powershell startup, same command, three environments:",
        timed("full environment", None, None),
        timed("sanitised (what the tool does)", sanitised, None),
        timed("sanitised + startup vars", widened, None),
        timed("sanitised, stdin=DEVNULL", sanitised, subprocess.DEVNULL),
        f"allowlist passes: {sorted(sanitised)}",
        f"omitted startup vars present on this host: {present}",
        f"PSModulePath entries: {len(os.environ.get('PSModulePath', '').split(os.pathsep))}",
    ]
    return "\n".join(lines)


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

    assert result.success, f"{result.content}\n\n{_powershell_startup_diagnosis()}"
    assert "8009001d" not in result.content, (
        "powershell could not load the CLR, so the sanitised environment is "
        "still missing something it needs"
    )
    assert "20" in result.content, result.content
