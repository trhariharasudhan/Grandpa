"""No module-level constant may resolve a filesystem path when it is imported.

``grandpa/knowledge/storage.py`` held::

    DEFAULT_KNOWLEDGE_DIR = runtime_path("knowledge")

which runs at import. ``runtime_path`` reads ``GRANDPA_HOME``, so the value was
decided by whatever the environment happened to be at the moment some other
module imported this one -- and a script that imported grandpa before setting
``GRANDPA_HOME`` got the developer's real home. That is how five files under a
real ``~/.grandpa`` were written by a diagnostic script that never meant to
touch them.

It is the same defect as a config default computed at import: a path decided
before anyone could configure it. The fix is always the same shape -- a function
called when the path is needed, not a constant bound when the module loads.

WHAT COUNTS

A module-level assignment whose value calls something that reads the
environment or the user's identity to produce a path: ``Path.home()``,
``Path.cwd()``, ``os.getcwd``, ``expanduser``, ``tempfile.gettempdir``, or this
project's own ``grandpa_home``/``runtime_dir``/``runtime_path``. A literal like
``Path("runtime")`` is fine: it is relative, resolves nothing, and cannot point
at somebody's home.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "grandpa"

pytestmark = pytest.mark.core

RESOLVING_CALLS = {
    # This project's own, all of which read GRANDPA_HOME.
    "grandpa_home",
    "runtime_dir",
    "runtime_path",
    "legacy_state",
    # The standard library's ways of asking where the user lives.
    "home",
    "cwd",
    "getcwd",
    "expanduser",
    "expandvars",
    "gettempdir",
    "mkdtemp",
}

ALLOWED: dict[str, set[str]] = {
    # The root of all the others, and the one not converted. It has 153 usage
    # sites, 56 of them default arguments whose signatures would have to change
    # -- a refactor larger than every other fix in this file put together, and
    # one that touches the audit log, the session store and the credentials
    # path. It is also the least dangerous of the eight: `grandpa_home()` reads
    # GRANDPA_HOME on every call and only falls back to this, so a late
    # GRANDPA_HOME is honoured by everything that goes through the runtime
    # paths. What remains is a module that does `from grandpa.core.config
    # import DEFAULT_CONFIG_DIR` and uses it directly; 59 modules do.
    #
    # Left deliberately, not overlooked. Converting it is its own task.
    "src/grandpa/core/config.py": {"DEFAULT_CONFIG_DIR"},
}


def _call_names(node: ast.AST) -> set[str]:
    """Every function name called anywhere inside this expression."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def import_time_paths(root: Path) -> list[tuple[str, int, str, str]]:
    """Module-level assignments that resolve a path at import.

    Returns ``(file, line, name, the call that resolves)``.
    """
    found: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):  # pragma: no cover - unreadable file
            continue
        relative = path.relative_to(root.parent.parent).as_posix()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
                value = node.value
            else:
                continue
            if value is None or not targets:
                continue
            resolving = _call_names(value) & RESOLVING_CALLS
            if not resolving:
                continue
            for name in targets:
                if name in ALLOWED.get(relative, set()):
                    continue
                found.append((relative, node.lineno, name, sorted(resolving)[0]))
    return found


def test_no_module_level_constant_resolves_a_path() -> None:
    offenders = import_time_paths(SRC)

    rendered = "\n".join(
        f"  {where}:{line}  {name} = ...{call}(...)"
        for where, line, name, call in offenders
    )
    assert not offenders, (
        "These resolve a path when the module is imported:\n"
        f"{rendered}\n\n"
        "The value is then whatever the environment was at import, which is "
        "decided by somebody else's import order. Make it a function that "
        "resolves when the path is used."
    )


def test_the_scanner_sees_a_planted_constant(tmp_path: Path) -> None:
    """A scanner that finds nothing and a clean repository look identical."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        "from pathlib import Path\nDEFAULT_DIR = Path.home() / '.thing'\n",
        encoding="utf-8",
    )

    found = import_time_paths(package)

    assert [(name, call) for _, _, name, call in found] == [("DEFAULT_DIR", "home")]


def test_it_sees_this_projects_own_helpers(tmp_path: Path) -> None:
    """``runtime_path("knowledge")`` is the one that actually bit."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        "from grandpa.runtime_paths import runtime_path\n"
        'DEFAULT_KNOWLEDGE_DIR = runtime_path("knowledge")\n',
        encoding="utf-8",
    )

    found = import_time_paths(package)

    assert [name for _, _, name, _ in found] == ["DEFAULT_KNOWLEDGE_DIR"]


def test_a_relative_literal_is_not_a_resolution(tmp_path: Path) -> None:
    """``Path("runtime")`` points nowhere until something joins it to a root."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        'from pathlib import Path\nLEGACY = Path("runtime")\nNAME = "knowledge.db"\n',
        encoding="utf-8",
    )

    assert import_time_paths(package) == []


def test_a_function_that_resolves_when_called_is_fine(tmp_path: Path) -> None:
    """The shape every fix takes: inside a def, not at module level."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(
        "from pathlib import Path\n\n\ndef default_dir() -> Path:\n"
        "    return Path.home() / '.thing'\n",
        encoding="utf-8",
    )

    assert import_time_paths(package) == []
