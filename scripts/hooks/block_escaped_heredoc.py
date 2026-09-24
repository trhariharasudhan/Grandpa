"""Refuse a bash command that carries escaped file content in a heredoc.

Three files in this project have been written through a heredoc and arrived
mangled, because the backslash sequences did not survive the trip to the shell:

* ``scripts/commit_verification.py`` -- every ``\\n`` inside a Python string
  became a real newline, producing 87 syntax errors in one command;
* a scratch test-narrowing runner, the same way, in the middle of a measurement;
* earlier still, a ``\\b`` in a regex became a literal backspace (0x08), which
  did not fail loudly at all -- it silently changed what the pattern matched.

Each time the lesson was written down, and each time it was written down again a
few days later. A rule that has to be remembered at the moment of temptation is
not a rule; it is a hope. This is the mechanical version: a PreToolUse hook that
inspects every Bash command before it runs and refuses the ones that would be
mangled, naming the tool to use instead.

WHAT IT BLOCKS, AND WHY ONLY THAT

Only a backslash inside a heredoc body. That is precisely what gets mangled --
quotes travel fine, and blocking them would refuse a great many safe commands
(``python -c "print('x')"`` inside a heredoc, for one). A hook that cries wolf is
a hook that gets deleted, and then we are back to hoping. Scope it to the thing
that actually breaks.

The escape hatch is the Write tool, which sends file content as data and never
lets a shell near it. It is not slower: it is one tool call, the same as the
heredoc it replaces.
"""

from __future__ import annotations

import json
import re
import sys

# `<<EOF`, `<<'EOF'`, `<<"EOF"`, `<<-EOF`. The delimiter is captured so the body
# can be found; the quoting does not matter, because what mangles the content
# happens before bash ever sees it.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

HINT = """\
Refusing this Bash command: it writes file content through a heredoc, and the
content contains a backslash.

  heredoc delimiter: {delimiter}
  first offending line: {line}

Backslash sequences do not survive the trip into a bash heredoc in this harness.
This has silently corrupted three files in this project: an 87-syntax-error
Python module, a scratch runner, and a regex whose \\b became a literal backspace
-- the last of which did not fail loudly, it just quietly matched the wrong
thing.

Use the Write tool instead. It sends the content as data, no shell involved, and
it is one call rather than one command, so it is not slower.

If the backslash is genuinely part of a shell command and not file content --
`find . -name '*.py' -exec ... \\;` for instance -- put it in the command
directly rather than inside a heredoc.\
"""


def offending_heredoc(command: str) -> tuple[str, str] | None:
    """The delimiter and first backslash-bearing line of a mangling heredoc."""
    lines = command.splitlines()
    index = 0
    while index < len(lines):
        match = _HEREDOC.search(lines[index])
        if not match:
            index += 1
            continue
        delimiter = match.group(2)
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            if "\\" in lines[index]:
                return delimiter, lines[index].strip()[:120]
            index += 1
        index += 1
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if "<<" not in command:
        return 0
    found = offending_heredoc(command)
    if found is None:
        return 0
    delimiter, line = found
    print(HINT.format(delimiter=delimiter, line=line), file=sys.stderr)
    # Exit status 2 is what tells Claude Code to block the call and show stderr.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
