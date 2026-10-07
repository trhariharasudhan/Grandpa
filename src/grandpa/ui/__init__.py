"""Grandpa's desktop UI: a floating bubble over the existing paths.

Three layers, deliberately separated so the middle one can be tested without a
display:

* :mod:`grandpa.ui.bridge` -- the two methods the UI may use, ``send`` and
  ``transcribe``, both in-process.
* :mod:`grandpa.ui.bubble` -- the controller. All the behaviour, no toolkit
  import. Drives an injected view.
* :mod:`grandpa.ui.tk_view` -- the tkinter view. Imports tkinter lazily and is
  itself driven by an injected ``tkinter`` module, the way
  ``grandpa.tray.start_tray`` takes ``pystray_module``.

No test opens a window, a microphone or a speaker.
"""

from __future__ import annotations

__all__ = ["bridge", "bubble", "tk_view"]
