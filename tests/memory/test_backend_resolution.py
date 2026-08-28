"""Backend construction contract for ``MemoryRegistry.create()``.

``RegistryBase.create()`` is a bare passthrough — ``entry(*args, **kwargs)`` —
and ``MemoryBackend`` declares no ``__init__``, so nothing in the type system
constrains how a backend is constructed.  Each caller therefore has to agree
with each backend class by hand, and they did not: ``system/builder.py`` and
``cli/serve.py`` passed ``db_path`` to *every* backend, which only ``sqlite``
accepts.  For ``dense`` that raised ``TypeError``, and because both call sites
wrap construction in ``except Exception`` the result was memory being silently
disabled rather than an error anyone could see.

These tests exercise the real production call paths.  They deliberately do not
patch ``_resolve_memory`` or the serve memory block out — mocking the layer the
defect lives in is what kept it invisible.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from grandpa.core.config import load_config
from grandpa.core.registry import MemoryRegistry
from grandpa.tools.storage import load_storage_backends


@pytest.fixture(autouse=True)
def _backends_registered():
    """Re-register the built-in backends after conftest clears the registry.

    ``conftest._clean_registries`` empties ``MemoryRegistry`` before every
    test, and ``load_storage_backends()`` is memoised via ``_backends_loaded``
    — once it has run, the modules are already in ``sys.modules`` so the
    ``@MemoryRegistry.register`` decorators never fire again.  The other memory
    suites re-register explicitly for the same reason.
    """
    from grandpa.tools.storage.dense import DenseMemory
    from grandpa.tools.storage.hybrid import HybridMemory
    from grandpa.tools.storage.sqlite import SQLiteMemory

    load_storage_backends()
    MemoryRegistry.register_or_replace("sqlite", SQLiteMemory)
    MemoryRegistry.register_or_replace("dense", DenseMemory)
    MemoryRegistry.register_or_replace("hybrid", HybridMemory)


def _spy_on_create():
    """Return ``(calls, patcher)`` recording every MemoryRegistry.create call.

    The real constructor still runs — this records arguments, it does not
    replace the code under test.
    """
    calls: list[tuple[str, dict]] = []
    real = MemoryRegistry.create.__func__

    def spy(cls, key, *args, **kwargs):
        calls.append((key, dict(kwargs)))
        return real(cls, key, *args, **kwargs)

    return calls, patch.object(MemoryRegistry, "create", classmethod(spy))


# ---------------------------------------------------------------------------
# Registry construction contract
# ---------------------------------------------------------------------------


class TestRegistryConstruction:
    def test_create_sqlite_works(self, tmp_path):
        backend = MemoryRegistry.create(
            "sqlite",
            db_path=str(tmp_path / "m.db"),
        )
        assert backend.backend_id == "sqlite"

    def test_create_dense_works(self):
        """``dense`` takes no db_path; construction is lazy (no Ollama needed)."""
        backend = MemoryRegistry.create("dense")
        assert backend.backend_id == "dense"

    def test_create_dense_rejects_db_path(self, tmp_path):
        """Pins why the call sites must not pass db_path universally."""
        with pytest.raises(TypeError):
            MemoryRegistry.create("dense", db_path=str(tmp_path / "m.db"))

    def test_create_hybrid_still_requires_injection(self):
        """Known gap: ``hybrid`` is registered but is not zero-arg constructible.

        ``HybridMemory`` needs a sparse and a dense peer, which a config string
        cannot express.  Whether a composite backend belongs in the registry at
        all is an open architecture decision; this test pins the current
        behaviour so the gap is not mistaken for a regression.
        """
        with pytest.raises(TypeError):
            MemoryRegistry.create("hybrid")

    def test_explicit_hybrid_injection_still_works(self, tmp_path):
        """Existing callers that inject both peers are unaffected."""
        from grandpa.tools.storage.dense import DenseMemory
        from grandpa.tools.storage.hybrid import HybridMemory
        from grandpa.tools.storage.sqlite import SQLiteMemory

        hybrid = HybridMemory(
            sparse=SQLiteMemory(db_path=str(tmp_path / "m.db")),
            dense=DenseMemory(),
        )
        assert hybrid.backend_id == "hybrid"


# ---------------------------------------------------------------------------
# system/builder.py — SystemBuilder._resolve_memory
# ---------------------------------------------------------------------------


class TestBuilderBackendResolution:
    def _builder(self):
        from grandpa.system.builder import SystemBuilder

        return SystemBuilder.__new__(SystemBuilder)

    def test_sqlite_receives_configured_db_path(self, tmp_path):
        config = load_config()
        config.memory.default_backend = "sqlite"
        config.memory.db_path = str(tmp_path / "custom.db")

        calls, patcher = _spy_on_create()
        with patcher:
            backend = self._builder()._resolve_memory(config)

        assert calls == [("sqlite", {"db_path": str(tmp_path / "custom.db")})]
        assert backend is not None
        assert backend._db_path == str(tmp_path / "custom.db")

    def test_non_sqlite_backend_receives_no_db_path(self, tmp_path):
        config = load_config()
        config.memory.default_backend = "dense"
        config.memory.db_path = str(tmp_path / "custom.db")

        calls, patcher = _spy_on_create()
        with patcher:
            backend = self._builder()._resolve_memory(config)

        assert calls == [("dense", {})]
        # Previously db_path raised TypeError here and the except clause
        # turned that into a silent None — memory disabled without a word.
        assert backend is not None
        assert backend.backend_id == "dense"


# ---------------------------------------------------------------------------
# cli/serve.py — the inline memory block
# ---------------------------------------------------------------------------


_SERVE_PROBE = r"""
import contextlib, json, sys
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from grandpa.core.config import load_config
from grandpa.core.registry import MemoryRegistry
from grandpa.tools.storage import load_storage_backends

