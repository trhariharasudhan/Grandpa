"""Reminders come due while the orb is open: Grandpa says them.

Captain set "remind me in 2 minutes to drink water" and nothing happened at
the time: the reminder was saved, but nothing that delivers reminders was
running -- the scheduler lived in ``grandpa scheduler`` and the tray, not in
the orb or the app. While the orb runs, it now checks every 20 seconds and,
for each reminder that is due:

* says it ("Reminder: drink water") and shows it in the panel;
* also pops a Windows notification when ``winotify`` is installed, so a
  reminder is seen even with the sound off.

Delivery is marked in the same store, so a reminder is never said twice; one
that came due while the PC was off is said on the next start, with how late
it is ("(15 minutes late)").
"""

from __future__ import annotations

import logging
from typing import Any

from grandpa.reminders import (
    NotificationResult,
    Reminder,
    ReminderSchedulerService,
    ReminderStore,
    WindowsToastNotifier,
)

logger = logging.getLogger(__name__)

POLL_SECONDS = 20.0


class OrbReminderNotifier:
    """Speak through the orb; a toast too when the system can show one."""

    def __init__(self, controller: Any, toast: Any | None = None) -> None:
        self.controller = controller
        self.toast = toast if toast is not None else WindowsToastNotifier()

    def notify(self, reminder: Reminder) -> NotificationResult:
        spoken = False
        try:
            spoken = bool(self.controller.announce(f"Reminder: {reminder.message}"))
        except Exception:  # noqa: BLE001 - the toast may still reach the user
            logger.warning("the orb could not say a reminder", exc_info=True)
        toasted = False
        try:
            toasted = bool(self.toast.notify(reminder).ok)
        except Exception:  # noqa: BLE001
            logger.debug("reminder toast failed", exc_info=True)
        if spoken or toasted:
            how = " and ".join(n for n, ok in (("said", spoken), ("notified", toasted)) if ok)
            return NotificationResult(True, "sent", f"Reminder {how}.", backend="orb")
        return NotificationResult(
            False, "failed", "The orb could not deliver the reminder.", backend="orb"
        )


def start_reminders(controller: Any, *, store: ReminderStore | None = None) -> ReminderSchedulerService | None:
    """Start delivering due reminders through *controller*; ``None`` if it cannot."""
    try:
        service = ReminderSchedulerService(
            store or ReminderStore(),
            notifier=OrbReminderNotifier(controller),
            poll_interval_seconds=POLL_SECONDS,
        )
        service.start()
        return service
    except Exception:  # noqa: BLE001 - the orb works without reminders
        logger.warning("reminders could not be started", exc_info=True)
        return None


__all__ = ["OrbReminderNotifier", "POLL_SECONDS", "start_reminders"]
