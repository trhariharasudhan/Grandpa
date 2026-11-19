"""E2: nothing depends on the optional ``grandpa_rust`` binding being built."""

from __future__ import annotations

import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

from grandpa import _rust_bridge

SRC = Path(__file__).resolve().parents[2] / "src" / "grandpa"

#: Every module that consults the binding.
CALLERS = [
    "grandpa.agents.loop_guard",
    "grandpa.security.capabilities",
    "grandpa.security.file_policy",
    "grandpa.security.injection_scanner",
    "grandpa.security.scanner",
    "grandpa.security.ssrf",
    "grandpa.tools.calculator",
    "grandpa.tools.file_read",
    "grandpa.tools.file_write",
    "grandpa.tools.git_tool",
    "grandpa.tools.http_request",
    "grandpa.tools.storage.bm25",
    "grandpa.tools.storage.sqlite",
    "grandpa.tools.think",
]


@pytest.fixture
def no_rust(monkeypatch: pytest.MonkeyPatch):
    """Make ``import grandpa_rust`` fail, as on a default install."""
    monkeypatch.setitem(sys.modules, "grandpa_rust", None)
    _rust_bridge.get_rust_module.cache_clear()
    yield
    _rust_bridge.get_rust_module.cache_clear()


def test_every_caller_imports_without_the_binding(
    no_rust, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fresh imports (the originals are put back afterwards), so a module that
    # touches the binding at import time fails here.
    for name in CALLERS:
        if name in sys.modules:
            monkeypatch.delitem(sys.modules, name)
            parent, _, child = name.rpartition(".")
            package = sys.modules.get(parent)
            if package is not None and hasattr(package, child):
                # Put the package attribute back too, or later imports of
                # ``a.b.c`` would get the throwaway module.
                monkeypatch.setattr(package, child, getattr(package, child))
    for name in CALLERS:
        importlib.import_module(name)


def test_caller_list_is_complete() -> None:
    """A new caller has to be added above, so it is covered by the import test."""
    found = set()
    for path in SRC.rglob("*.py"):
        if path.name == "_rust_bridge.py":
            continue
        if "get_rust_module" in path.read_text(encoding="utf-8"):
            rel = path.relative_to(SRC.parent).with_suffix("")
            found.add(".".join(rel.parts))
    assert found <= set(CALLERS), sorted(found - set(CALLERS))


def test_no_module_calls_the_binding_at_import() -> None:
    """``get_rust_module()`` at module level breaks the import without Rust."""
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            for call in ast.walk(node):
                if (
                    not isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    )
                    and isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "get_rust_module"
                ):
                    offenders.append(f"{path.relative_to(SRC)}:{call.lineno}")
    assert not offenders, offenders


def test_bm25_works_in_python(no_rust) -> None:
    from grandpa.tools.storage import bm25

    memory = bm25.BM25Memory()
    assert isinstance(memory._rust_impl, bm25._PythonBM25)
    memory.store("Python is a programming language.", source="wiki")
    memory.store("The weather is sunny today", source="diary")
    memory.store("cooking recipes for dinner", metadata={"k": 1})
    results = memory.retrieve("programming LANGUAGE")
    assert [r.source for r in results] == ["wiki"]
    assert results[0].score > 0
    assert memory.retrieve("dinner")[0].metadata == {"k": 1}
    assert memory.count() == 3


def test_bm25_prefers_rust_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("grandpa_rust")
    fake.BM25Memory = lambda: "rust-impl"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "grandpa_rust", fake)
    _rust_bridge.get_rust_module.cache_clear()
    try:
        from grandpa.tools.storage import bm25

        assert bm25.BM25Memory()._rust_impl == "rust-impl"
        assert _rust_bridge.rust_status()[0] is True
    finally:
        _rust_bridge.get_rust_module.cache_clear()


def test_python_scores_match_the_rust_formula() -> None:
    from grandpa.tools.storage.bm25 import _PythonBM25

    impl = _PythonBM25()
    impl.store("apple banana", "a", None)
    impl.store("apple apple cherry date", "b", None)
    import json
    import math

    results = json.loads(impl.retrieve("banana", 5))
    n, df, tf, dl, avg = 2.0, 1.0, 1.0, 2.0, 3.0
    idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
    expected = idf * (tf * 2.2) / (tf + 1.2 * (1 - 0.75 + 0.75 * dl / avg))
    assert results[0]["source"] == "a"
    assert results[0]["score"] == pytest.approx(expected)


def test_status_and_doctor_without_binding(no_rust) -> None:
    from grandpa.cli.doctor_cmd import _check_rust_bridge

    active, message = _rust_bridge.rust_status()
    assert active is False and "pure-Python fallback" in message
    result = _check_rust_bridge()
    assert result.status == "ok" and "fallback" in result.message
    assert _rust_bridge.optimization_store_from_rust() is None