backend_key, db_path = sys.argv[1], sys.argv[2]
load_storage_backends()

config = load_config()
config.agent.context_from_memory = True
config.memory.default_backend = backend_key
config.memory.db_path = db_path
# Pin the model so resolution does not depend on what discovery finds.
config.server.model = "stub-model"
# Dead host: if anything still reaches for a live engine, fail fast and
# loudly rather than quietly succeeding because the dev box runs Ollama.
config.engine.ollama.host = "http://127.0.0.1:59999"

calls = []
real = MemoryRegistry.create.__func__


def spy(cls, key, *args, **kwargs):
    calls.append([key, dict(kwargs)])
    return real(cls, key, *args, **kwargs)


from grandpa.cli.serve import serve  # noqa: E402

# get_engine() probes engine.health() over the network and returns None when
# nothing answers, at which point serve exits(1) long before the memory block
# this test is about.  Stub engine discovery so the memory-resolution path is
# reached deterministically; everything under test still runs for real.
patches = [
    patch("uvicorn.run"),
    patch("grandpa.cli.serve.load_config", return_value=config),
    patch("grandpa.cli.serve.get_engine", return_value=("stub", MagicMock())),
    patch("grandpa.cli.serve.discover_engines", return_value={}),
    patch("grandpa.cli.serve.discover_models", return_value={}),
    patch.object(MemoryRegistry, "create", classmethod(spy)),
]
with contextlib.ExitStack() as stack:
    for p in patches:
        stack.enter_context(p)
    result = CliRunner().invoke(serve, ["--no-auth"], catch_exceptions=True)

# Emitted ahead of the marker so that if serve ever stops early again, the
# failure text says why instead of only that no backend was constructed.
print("__EXIT__" + json.dumps([result.exit_code, repr(result.exception)]))
print("__CALLS__" + json.dumps(calls))
"""


def _run_serve(backend_key: str, db_path: str):
    """Drive the real ``serve`` command in a subprocess and record create calls.

    A subprocess rather than an in-process ``CliRunner`` because
    ``conftest._clean_registries`` empties every registry before each test
    while engine/tool registration is memoised — so the second in-process
    ``serve`` invocation runs against emptied registries and aborts before it
    reaches the memory block.  That made the in-process version pass or fail
    depending on test order.  ``uvicorn.run`` is stubbed so nothing binds a
    port, and engine discovery is stubbed so the test does not need Ollama or
    any other live engine; the memory-resolution path under test runs for real.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _SERVE_PROBE, backend_key, db_path],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    marker = "__CALLS__"
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            return [(key, kwargs) for key, kwargs in json.loads(line[len(marker) :])]
    raise AssertionError(
        f"serve probe produced no result\nstdout:\n{proc.stdout[-2000:]}\n"
        f"stderr:\n{proc.stderr[-2000:]}"
    )


class TestServeBackendResolution:
    def test_sqlite_receives_configured_db_path(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        calls = _run_serve("sqlite", db_path)

        memory_calls = [c for c in calls if c[0] == "sqlite"]
        assert memory_calls, f"serve did not construct the sqlite backend: {calls}"
        assert all(kwargs.get("db_path") == db_path for _key, kwargs in memory_calls)

    def test_non_sqlite_backend_receives_no_db_path(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        calls = _run_serve("dense", db_path)

        memory_calls = [c for c in calls if c[0] == "dense"]
        assert memory_calls, f"serve did not construct the dense backend: {calls}"
        # Previously db_path was passed here too, raising TypeError, which the
        # except clause turned into the server starting with no memory at all.
        for _key, kwargs in memory_calls:
            assert "db_path" not in kwargs
