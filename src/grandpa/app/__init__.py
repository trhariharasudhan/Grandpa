"""Grandpa's desktop app: a ChatGPT/Claude-style window on the chat engine.

``grandpa app`` opens it. The page lives in ``web/``; :mod:`.session` turns the
chat engine into messages for it; :mod:`.window` opens the native window.
"""

from grandpa.app.window import WEB_DIR, run

__all__ = ["WEB_DIR", "run"]
