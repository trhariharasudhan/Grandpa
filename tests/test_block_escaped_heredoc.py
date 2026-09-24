"""The hook that refuses a heredoc carrying escaped file content.

Three files in this project arrived mangled through a heredoc, and each time the
remedy recorded was "remember not to". This is the version that does not depend
on remembering: a PreToolUse hook that blocks the command before it runs.

These tests are the hook's own: they check it catches the shapes that actually
corrupted files here, and -- as importantly -- that it stays quiet for the safe
ones. A hook that refuses too much gets removed, and then nothing guards this at
all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "hooks"
    / "block_escaped_heredoc.py"
)

sys.path.insert(0, str(HOOK.parent))

from block_escaped_heredoc import offending_heredoc  # noqa: E402

pytestmark = pytest.mark.core


# The three real cases, as the command that would have produced them.
COMMIT_VERIFICATION = (
    "cd /repo && python - <<'PYEOF'\n"
    "import pathlib\n"
    'text = text.replace("a", "names = \\"\\".join(f\\"\\\\n      {name}\\")")\n'
    "PYEOF"
)
SKILL_RUNNER = (
    "cat >> runner.py <<'PYEOF'\nPYPROJECT = '[project]\\nname = \"probe\"\\n'\nPYEOF"
)
REGEX_BACKSPACE = (
    "python - <<'EOF'\npattern = r\"(?i)\\b(every\\s+(day|week))\\b\"\nEOF"
)


@pytest.mark.parametrize(
    "command",
    [COMMIT_VERIFICATION, SKILL_RUNNER, REGEX_BACKSPACE],
    ids=["commit_verification", "skill_runner", "regex_backspace"],
)
def test_it_catches_each_file_this_actually_corrupted(command: str) -> None:
    found = offending_heredoc(command)

    assert found is not None, "this exact shape has corrupted a file here before"
    delimiter, line = found
    assert delimiter in {"PYEOF", "EOF"}
    assert "\\" in line


SAFE = [
    ("no heredoc at all", "ls -la && grep -n 'foo' file.py"),
    ("heredoc without escapes", "cat > f.txt <<EOF\nplain text here\nEOF"),
    (
        "backslash in the command, not the heredoc body",
        "find . -name '*.py' -exec wc -l {} \\; && cat > f.txt <<EOF\nplain\nEOF",
    ),
    ("heredoc body with quotes but no backslash", "cat > f.py <<'PY'\nprint('hi')\nPY"),
    (
        "closing delimiter reached before a later backslash",
        "cat > f.txt <<EOF\nplain\nEOF\necho done\\n",
    ),
]


@pytest.mark.parametrize("label,command", SAFE, ids=[label for label, _ in SAFE])
def test_it_stays_quiet_for_safe_commands(label: str, command: str) -> None:
    """A guard that cries wolf is one somebody switches off."""
    assert offending_heredoc(command) is None, label


@pytest.mark.real_actions(
    reason="runs the hook as the harness runs it, in a subprocess reading JSON on "
    "stdin, because the exit status is the whole contract; writes nothing"
)
def test_the_hook_exits_2_so_the_call_is_blocked() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": SKILL_RUNNER},
    }

    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert "Write tool" in proc.stderr
    assert "PYEOF" in proc.stderr


@pytest.mark.real_actions(
    reason="runs the hook in a subprocess to check it allows a safe command; "
    "writes nothing"
)
def test_the_hook_exits_0_for_a_safe_command() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello && ls"},
    }

    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, (proc.returncode, proc.stderr)


@pytest.mark.real_actions(
    reason="runs the hook against a non-Bash tool payload in a subprocess; "
    "writes nothing"
)
def test_it_ignores_tools_that_are_not_bash() -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "x", "content": "a\\nb"},
    }

    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr


@pytest.mark.real_actions(
    reason="runs the hook in a subprocess with junk on stdin to check it fails "
    "open; writes nothing"
)
def test_malformed_input_never_breaks_the_session() -> None:
    """A hook runs before every Bash call; it must fail open on nonsense."""
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json at all",
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr


def test_the_hook_is_wired_into_the_projects_settings() -> None:
    """The script alone guards nothing; the settings file is what runs it."""
    settings_path = HOOK.resolve().parents[2] / ".claude" / "settings.json"

    assert settings_path.exists(), (
        ".claude/settings.json is missing, so the hook is not installed. It is "
        "un-ignored in .gitignore precisely so it travels with the repository."
    )
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    matchers = settings.get("hooks", {}).get("PreToolUse", [])
    commands = [
        entry.get("command", "")
        for matcher in matchers
        if matcher.get("matcher") == "Bash"
        for entry in matcher.get("hooks", [])
    ]
    assert any("block_escaped_heredoc.py" in command for command in commands), settings
