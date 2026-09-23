"""An empty allowed_dirs means nothing is allowed, not everything.

``file_read`` and ``file_write`` each guarded paths like this::

    if not self._allowed_dirs:
        return True

and nothing ever passed a list -- ``ToolRegistry.create("file_write")`` builds
the tool with no arguments. So the guard was inert in every configuration
Grandpa actually runs in, and ``file_write`` could write any path on the disk.
That included ``~/.grandpa/skills/``, where a manifest is deferred execution:
the tool that is *supposed* to write manifests is confirmation-gated, and this
one wrote to the same directory without being gated at all.

The default is inverted now. Unconfigured means "the file domain's roots",
which is the policy ``grandpa.files`` already applies to the user's own file
actions rather than a second opinion invented for tools; an explicitly empty
list means nowhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from grandpa.tools.file_read import FileReadTool
from grandpa.tools.file_write import FileWriteTool

# The *shapes* the guard refuses, built under a throwaway directory rather than
# against the real ones.
#
# These used to be Path.home() / ".ssh" / "authorized_keys" and friends, on the
# reasoning that a test asserting a refusal never writes anything. That is true
# only while the guard works -- and this file exists to be run with the guard
# deliberately removed, to prove the refusal is real. The first mutation run
# duly wrote "x" over a real ~/.ssh/authorized_keys and a real
# ~/.grandpa/config.toml.
#
# FileSafetyPolicy.is_protected matches on path *parts*, so ".ssh", ".grandpa"
# and "system32" are protected wherever they sit. Every shape below is
# therefore tested exactly, and the worst a broken guard can now do is write
# inside tmp_path.
PROTECTED_SHAPES = [
    ("windows/system32/grandpa_probe.dll", "a system directory"),
    (".ssh/authorized_keys", "a credential store"),
    (".grandpa/config.toml", "Grandpa's own configuration"),
    (".grandpa/skills/written_by_a_model.toml", "a manifest"),
]


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A directory that is inside the tool's scope, so only the carve-outs bite."""
    for relative, _ in PROTECTED_SHAPES:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.mark.parametrize("relative,why", PROTECTED_SHAPES)
def test_the_write_that_used_to_succeed_is_refused(
    sandbox: Path, monkeypatch, relative: str, why: str
) -> None:
    monkeypatch.setenv("GRANDPA_FILE_SAFE_ROOTS", str(sandbox))
    target = sandbox / relative

    result = FileWriteTool().execute(path=str(target), content="x")

    assert result.success is False, f"still writes to {why}"
    assert "Access denied" in result.content
    assert not target.exists(), f"a file was created at {why}"


@pytest.mark.parametrize("relative,why", PROTECTED_SHAPES)
def test_the_same_paths_are_refused_for_reading(
    sandbox: Path, monkeypatch, relative: str, why: str
) -> None:
    monkeypatch.setenv("GRANDPA_FILE_SAFE_ROOTS", str(sandbox))
    target = sandbox / relative
    target.write_text("secret", encoding="utf-8")

    result = FileReadTool().execute(path=str(target))

    assert result.success is False, f"still reads {why}"
    assert "Access denied" in result.content
    assert "secret" not in result.content


def test_the_guard_refuses_outside_the_scope_entirely(tmp_path: Path) -> None:
    """The other half: not a carve-out, simply not in the allowed roots."""
    outside = tmp_path / "somewhere_else.txt"

    result = FileWriteTool(allowed_dirs=[str(tmp_path / "only_here")]).execute(
        path=str(outside), content="x"
    )

    assert result.success is False
    assert "outside the allowed directories" in result.content
    assert not outside.exists()


def test_an_empty_list_allows_nothing(tmp_path: Path, monkeypatch) -> None:
    """The inversion, stated directly.

    This is the property the whole change turns on: the absence of a permission
    is not a permission. The target is inside the default scope, so only the
    empty list can be refusing it -- and it is under tmp_path, so a mutation
    that puts the fail-open back writes there rather than into the repository.
    """
    monkeypatch.setenv("GRANDPA_FILE_SAFE_ROOTS", str(tmp_path))
    inside_the_default_scope = tmp_path / "would_be_allowed_by_default.txt"

    refused = FileWriteTool(allowed_dirs=[]).execute(
        path=str(inside_the_default_scope), content="x"
    )

    assert refused.success is False
    assert "none are allowed" in refused.content
    assert not inside_the_default_scope.exists()


def test_an_explicit_list_still_means_that_list(tmp_path: Path) -> None:
    tool = FileWriteTool(allowed_dirs=[str(tmp_path)])

    allowed = tool.execute(path=str(tmp_path / "ok.txt"), content="hello")
    outside = tool.execute(path=str(tmp_path.parent / "no.txt"), content="hello")

    assert allowed.success is True
    assert outside.success is False
    assert not (tmp_path.parent / "no.txt").exists()


def test_the_ordinary_case_still_works(tmp_path: Path, monkeypatch) -> None:
    """A bounded tool that refuses everything would be a different bug."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "notes.txt"

    written = FileWriteTool().execute(path=str(target), content="hello")
    read_back = FileReadTool().execute(path=str(target))

    assert written.success is True, written.content
    assert read_back.success is True
    assert "hello" in read_back.content


def test_the_scope_is_the_file_domains_own(monkeypatch, tmp_path: Path) -> None:
    """Not a second policy. It is what grandpa.files already searches."""
    from grandpa.files.paths import safe_roots
    from grandpa.tools._file_scope import default_scope

    monkeypatch.setenv("GRANDPA_FILE_SAFE_ROOTS", str(tmp_path))

    assert default_scope() == safe_roots()
    assert tmp_path.resolve() in default_scope(), (
        "the scope is read at call time, so configuration still reaches it"
    )


def test_the_guard_is_not_fooled_by_traversal(tmp_path: Path) -> None:
    escape = tmp_path / "sub" / ".." / ".." / "escaped.txt"

    result = FileWriteTool(allowed_dirs=[str(tmp_path / "sub")]).execute(
        path=str(escape), content="x"
    )

    assert result.success is False
    assert not Path(os.path.normpath(escape)).exists()
