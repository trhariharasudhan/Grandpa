"""The desktop window for the avatar: a small ring that opens into a chat panel.

pywebview hosts the page in WebView2 on Windows. The page is served by
pywebview's own local file server (``http_server=True``), so its Content
Security Policy can say ``'self'``; the WebSocket address with its per-run token
is handed over with ``evaluate_js`` once the page has loaded, rather than put in
a URL that might be logged.

It opens **collapsed**: a ring-sized window showing only the glowing ring, like
the bubble's orb. A click on the ring opens the panel (the window grows to the
chat size) and another click closes it; a drag moves the window and never
toggles. The page asks for those two things through :class:`WindowApi`, the
only methods exposed to it -- window geometry, nothing that reaches Grandpa.

The window is opaque and dark. WebView2 under pywebview painted a white page
where a transparent one was asked for (seen on Captain's machine), so a solid
background that matches the panel is the reliable look.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).with_name("avatar_web")
INDEX = WEB_DIR / "index.html"

COLLAPSED = (132, 132)
"""The ring alone."""
EXPANDED = (360, 560)
"""The ring and the chat panel."""

BACKGROUND = "#12141C"

MAX_STEP = 400
"""Largest single drag step accepted from the page, in pixels."""


def missing_pywebview() -> RuntimeError:
    return RuntimeError(
        "The avatar window needs pywebview. Install the avatar extra: "
        'uv sync --extra avatar   (or: pip install -e ".[avatar]"). '
        "Or run `grandpa avatar --no-window` and open the printed address."
    )


def ensure_js_mime() -> None:
    """Serve ``.js`` as JavaScript, whatever the Windows registry says.

    character.js (A3) is an ES module, and a browser refuses a module served as
    ``text/plain`` -- which is what Python's ``mimetypes`` reports for ``.js``
    on Windows machines whose registry maps it that way. Both servers (ours for
    --no-window and pywebview's) ask ``mimetypes``.
    """
    import mimetypes

    mimetypes.add_type("text/javascript", ".js")


def connect_script(ws_url: str) -> str:
    """The one line of JS the window runs: hand the page its address."""
    return f"window.grandpaConnect({json.dumps(ws_url)});"


class WindowApi:
    """What the page may ask of the window: open/close the panel, and move.

    pywebview exposes every public method of this object to the page, so it has
    exactly these two, and both take plain numbers or a flag.
    """

    def __init__(self) -> None:
        self._window: Any = None
        self._lock = threading.Lock()
        self.expanded = False

    def attach(self, window: Any) -> None:
        self._window = window

    def set_expanded(self, expanded: Any) -> bool:
        if not isinstance(expanded, bool):
            return self.expanded
        with self._lock:
            self.expanded = expanded
            width, height = EXPANDED if expanded else COLLAPSED
            if self._window is not None:
                self._window.resize(width, height)
        return self.expanded

    def move_by(self, dx: Any, dy: Any) -> None:
        if isinstance(dx, bool) or isinstance(dy, bool):
            return
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            return
        dx = max(-MAX_STEP, min(MAX_STEP, int(dx)))
        dy = max(-MAX_STEP, min(MAX_STEP, int(dy)))
        window = self._window
        if window is None or (dx == 0 and dy == 0):
            return
        with self._lock:
            window.move(int(window.x) + dx, int(window.y) + dy)


def serve_page() -> tuple[Any, int]:
    """For --no-window: serve the page's folder on loopback. Returns (server, port).

    Only ``avatar_web`` is served, read-only, on ``127.0.0.1``. It holds no
    secret: the token travels in the address the user opens, not in a file.
    """
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class _Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:  # noqa: D401 - silence
            return

    ensure_js_mime()
    handler = functools.partial(_Quiet, directory=str(WEB_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(
        target=server.serve_forever, name="grandpa-avatar-page", daemon=True
    ).start()
    return server, server.server_address[1]


def browser_address(ws_url: str, page_port: int) -> str:
    """The page's address for a browser tab, with the socket address in its hash."""
    from urllib.parse import quote

    return f"http://127.0.0.1:{page_port}/index.html#ws={quote(ws_url, safe='')}"


def run_window(
    ws_url: str,
    *,
    on_top: bool = True,
    debug: bool = False,
    webview_module: Any = None,
) -> None:
    """Open the window and block until it is closed (pywebview owns the loop)."""
    if webview_module is None:
        try:
            import webview as webview_module  # pywebview
        except ImportError as exc:
            raise missing_pywebview() from exc

    ensure_js_mime()
    api = WindowApi()
    width, height = COLLAPSED
    window = webview_module.create_window(
        "Grandpa",
        str(INDEX),
        js_api=api,
        width=width,
        height=height,
        min_size=COLLAPSED,
        frameless=True,
        easy_drag=False,
        on_top=on_top,
        background_color=BACKGROUND,
    )
    api.attach(window)

    def _hand_over(*_args: Any) -> None:
        window.evaluate_js(connect_script(ws_url))

    window.events.loaded += _hand_over
    webview_module.start(http_server=True, debug=debug)


__all__ = [
    "BACKGROUND",
    "COLLAPSED",
    "EXPANDED",
    "INDEX",
    "WEB_DIR",
    "WindowApi",
    "browser_address",
    "connect_script",
    "ensure_js_mime",
    "missing_pywebview",
    "run_window",
    "serve_page",
]
