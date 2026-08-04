"""Background scheduler daemon for routines and reminders."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from grandpa.task_scheduler import SchedulerStore, execute_due_once

logger = logging.getLogger(__name__)


@dataclass
class SchedulerDaemonStatus:
    running: bool
    poll_interval_seconds: float
    started_at: float | None
    last_tick_at: float | None
    last_result: dict[str, Any] | None
    last_error: str | None
    reminders: dict[str, Any] | None = None


class BackgroundSchedulerDaemon:
    """Small thread-based scheduler loop for the server process.

    This daemon hosts routine execution and one-shot local reminders so Grandpa
    does not spin up multiple scheduler loops in the same backend process.
    """

    def __init__(
        self,
        *,
        store: SchedulerStore | None = None,
        reminder_store: Any = None,
        reminder_notifier: Any = None,
        poll_interval_seconds: float = 15.0,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store or SchedulerStore()
        from grandpa.reminders import ReminderSchedulerService, ReminderStore

        self.reminder_scheduler = ReminderSchedulerService(
            reminder_store or ReminderStore(),
            notifier=reminder_notifier,
            poll_interval_seconds=poll_interval_seconds,
            now_fn=now_fn,
        )
        self.poll_interval_seconds = poll_interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._last_tick_at: float | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run,
            name="grandpa-routine-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Routine scheduler daemon started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.reminder_scheduler.stop(timeout=timeout)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("Routine scheduler daemon stopped")

    def tick(self) -> dict[str, Any]:
        with self._lock:
            self._last_tick_at = time.time()
            try:
                routine_result = execute_due_once(self.store, now=self._last_tick_at)
                reminder_result = self.reminder_scheduler.tick()
                result = {
                    "status": "ok",
                    "routines": routine_result,
                    "reminders": reminder_result,
                    "routines_run": routine_result.get("routines_run", 0),
                    "legacy_reminders_triggered": routine_result.get(
                        "reminders_triggered", 0
                    ),
                    "reminders_triggered": len(reminder_result.get("triggered", [])),
                    "reminders_failed": len(reminder_result.get("failed", [])),
                }
                self._last_result = result
                self._last_error = None
                return result
            except Exception as exc:  # pragma: no cover - defensive background guard
                self._last_error = str(exc)
                logger.exception("Routine scheduler daemon tick failed")
                return {"status": "error", "message": str(exc)}

    def status(self) -> dict[str, Any]:
        thread_running = bool(self._thread and self._thread.is_alive())
        reminder_status = self.reminder_scheduler.status()
        reminder_status.update(
            {
                "hosted_by_daemon": True,
                "running": thread_running and not self._stop.is_set(),
            }
        )
        status = SchedulerDaemonStatus(
            running=thread_running and not self._stop.is_set(),
            poll_interval_seconds=self.poll_interval_seconds,
            started_at=self._started_at,
            last_tick_at=self._last_tick_at,
            last_result=self._last_result,
            last_error=self._last_error,
            reminders=reminder_status,
        )
        return status.__dict__

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.poll_interval_seconds)


__all__ = ["BackgroundSchedulerDaemon", "SchedulerDaemonStatus"]
