"""pytest records its own verdict, so nothing downstream has to be trusted with it.

``2df79819`` was committed on a failing suite because the pytest output went
through ``tail`` in an ``&&`` chain, so the shell saw tail's exit status. The
number was correct at the source and wrong by the time anyone acted on it.

Everything here runs *inside* the pytest process. ``pytest_sessionfinish``
receives the real exit status as an argument; the record is written from that,
before any pipe, redirect, ``&&`` or human summary exists. The commit guard
(``scripts/commit_verification.py``) reads the file, not a terminal.

Deliberately not a refusal of anything: this module only observes. The refusing
is done by the commit-msg hook, which is the only place that can refuse a
commit.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from commit_verification import (  # noqa: E402
    Record,
    repo_root,
    scope_from_options,
    worktree_digest,
    write_record,
)

#: The digest taken when this run started, so sessionfinish can tell whether
#: the tree changed underneath it.
_STARTED: dict[str, object] = {}

_FAILED: list[str] = []


def _imported_source() -> str:
    """The directory ``grandpa`` was imported from, or "" if it was not.

    This is the difference between "these files were on disk" and "these files
    ran". Two full runs this week were started without PYTHONPATH: they
    collected this checkout's tests, imported another checkout's source, and
    recorded a correct digest of this one.

    Read from ``sys.modules`` rather than by importing: by sessionfinish the
    suite has long since imported it, and importing here would make the answer
    depend on this function instead of reporting what actually happened.
    """
    module = sys.modules.get("grandpa")
    location = getattr(module, "__file__", None) if module else None
    if not location:
        return ""
    try:
        # <src>/grandpa/__init__.py -> <src>
        return str(Path(location).resolve().parent.parent)
    except OSError:
        return ""


def pytest_sessionstart(session) -> None:
    """Record that a run has STARTED, before it can prove anything.

    A run that is killed writes nothing at sessionfinish, so the guard used to
    fall back to an older record -- the absence was invisible. This leaves a
    record marked incomplete, which the guard refuses by name.
    """
    config = session.config
    if getattr(config.option, "collectonly", False):
        return
    repo = repo_root(Path(str(config.rootdir)))
    try:
        digest = worktree_digest(repo)
    except Exception:  # noqa: BLE001 - bookkeeping must not fail a run
        digest = "unavailable"
    _STARTED["digest"] = digest
    _STARTED["when"] = time.time()
    record = Record(
        exitstatus=-1,
        scope=_scope_of(config),
        digest=digest,
        started_digest=digest,
        when=_STARTED["when"],
        argv=list(config.invocation_params.args),
        complete=False,
        pid=os.getpid(),
    )
    try:
        write_record(repo, record)
    except OSError:  # noqa: BLE001 - a read-only checkout is not a failure
        pass


def _scope_of(config) -> str:
    option = config.option
    return scope_from_options(
        file_or_dir=list(getattr(option, "file_or_dir", []) or []),
        keyword=getattr(option, "keyword", "") or "",
        markexpr=getattr(option, "markexpr", "") or "",
        deselect=list(getattr(option, "deselect", []) or []),
        last_failed=bool(getattr(option, "lf", False)),
        failed_first=bool(getattr(option, "failedfirst", False)),
    )


def pytest_runtest_logreport(report) -> None:
    """Collect the names of what failed, so the refusal can name them too."""
    if report.failed and report.when in {"setup", "call", "teardown"}:
        if report.nodeid not in _FAILED:
            _FAILED.append(report.nodeid)


def _counts(terminalreporter) -> dict[str, int]:
    stats = getattr(terminalreporter, "stats", {}) or {}
    return {
        key: len(value)
        for key, value in stats.items()
        if key in {"passed", "failed", "error", "skipped", "xfailed", "xpassed"}
    }


def pytest_sessionfinish(session, exitstatus) -> None:
    """Write what this run actually proved, about exactly this tree."""
    config = session.config
    if getattr(config.option, "collectonly", False):
        return
    scope = _scope_of(config)
    repo = repo_root(Path(str(config.rootdir)))
    try:
        digest = worktree_digest(repo)
    except Exception:  # noqa: BLE001 - never fail a test run over bookkeeping
        # A digest we could not take is recorded as one that matches nothing, so
        # the guard refuses rather than trusting a blank.
        digest = "unavailable"
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    record = Record(
        source=_imported_source(),
        exitstatus=int(exitstatus),
        scope=scope,
        digest=digest,
        # Taken at sessionstart. When the two differ the tree was edited while
        # the run was going, and the run proved nothing about either state.
        started_digest=str(_STARTED.get("digest") or digest),
        complete=True,
        pid=os.getpid(),
        when=_STARTED.get("when", time.time()),
        argv=list(config.invocation_params.args),
        counts=_counts(reporter) if reporter is not None else {},
        failed=list(_FAILED),
    )
    try:
        write_record(repo, record)
    except OSError:  # noqa: BLE001 - a read-only checkout is not a test failure
        pass
