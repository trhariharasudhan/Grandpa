"""No bundled skill may run a POSIX command that means something else on Windows.

``shell_exec`` is ``subprocess.run(..., shell=True)``, which on Windows is
``cmd.exe``. Four of the eighteen bundled skills shipped POSIX command lines, and
the failure modes were not symmetrical:

* ``backup-files`` ran ``date +%Y%m%d_%H%M%S``. In cmd.exe ``date`` is not the GNU
  program that prints a timestamp -- it is the built-in that **sets the system
  clock**. With an argument it cannot parse it prints "The system cannot accept
  the date entered." and prompts "Enter the new date: (dd-mm-yy)" on stdin. A
  refused argument and an unanswered prompt were the only things between a
  bundled skill and the machine's clock.
* ``file-deduplicator``, ``file-organizer`` and ``search-and-index`` ran POSIX
  ``find`` with ``md5sum``, ``file`` and ``head``. Windows ``find`` is a string
  search tool and the other three do not exist. Worse than failing: the skills
  reported **Success** and passed the error text to the next step as data --
  ``find: missing argument to `-exec'`` became the input to "identify duplicate
  files from the checksums", and an empty result became "No results found.",
  which reads as an empty directory rather than a command that could not run.

The `find` cases only produced a GNU error at all because Git Bash happened to be
on PATH. On a clean Windows machine they would have failed differently, which is
the deeper reason to test the manifests rather than the behaviour on one box.

``_DIFFERENT_ON_WINDOWS`` is a list of names, so a new manifest using one is
caught by name rather than by someone noticing. ``tar`` is deliberately absent:
it genuinely ships with Windows 10 and later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomllib

pytestmark = pytest.mark.core

DATA = Path(__file__).resolve().parents[2] / "src" / "grandpa" / "skills" / "data"
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

#: Commands that exist on Windows but do something different, or do not exist.
#: The value is what makes it wrong, and it is printed on failure.
_DIFFERENT_ON_WINDOWS = {
    "date": "cmd.exe's `date` SETS the system clock; it does not print one. Use "
    '`powershell -NoProfile -Command "Get-Date -Format ..."`.',
    "time": "cmd.exe's `time` SETS the system clock. Use Get-Date.",
    "find": "Windows `find` is a string search tool and takes none of POSIX "
    "find's switches. Use Get-ChildItem.",
    "md5sum": "does not exist on Windows. Use Get-FileHash.",
    "sha1sum": "does not exist on Windows. Use Get-FileHash.",
    "sha256sum": "does not exist on Windows. Use Get-FileHash.",
    "file": "does not exist on Windows. Windows types files by extension.",
    "head": "does not exist on Windows. Use Select-Object -First.",
    "tail": "does not exist on Windows. Use Select-Object -Last.",
    "grep": "does not exist on Windows. Use Select-String.",
    "sed": "does not exist on Windows.",
    "awk": "does not exist on Windows.",
    "ls": "does not exist in cmd.exe. Use Get-ChildItem or dir.",
    "cat": "does not exist in cmd.exe. Use Get-Content or type.",
    "rm": "does not exist in cmd.exe. Use Remove-Item or del.",
    "cp": "does not exist in cmd.exe. Use Copy-Item or copy.",
    "mv": "does not exist in cmd.exe. Use Move-Item or move.",
    "touch": "does not exist on Windows. Use New-Item.",
    "which": "does not exist in cmd.exe. Use Get-Command or where.",
    "wc": "does not exist on Windows. Use Measure-Object.",
    "df": "does not exist on Windows.",
    "du": "does not exist on Windows.",
    "chmod": "has no meaning on Windows. Use icacls if ACLs are really needed.",
    "chown": "has no meaning on Windows.",
    "ps": "does not exist in cmd.exe. Use Get-Process.",
    "kill": "does not exist in cmd.exe. Use Stop-Process or taskkill.",
    # Listed after being caught in practice, and for a subtler reason than the
    # rest: tar is not missing. Windows 10 ships bsdtar and Git Bash brings GNU
    # tar. But GNU tar treats a path containing a colon as a remote host spec, so
    # an ordinary Windows path fails with "Cannot connect to C: resolve failed",
    # and the `--force-local` that fixes GNU tar is rejected by bsdtar. There is
    # no single spelling that works on both, and every path here has a drive
    # letter.
    "tar": "GNU tar reads a colon in the archive path as a remote host, so "
    "Windows paths fail; --force-local fixes GNU tar and breaks bsdtar. Use "
    "Compress-Archive.",
}


#: Commands that DO exist on Windows but reject a POSIX switch. Checking command
#: names alone missed these -- a mutation restoring `mkdir -p` passed, because
#: mkdir is a real Windows command and only the switch is wrong.
_POSIX_SWITCHES = {
    "mkdir": {
        "-p": "cmd.exe's mkdir creates intermediate directories anyway and has "
        "no -p switch, so it creates a directory literally named '-p'. Use "
        "New-Item -ItemType Directory -Force.",
    },
    "sort": {
        "-u": "Windows sort has no -u. Use Sort-Object -Unique.",
        "-n": "Windows sort has no -n. Use Sort-Object with a numeric key.",
    },
    "more": {"-n": "Windows more uses /N. Use Select-Object -First."},
}


def shell_commands() -> list[tuple[str, str]]:
    """Every (skill name, command string) a bundled manifest would run."""
    found: list[tuple[str, str]] = []
    for path in sorted(DATA.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for step in data.get("skill", {}).get("steps", []):
            if step.get("tool_name") not in {"shell_exec", "code_interpreter"}:
                continue
            template = step.get("arguments_template", "")
            # Fill placeholders with a benign token so the JSON parses.
            arguments = json.loads(PLACEHOLDER.sub("PLACEHOLDER", template))
            command = arguments.get("command")
            if command:
                found.append((path.stem, command))
    return found


def invocations(command: str) -> list[tuple[str, list[str]]]:
    """Each (command word, its switches), split on shell operators | & ; ( )."""
    found: list[tuple[str, list[str]]] = []
    for fragment in re.split(r"[|&;()]+", command):
        parts = fragment.split()
        if not parts:
            continue
        name = Path(parts[0]).name.casefold()
        switches = [part for part in parts[1:] if part.startswith("-")]
        found.append((name, switches))
    return found


def words(command: str) -> list[str]:
    """Just the command words, for the name-based check."""
    return [name for name, _ in invocations(command)]


def test_there_are_shell_commands_to_check() -> None:
    """Guards the guard: an empty list would make the next test vacuous."""
    found = shell_commands()

    assert len(found) >= 5, found
    assert {"backup-files", "file-organizer"} <= {name for name, _ in found}


@pytest.mark.parametrize(
    ("skill", "command"), shell_commands(), ids=lambda v: str(v)[:40]
)
def test_no_bundled_skill_runs_a_posix_only_command(skill: str, command: str) -> None:
    offenders = {
        token: _DIFFERENT_ON_WINDOWS[token]
        for token in words(command)
        if token in _DIFFERENT_ON_WINDOWS
    }

    assert not offenders, (
        f"{skill} runs {sorted(offenders)} through cmd.exe.\n"
        + "\n".join(f"  {name}: {why}" for name, why in sorted(offenders.items()))
        + f"\n  command: {command}"
    )


@pytest.mark.parametrize(
    ("skill", "command"), shell_commands(), ids=lambda v: str(v)[:40]
)
def test_no_bundled_skill_passes_a_posix_switch_to_a_windows_command(
    skill: str, command: str
) -> None:
    """The gap the name check missed, found by mutating `mkdir -p` back in."""
    offenders: list[str] = []
    for name, switches in invocations(command):
        for switch in switches:
            why = _POSIX_SWITCHES.get(name, {}).get(switch)
            if why:
                offenders.append(f"  {name} {switch}: {why}")

    assert not offenders, (
        f"{skill} passes a POSIX-only switch to a Windows command.\n"
        + "\n".join(offenders)
        + f"\n  command: {command}"
    )


def test_the_clock_setting_builtins_are_named_in_the_list() -> None:
    """The one that mattered most, pinned by name.

    If someone trims this list, `date` and `time` are the two entries that must
    not go: they are the only ones that can change the machine rather than fail.
    """
    assert "date" in _DIFFERENT_ON_WINDOWS
    assert "time" in _DIFFERENT_ON_WINDOWS
    for name in ("date", "time"):
        assert "clock" in _DIFFERENT_ON_WINDOWS[name].casefold()


def test_tar_is_listed_for_the_colon_reason_not_for_being_absent() -> None:
    """tar earns its place here differently from the rest, and the reason matters.

    This test originally asserted the opposite -- that tar must NOT be listed,
    because it genuinely ships with Windows 10. That was true and beside the
    point: `tar -czf "C:\\...\\backup.zip"` failed anyway, because GNU tar reads
    the colon as a remote host. Anyone revisiting this needs the real reason, or
    they will conclude tar is fine on the grounds that it exists.
    """
    assert "tar" in _DIFFERENT_ON_WINDOWS
    why = _DIFFERENT_ON_WINDOWS["tar"].casefold()
    assert "colon" in why
    assert "does not exist" not in why
