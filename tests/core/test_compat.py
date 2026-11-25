"""The Python 3.10 StrEnum fallback behaves like the standard library's."""

from __future__ import annotations

import ast
import sys
from enum import auto
from pathlib import Path

import pytest

from grandpa.core.compat import StrEnum, _StrEnumFallback

SRC = Path(__file__).resolve().parents[2] / "src" / "grandpa"


class _Fallback(_StrEnumFallback):
    IDLE = "idle"
    SPEAKING = "speaking"


class _FallbackAuto(_StrEnumFallback):
    LOADING = auto()
    EXECUTING = auto()


def test_fallback_text_is_the_value():
    assert str(_Fallback.IDLE) == "idle"
    assert f"{_Fallback.SPEAKING}" == "speaking"
    assert f"{_Fallback.IDLE:>6}" == "  idle"


def test_fallback_compares_and_looks_up_as_its_value():
    assert _Fallback.IDLE == "idle"
    assert _Fallback("speaking") is _Fallback.SPEAKING
    assert {"idle": 1}[_Fallback.IDLE] == 1
    assert isinstance(_Fallback.IDLE, str)


def test_fallback_auto_is_lowercase_name():
    assert _FallbackAuto.LOADING.value == "loading"
    assert _FallbackAuto.EXECUTING.value == "executing"


@pytest.mark.skipif(sys.version_info < (3, 11), reason="compares against enum.StrEnum")
def test_fallback_matches_stdlib_strenum():
    from enum import StrEnum as Stdlib

    class Real(Stdlib):
        IDLE = "idle"
        LOADING = auto()

    class Fake(_StrEnumFallback):
        IDLE = "idle"
        LOADING = auto()

    for name in ("IDLE", "LOADING"):
        real, fake = Real[name], Fake[name]
        assert str(real) == str(fake)
        assert f"{real}" == f"{fake}"
        assert real.value == fake.value


def test_exported_strenum_works_on_this_interpreter():
    class State(StrEnum):
        IDLE = "idle"

    assert str(State.IDLE) == "idle"


def test_no_module_imports_strenum_from_the_standard_library():
    """Python 3.10 has no enum.StrEnum; import it from grandpa.core.compat."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "compat.py" and path.parent.name == "core":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "enum":
                if any(alias.name == "StrEnum" for alias in node.names):
                    offenders.append(str(path.relative_to(SRC)))
    assert offenders == []
