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

_FAILED: list[str] = []


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
    option = config.option
    scope = scope_from_options(
        file_or_dir=list(getattr(option, "file_or_dir", []) or []),
        keyword=getattr(option, "keyword", "") or "",
        markexpr=getattr(option, "markexpr", "") or "",
        deselect=list(getattr(option, "deselect", []) or []),
        last_failed=bool(getattr(option, "lf", False)),
        failed_first=bool(getattr(option, "failedfirst", False)),
    )
    repo = repo_root(Path(str(config.rootdir)))
    try:
        digest = worktree_digest(repo)
    except Exception:  # noqa: BLE001 - never fail a test run over bookkeeping
        # A digest we could not take is recorded as one that matches nothing, so
        # the guard refuses rather than trusting a blank.
        digest = "unavailable"
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    record = Record(
        exitstatus=int(exitstatus),
        scope=scope,
        digest=digest,
        when=time.time(),
        argv=list(config.invocation_params.args),
        counts=_counts(reporter) if reporter is not None else {},
        failed=list(_FAILED),
    )
    try:
        write_record(repo, record)
    except OSError:  # noqa: BLE001 - a read-only checkout is not a test failure
        pass
