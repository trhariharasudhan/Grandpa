"""Make a sqlite connection that outlives its test visible.

Three stalls, in three unrelated places, none reproducible on demand:

* an 1114-second teardown of ``tests/workflow/test_workflow.py`` -- a test whose
  own body runs in 1.9 seconds;
* a 210-second *setup* of ``tests/traces/test_analyzer.py``;
* ``tests/security/test_agent_plan_cannot_be_named_into_a_write.py`` blocked in
  ``MemoryIntelligenceStore.sync()`` on ``conn.execute`` until pytest killed it
  at 300 seconds.

The third came with a stack dump, and it is the one that names a mechanism: a
test was waiting for a sqlite lock. sqlite blocks a writer while another
connection holds a write transaction, and it blocks for its busy timeout, which
defaults to five seconds but is set higher in places. A connection left open by
an earlier test -- never closed, or owned by a module-level singleton that
survives the test that created it -- will do exactly this to whatever runs next.

So: record every connection, who opened it, and whether it was closed. At the end
of each test, anything that test opened and did not close is a leak, and the
report says which test and which file. Armed by ``GRANDPA_TRACK_SQLITE=1`` so an
ordinary run pays nothing.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import traceback
import weakref
from dataclasses import dataclass, field
from pathlib import Path

ENV_VAR = "GRANDPA_TRACK_SQLITE"

_LOCK = threading.Lock()


@dataclass
class _Open:
    database: str
    nodeid: str
    opened_at: str
    stack: str
    closed: bool = False


@dataclass
class Tracker:
    """Every connection this process has opened, and who opened it."""

    by_connection: dict[int, _Open] = field(default_factory=dict)
    live: "weakref.WeakValueDictionary[int, sqlite3.Connection]" = field(
        default_factory=weakref.WeakValueDictionary
    )
    """Weak handles, so ``in_transaction`` can be asked without keeping anything alive.

    A strong dict here was a real defect in this instrument: it held every
    connection the suite ever opened, so nothing could be garbage collected and
    every connection stayed open for the whole run. An instrument that keeps
    connections alive manufactures exactly the contention it is looking for, and
    it grew the per-test scan without bound -- the first tracked run showed a
    5.3 second teardown that this is the likeliest explanation for.
    """

    current_nodeid: str = "<import>"
    leaks: list[tuple[str, str, str]] = field(default_factory=list)
    """(nodeid, database, the line that opened it) for each leak found."""

    def record(self, connection: sqlite3.Connection, database: str) -> None:
        frames = [
            frame
            for frame in traceback.extract_stack()[:-2]
            if "site-packages" not in frame.filename
        ]
        where = ""
        for frame in reversed(frames):
            if (
                "\\src\\grandpa\\" in frame.filename
                or "/src/grandpa/" in frame.filename
            ):
                where = f"{Path(frame.filename).name}:{frame.lineno} {frame.name}"
                break
        if not where and frames:
            last = frames[-1]
            where = f"{Path(last.filename).name}:{last.lineno} {last.name}"
        with _LOCK:
            self.by_connection[id(connection)] = _Open(
                database=database,
                nodeid=self.current_nodeid,
                opened_at=where,
                stack=where,
            )
            self.live[id(connection)] = connection

    def mark_closed(self, connection: sqlite3.Connection) -> None:
        with _LOCK:
            found = self.by_connection.get(id(connection))
            if found is not None:
                found.closed = True
            self.live.pop(id(connection), None)

    def open_for(self, nodeid: str) -> list[_Open]:
        with _LOCK:
            return [
                record
                for record in self.by_connection.values()
                if record.nodeid == nodeid and not record.closed
            ]

    def in_transaction(self) -> list[_Open]:
        """Open connections currently holding a transaction.

        This is the set that actually blocks somebody: sqlite lets any number of
        idle connections coexist, and blocks a writer only while another
        connection holds a write transaction. A leak that matters is a leak that
        is mid-transaction when the next test starts.

        Iterates the weak map rather than every record ever seen, so the cost is
        proportional to what is still alive rather than to how long the suite has
        been running.
        """
        found: list[_Open] = []
        with _LOCK:
            for key, connection in list(self.live.items()):
                record = self.by_connection.get(key)
                if record is None or record.closed:
                    continue
                try:
                    if connection.in_transaction:
                        found.append(record)
                except sqlite3.ProgrammingError:
                    # Closed underneath us without going through close().
                    continue
        return found

    def forget_dead(self) -> int:
        """Drop records for connections that have been garbage collected.

        Without this ``by_connection`` grows for the whole run and every scan
        walks the history. Returns how many were dropped.
        """
        with _LOCK:
            alive = set(self.live.keys())
            dead = [
                key
                for key, record in self.by_connection.items()
                if record.closed or key not in alive
            ]
            for key in dead:
                self.by_connection.pop(key, None)
            return len(dead)

    def still_open(self) -> list[_Open]:
        with _LOCK:
            return [r for r in self.by_connection.values() if not r.closed]


TRACKER = Tracker()
_INSTALLED = False


class _TrackedConnection(sqlite3.Connection):
    """A connection that says when it is closed.

    ``sqlite3.Connection`` is a C type and its ``close`` cannot be replaced --
    "cannot set 'close' attribute of immutable type". Subclassing and passing the
    subclass as ``factory=`` is the supported way in, and it is what
    ``sqlite3.connect`` offers precisely for this.
    """

    def close(self) -> None:
        try:
            TRACKER.mark_closed(self)
        except Exception:  # noqa: BLE001 - instrumentation must not break a test
            pass
        super().close()


def install() -> bool:
    """Wrap sqlite3.connect so every connection is attributable. Returns armed."""
    global _INSTALLED
    if _INSTALLED or os.environ.get(ENV_VAR) != "1":
        return _INSTALLED
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Only supply the factory when the caller has not chosen one; a caller
        # with its own Connection subclass keeps it and simply is not tracked.
        if "factory" not in kwargs:
            kwargs["factory"] = _TrackedConnection
        connection = real_connect(database, *args, **kwargs)
        try:
            TRACKER.record(connection, str(database))
        except Exception:  # noqa: BLE001
            pass
        return connection

    sqlite3.connect = connect  # type: ignore[assignment]
    _INSTALLED = True
    return True


def describe(records: list[_Open]) -> str:
    lines = []
    for record in records:
        database = record.database
        if len(database) > 70:
            database = "..." + database[-67:]
        lines.append(f"    {database}\n        opened by {record.opened_at}")
    return "\n".join(lines)


__all__ = ["ENV_VAR", "TRACKER", "describe", "install"]
