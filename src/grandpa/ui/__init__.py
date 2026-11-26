"""Grandpa's desktop UI: the orb ring (``grandpa avatar``).

* :mod:`grandpa.ui.session_bridge` -- the orb talks to the same chat engine
  as the desktop app and the terminal.
* :mod:`grandpa.ui.avatar_controller` -- the behaviour, no toolkit import.
* :mod:`grandpa.ui.avatar_window` / :mod:`grandpa.ui.avatar_server` -- the
  pywebview window and its loopback socket; ``avatar_web/`` is the page.
* :mod:`grandpa.ui.wake_talk` -- "Hey Grandpa".

The tkinter bubble (``grandpa bubble``) was retired on 2026-11-26 in favour of
the orb ring.
"""

from __future__ import annotations

__all__ = ["avatar_controller", "bridge", "session_bridge"]
