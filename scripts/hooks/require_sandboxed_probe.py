"""Refuse a python command that touches grandpa without a sandbox.

Every machine change in recent turns came from the same shape: an ad-hoc probe
script, run outside pytest, importing grandpa before ``GRANDPA_HOME`` was set,
writing into a real ``~/.grandpa``. Five files one turn; a mocked traceback
appended to a real ``server.log`` another. Each time the remedy was to remember
to set GRANDPA_HOME next time, and each time the next time came.

Arming a sandbox cannot be automatic from inside Python: a module only runs when
something imports it, and the scripts that did the damage did not. What can be
automatic is the refusal. This hook blocks the command before it runs unless the
process will be sandboxed one way or another:

* ``GRANDPA_HOME`` appears in the command, or
* the script calls ``tests.sandbox.arm()``, or
* it is ``-m pytest`` (the suite arms per test), or
* the script lives in the repository's own ``scripts/`` or ``tests/`` (those
  build their own sandboxes -- ``run_e2e.py`` and the confirmation probe both do).

Anything else importing grandpa from a scratch file is the exact shape that has
damaged this machine, so it is refused with the one line that fixes it.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_PYTHON = re.compile(r"(^|[/\\\s\"'])(python|python3|python\.exe|py)([\s\"']|$)", re.I)

_IMPORT_TEXT = re.compile(r"^\s*(?:import\s+grandpa\b|from\s+grandpa[\w.]*\s+import\b)")


def _imports_grandpa(code: str) -> bool:
    """Does this code actually import grandpa?

    Parsed, not matched. Two false positives taught this: a command that read
    ``~/.grandpa`` with sqlite3 was refused because the *path* contains the word,
    and a command that edited a source file was refused because the *replacement
    string* contained an import. Neither imports anything. An ``ast`` walk knows
    the difference between an import statement and a string that looks like one;
    a regex never will.

    Unparseable code falls back to the textual form anchored at the start, which
    is where a real ``python -c "from grandpa... "`` puts it.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return bool(_IMPORT_TEXT.match(code.strip().strip("\"'")))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "grandpa" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "grandpa":
                return True
    return False


_ARMS = re.compile(r"\barm\s*\(|from\s+tests\.sandbox\s+import|tests\.sandbox")

HINT = """\
Refusing this Bash command: it runs python against grandpa with nothing to stop
it writing outside a sandbox.

  what it runs: {what}

This exact shape has changed this machine before: a probe script imported grandpa
before GRANDPA_HOME was set, and grandpa's paths resolved to the real
~/.grandpa. Five files one turn, a real server.log another.

Pick one:

  1. Arm the guard inside the script -- one line, and writes outside a throwaway
     directory then raise loudly:

         from tests.sandbox import arm
         arm()

  2. Or point the run at a sandbox on the command line:

         GRANDPA_HOME=/some/temp/dir python your_probe.py

pytest needs neither: the suite arms per test. Scripts under the repository's own
scripts/ and tests/ are exempt, because they build their own sandboxes.\
"""


def _looks_like_python(command: str) -> bool:
    return bool(_PYTHON.search(command))


def _repo_owned(path: str) -> bool:
    """A script the repository ships, which manages its own sandbox."""
    try:
        resolved = Path(path).resolve()
    except OSError:  # pragma: no cover - a malformed path is not repo-owned
        return False
    try:
        relative = resolved.relative_to(REPO)
    except ValueError:
        return False
    return relative.parts and relative.parts[0] in {"scripts", "tests"}


def _script_targets(command: str) -> list[str]:
    """Any .py file python will *run as a script*.

    Nothing when the command is ``python -m something``: then the positional
    arguments belong to that module, not to python. ``python -m ruff check
    src/grandpa/tools/_stubs.py`` lints a file, and an earlier version of this
    read it as running one -- the third false positive this hook produced, and
    the third reason it now knows the difference between a path and a program.
    """
    if re.search(r"-m\s+\S+", command):
        return []
    return list(re.findall(r"""["']?([^\s"']+\.py)["']?""", command))


def offence(command: str) -> str | None:
    """What is unsandboxed about this command, or None if it is fine."""
    if not _looks_like_python(command):
        return None
    if "GRANDPA_HOME" in command:
        return None
    if re.search(r"-m\s+pytest\b", command):
        return None

    # Inline code: the whole command is the evidence.
    inline = re.search(r"-c\s+(.+)", command, re.S)
    if inline and _imports_grandpa(inline.group(1).strip().strip("\"'")):
        if _ARMS.search(inline.group(1)):
            return None
        return "python -c ... (inline code that reaches grandpa)"

    if re.search(r"-m\s+grandpa", command):
        return "python -m grandpa..."

    for target in _script_targets(command):
        if _repo_owned(target):
            continue
        try:
            text = Path(target).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _imports_grandpa(text):
            continue
        if _ARMS.search(text):
            continue
        return target
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    what = offence(command)
    if what is None:
        return 0
    print(HINT.format(what=what), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["offence"]
