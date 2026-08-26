"""Post-command "new version available" nudge.

Disabled: there is nothing to check against.

This module used to poll ``https://pypi.org/pypi/Grandpa/json`` after most CLI
commands. That name on PyPI belongs to an unrelated project (``grandpa`` 0.6.3,
"Bizerba AI Team"), so the poll compared Grandpa's version against a stranger's
release numbers — it could announce a bogus upgrade, and it pointed users at
``pip install --upgrade grandpa``, which would install that project over their
environment. It also sent a request to a third party on nearly every run of a
tool whose premise is that it stays local.

Grandpa is distributed as a git checkout. Checkout installs already upgrade
through ``grandpa self-update`` (``git pull && uv sync``), which needs no
version poll to be useful. Until Grandpa has a distribution channel of its own,
:func:`check_for_updates` does nothing and makes no network calls.

To restore automatic checks, point them at a source that is verifiably Grandpa
and re-add an opt-out before doing so.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Set when Grandpa has a verified distribution channel to check against.
#: Until then no update polling happens. See the module docstring.
UPDATE_CHECKS_AVAILABLE = False


def check_for_updates(command_name: str) -> None:
    """No-op. Kept so the CLI entry point needs no special-casing.

    Never performs I/O and never raises, regardless of *command_name*.
    """
    if not UPDATE_CHECKS_AVAILABLE:
        logger.debug(
            "Update check skipped for %r: no verified distribution channel.",
            command_name,
        )
        return


__all__ = ["UPDATE_CHECKS_AVAILABLE", "check_for_updates"]
