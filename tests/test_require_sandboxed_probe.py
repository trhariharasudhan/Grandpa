"""The hook that refuses an unsandboxed probe.

The cases below are the commands that actually damaged this machine, and the
commands that must keep working. A hook that blocks the second kind is a hook
somebody switches off, which is how the write guard came to exist only inside
pytest in the first place.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "hooks"
    / "require_sandboxed_probe.py"
)
sys.path.insert(0, str(HOOK.parent))

from require_sandboxed_probe import offence  # noqa: E402

pytestmark = pytest.mark.core

PY = "D:/Grandpa/.venv/Scripts/python.exe"


# --- what must be refused ----------------------------------------------------


def test_inline_code_reaching_grandpa_is_refused() -> None:
    """The shape that wrote five files: a one-liner importing grandpa."""
    command = f'{PY} -c "from grandpa.core.registry import ToolRegistry; print(1)"'

    assert offence(command) is not None


def test_running_the_cli_as_a_module_is_refused() -> None:
    assert offence(f"{PY} -m grandpa.cli --quiet reminders list") is not None


def test_a_scratch_script_that_imports_grandpa_is_refused(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from grandpa.connectors.store import KnowledgeStore\nKnowledgeStore()\n",
        encoding="utf-8",
    )

    assert offence(f'{PY} "{probe}"') == str(probe)


# --- what must keep working --------------------------------------------------


def test_the_same_script_is_allowed_once_it_arms() -> None:
    """Option one from the hook's own message."""
    command = f'{PY} -c "from tests.sandbox import arm; arm(); import grandpa"'

    assert offence(command) is None


def test_setting_grandpa_home_on_the_command_line_is_allowed() -> None:
    """Option two."""
    command = f'GRANDPA_HOME=/tmp/x {PY} -c "import grandpa; print(1)"'

    assert offence(command) is None


def test_pytest_is_allowed() -> None:
    """The suite arms per test; blocking it would block all verification."""
    assert offence(f"{PY} -m pytest tests/skills -q") is None


@pytest.mark.parametrize(
    "script",
    ["scripts/run_e2e.py", "scripts/verify_confirmation_enforcement.py"],
)
def test_the_repositorys_own_scripts_are_allowed(script: str) -> None:
    """Both build their own sandboxes; that is what they are for."""
    path = Path(__file__).resolve().parents[1] / script

    assert offence(f'{PY} "{path}"') is None


def test_a_scratch_script_that_arms_is_allowed(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from tests.sandbox import arm\n\narm()\nimport grandpa  # noqa: E402\n",
        encoding="utf-8",
    )

    assert offence(f'{PY} "{probe}"') is None


def test_a_script_that_never_touches_grandpa_is_allowed(tmp_path: Path) -> None:
    """Most scratch scripts only read files; they are nobody's business."""
    probe = tmp_path / "count.py"
    probe.write_text("print(len(open(__file__).read()))\n", encoding="utf-8")

    assert offence(f'{PY} "{probe}"') is None


def test_commands_that_are_not_python_are_ignored() -> None:
    for command in ("git status --short", "ls -la", "grep -rn grandpa src/"):
        assert offence(command) is None, command


def test_ruff_is_allowed() -> None:
    """It mentions the package in its paths and writes only source formatting."""
    assert offence(f"{PY} -m ruff check src/grandpa/") is None


@pytest.mark.parametrize(
    "command",
    [
        "-m ruff check src/grandpa/tools/_stubs.py",
        "-m ruff format src/grandpa/cli/chat_cmd.py",
        "-m pytest tests/tools/test_llm_tool.py -q",
        "-m mypy src/grandpa/pc_control.py",
    ],
)
def test_a_py_file_given_to_a_module_is_not_a_script(command: str) -> None:
    """The third false positive, pinned.

    ``python -m ruff check some_file.py`` hands the file to ruff. Reading it as a
    script python will run refused every lint of a source file that imports
    grandpa -- which is most of them.
    """
    assert offence(f"{PY} {command}") is None


def test_inspecting_the_real_home_is_not_blocked() -> None:
    """The first false positive this hook produced, pinned.

    The pattern was any mention of the word, and ``~/.grandpa`` contains it -- so
    a command that read the home directory with sqlite3, importing nothing, was
    refused. A guard that blocks reading the thing it protects gets switched off
    within the hour, and then nothing guards anything.
    """
    command = (
        f'{PY} -c "import sqlite3, pathlib; '
        "p = pathlib.Path.home() / '.grandpa' / 'knowledge.db'; "
        'print(sqlite3.connect(p))"'
    )

    assert offence(command) is None


def test_editing_a_file_that_contains_an_import_is_not_blocked() -> None:
    """The second false positive, pinned.

    Adding an import line to a source file with a one-liner puts the text of an
    import inside a string. The command imports nothing; the string it writes
    does. Only parsing can tell those apart, which is why this hook parses.
    """
    command = (
        f"{PY} -c \"import pathlib; p = pathlib.Path('x.py'); "
        "s = p.read_text(); "
        "p.write_text(s.replace('a', 'from grandpa.tools import x'))\""
    )

    assert offence(command) is None


def test_a_path_mentioning_the_word_in_a_file_is_not_blocked(tmp_path: Path) -> None:
    probe = tmp_path / "inspect.py"
    probe.write_text(
        "import pathlib\nprint(pathlib.Path.home() / '.grandpa' / 'config.toml')\n",
        encoding="utf-8",
    )

    assert offence(f'{PY} "{probe}"') is None
