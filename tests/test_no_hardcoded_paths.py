"""No absolute drive-letter path belongs in shipped code.

``agent/runtime.py`` defaulted a project's location to the literal string
``"D:\\Grandpa"`` -- one developer's drive, shipped, with a fallback to the
working directory only when that path did not exist. On that developer's machine
it did exist, so the runtime wrote project state there from whatever directory it
ran in, and on anyone else's machine with a ``D:\\Grandpa`` folder it would have
written into theirs.

Fixing that one found four. Looking properly found twenty-two, in the agent
runtime, the CLI commands, the planner, the memory service and the developer
helpers -- because each was added the same way, by someone with that folder on
their machine, and nothing ever said no.

This says no. A path the user's own machine decides belongs in configuration,
in ``GRANDPA_HOME``, or in ``Path.cwd()``; never in a string literal.

WHAT IS ALLOWED, AND WHY

Windows system locations, and only for the two honest reasons: refusing access
to them (``c:\\windows``, ``c:\\program files``) and finding software actually
installed there (Tesseract's install path). Those are properties of the
operating system rather than of anybody's checkout, so they are allowed by
prefix and listed here where a reader can weigh them.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "grandpa"

pytestmark = pytest.mark.core

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:[\\/]")
_REGEX_METACHARACTER = re.compile(r"[\[\]()*+^$?|]")

ALLOWED_PREFIXES = (
    # Refused, not used: the protected-path checks that keep the product out of
    # the operating system's own directories.
    "c:\\windows",
    "c:/windows",
    "c:\\program files",
    "c:/program files",
    "c:\\programdata",
    "c:/programdata",
)
"""Absolute paths that are the operating system's, not a developer's.

A prefix list rather than a list of exact strings, so that
``C:\\Program Files\\Tesseract-OCR\\tesseract.exe`` -- where the OCR backend
actually installs itself -- is covered without enumerating every executable.
"""


def _is_allowed(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _string_literals(tree: ast.AST):
    """Every string constant, including docstrings, with its line number."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def hardcoded_paths(root: Path) -> list[tuple[str, int, str]]:
    """Drive-letter absolute paths written into the source, as (file, line, text).

    Only string *literals*: a regex that matches a drive letter is not a path.
    ``memory/intent.py`` holds ``r"([a-zA-Z]:\\\\[^\\s]+)"``, whose job is to find
    a path in something a user typed, and which must not be flagged.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):  # pragma: no cover - unreadable file
            continue
        for lineno, value in _string_literals(tree):
            candidate = value.strip()
            # Anchored at the start of the literal, because a path literal is a
            # whole string. Searching anywhere inside one matched "s://" out of
            # "https://", "e://" out of "chrome://history", and "T:\\s*" out of
            # the regex "THOUGHT:\\s*(.+?)" -- 151 hits, almost none of them
            # paths. A drive letter in the middle of a sentence is prose.
            if not _DRIVE_LETTER.match(candidate):
                continue
            if _is_allowed(candidate):
                continue
            if _REGEX_METACHARACTER.search(candidate):
                # "[a-zA-Z]:\\[^\\s]+" is a pattern for finding a path, not one.
                continue
            found.append(
                (
                    path.relative_to(root.parent.parent).as_posix(),
                    lineno,
                    candidate.splitlines()[0][:80],
                )
            )
    return found


def test_no_hardcoded_absolute_path_ships() -> None:
    """The fifth one cannot be added quietly."""
    offenders = hardcoded_paths(SRC)

    rendered = "\n".join(
        f"  {where}:{line}  {text}" for where, line, text in offenders
    )
    assert not offenders, (
        "Absolute drive-letter paths in shipped code:\n"
        f"{rendered}\n\n"
        "A location that belongs to whoever is running this comes from "
        "configuration, GRANDPA_HOME, or Path.cwd(). If it is genuinely an "
        "operating-system path -- one that is the same on every Windows machine "
        "-- add its prefix to ALLOWED_PREFIXES in this file, with the reason."
    )


def test_the_scanner_sees_a_planted_path(tmp_path: Path) -> None:
    """Otherwise a broken scanner would read as a clean repository."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        'ROOT = "D:/SomeonesCheckout"\n', encoding="utf-8"
    )

    found = hardcoded_paths(package)

    assert [text for _, _, text in found] == ["D:/SomeonesCheckout"]


def test_a_regex_that_matches_a_drive_letter_is_not_a_path(tmp_path: Path) -> None:
    """memory/intent.py must stay legal: its pattern finds paths, it is not one."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        'PATTERN = r"([a-zA-Z]:\\\\[^\\s]+)"\n', encoding="utf-8"
    )

    assert hardcoded_paths(package) == []


def test_operating_system_paths_are_allowed(tmp_path: Path) -> None:
    """Refusing access to c:\\windows requires naming it."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        'PROTECTED = ("c:\\\\windows", "c:\\\\program files")\n'
        'TESSERACT = "C:/Program Files/Tesseract-OCR/tesseract.exe"\n',
        encoding="utf-8",
    )

    assert hardcoded_paths(package) == []
