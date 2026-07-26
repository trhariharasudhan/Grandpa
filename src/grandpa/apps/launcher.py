"""Safe app launch helpers for indexed applications."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from grandpa.apps.models import ApplicationInfo
from grandpa.apps.safety import is_safe_launch_target

logger = logging.getLogger(__name__)


def launch_application(app: ApplicationInfo, *, args: list[str] | None = None) -> str:
    """Launch a previously indexed application target."""

    target = Path(app.path)
    if not is_safe_launch_target(target):
        logger.warning("Blocked unsafe application launch target: %s", target)
        raise ValueError("dangerous_launch_target")
    launch_args = list(args or [])
    logger.info("Application launch requested: %s (%s)", app.display_name, target)
    if target.suffix.lower() == ".exe":
        subprocess.Popen([str(target), *launch_args], cwd=app.working_directory or None, shell=False)  # noqa: S603
    else:
        if launch_args:
            raise ValueError("shortcut_args_unsupported")
        os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
    logger.info("Application launch succeeded: %s", app.display_name)
    return f"Opening {app.display_name}."


__all__ = ["launch_application"]
