"""Fixtures and hooks for the end-to-end CLI suite.

The suite is marked ``e2e`` and is deselected unless the ``-m`` expression names
``e2e``, so the default ``pytest -q`` never runs it. Run it with
``python scripts/run_e2e.py`` or ``python -m pytest -m e2e``.

A test that raises :class:`CouldNotRun` (engine down, no usable model, no
network, no desktop shell) is reported as skipped with a ``COULD NOT RUN``
reason, listed in its own summary section, and makes the session exit 2 when
nothing failed. It is never reported as a pass.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.harness import (
    CliRun,
    CouldNotRun,
    OllamaServer,
    Sandbox,
    candidate_models,
    nonce,
    ollama_generate,
    ollama_models,
    run_cli,
    verify_checkout,
)

E2E_DIR = Path(__file__).resolve().parent
E2E_TEST_TIMEOUT = 900
EXIT_COULD_NOT_RUN = 2

# Small models first: every model-backed test only needs a model that can
# repeat a token. Override with GRANDPA_E2E_MODEL=<name>.
PREFERRED_MODELS = (
    "grandpa-mini",
    "qwen2.5",
    "grandpa-fast",
    "llama3.2",
    "gemma3",
    "qwen3",
    "grandpa-brain",
)

_COULD_NOT_RUN = pytest.StashKey[list]()


# --------------------------------------------------------------------------
# Selection and reporting
# --------------------------------------------------------------------------


def _e2e_requested(config: pytest.Config) -> bool:
    markexpr = config.getoption("markexpr", default="") or ""
    return bool(re.search(r"\be2e\b", markexpr))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    in_suite = [item for item in items if E2E_DIR in Path(item.path).parents]
    unmarked = [item.nodeid for item in in_suite if not item.get_closest_marker("e2e")]
    if unmarked:
        raise pytest.UsageError(
            "tests under tests/e2e must be marked e2e so the default run skips them: "
            + ", ".join(unmarked)
        )
    if not _e2e_requested(config):
        if in_suite:
            config.hook.pytest_deselected(items=in_suite)
            items[:] = [item for item in items if item not in in_suite]
        return
    for item in in_suite:
        item.add_marker(pytest.mark.timeout(E2E_TEST_TIMEOUT))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is None or not call.excinfo.errisinstance(CouldNotRun):
        return
    reason = str(call.excinfo.value)
    report.outcome = "skipped"
    report.longrepr = (
        str(item.path),
        item.location[1] or 0,
        f"COULD NOT RUN: {reason}",
    )
    item.config.stash.setdefault(_COULD_NOT_RUN, []).append((item.nodeid, reason))


def pytest_terminal_summary(
    terminalreporter, exitstatus, config: pytest.Config
) -> None:
    entries = config.stash.get(_COULD_NOT_RUN, [])
    if not entries:
        return
    terminalreporter.section("COULD NOT RUN (no evidence; not a pass)", sep="=")
    for nodeid, reason in entries:
        terminalreporter.line(f"{nodeid}: {reason}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if session.config.stash.get(_COULD_NOT_RUN, []) and exitstatus == 0:
        session.exitstatus = EXIT_COULD_NOT_RUN


# --------------------------------------------------------------------------
# Session prerequisites
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def e2e_checkout() -> Path:
    """Every e2e test runs the CLI from this checkout, or none of them can run."""
    probe = Sandbox(prefix="grandpa-e2e-checkout-")
    try:
        return verify_checkout(probe)
    finally:
        probe.cleanup()


@pytest.fixture(scope="session")
def ollama():
    with OllamaServer() as server:
        yield server


@pytest.fixture(scope="session")
def e2e_model(ollama: OllamaServer) -> str:
    """A model proven, straight through the Ollama API, to repeat a token.

    The proof bypasses Grandpa on purpose: if the CLI is broken, the preflight
    must still pass so the broken CLI shows up as a FAIL, not COULD NOT RUN.
    """
    requested = os.environ.get("GRANDPA_E2E_MODEL") or None
    notes = []
    for model in candidate_models(ollama.models, requested, PREFERRED_MODELS)[:4]:
        token = nonce("preflight")
        reply = ollama_generate(
            model, f"Reply with exactly this word and nothing else: {token}"
        )
        if reply is not None and token.lower() in reply.lower():
            return model
        notes.append(f"{model}: {'no response' if reply is None else repr(reply[:60])}")
    raise CouldNotRun(
        "No installed model repeated a token through the Ollama API: "
        + "; ".join(notes)
    )


# --------------------------------------------------------------------------
# Per-test sandbox
# --------------------------------------------------------------------------


class Cli:
    """The real CLI, run as a subprocess inside one sandbox."""

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox
        self.home = sandbox.home
        self.grandpa_home = sandbox.grandpa_home

    def __call__(
        self, *args: str, stdin: str | None = None, timeout: float = 300
    ) -> CliRun:
        run = run_cli(
            self.sandbox,
            list(args),
            cwd=self.sandbox.root,
            stdin_text=stdin,
            timeout=timeout,
        )
        if run.timed_out:
            raise AssertionError(f"`grandpa {' '.join(args)}` timed out: {run.tail()}")
        return run

    def chat(self, model: str, *lines: str, timeout: float = 420) -> CliRun:
        """A piped chat session that sends ``lines`` and then ``exit``."""
        run = self.run_model(
            "chat",
            "--no-fullscreen",
            "-m",
            model,
            stdin="\n".join([*lines, "exit"]) + "\n",
            timeout=timeout,
        )
        assert "Goodbye" in run.text, (
            f"chat did not finish its session: {run.tail(600)}"
        )
        return run

    def run_model(
        self, *args: str, stdin: str | None = None, timeout: float = 420
    ) -> CliRun:
        """Like calling the CLI, but a timeout while Ollama is down is COULD NOT RUN."""
        run = run_cli(
            self.sandbox,
            list(args),
            cwd=self.sandbox.root,
            stdin_text=stdin,
            timeout=timeout,
        )
        if run.timed_out:
            if ollama_models() is None:
                raise CouldNotRun(
                    f"Ollama went away during `grandpa {' '.join(args)}`."
                )
            raise AssertionError(
                f"`grandpa {' '.join(args)}` timed out with Ollama reachable: {run.tail()}"
            )
        return run

    def use_default_model(self, model: str) -> None:
        """Point commands that read ``intelligence.default_model`` at ``model``."""
        self.grandpa_home.mkdir(parents=True, exist_ok=True)
        (self.grandpa_home / "config.toml").write_text(
            f'[intelligence]\ndefault_model = "{model}"\n', encoding="utf-8"
        )


@pytest.fixture
def sandbox() -> Sandbox:
    box = Sandbox(keep=os.environ.get("GRANDPA_E2E_KEEP") == "1")
    for folder in ("Desktop", "Documents", "Downloads"):
        (box.home / folder).mkdir()
    yield box
    box.cleanup()


@pytest.fixture
def cli(sandbox: Sandbox) -> Cli:
    return Cli(sandbox)


@pytest.fixture
def make_nonce() -> Callable[[str], str]:
    return nonce
