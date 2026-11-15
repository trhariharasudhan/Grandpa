"""The desktop window for the avatar: transparent, frameless, always on top.

pywebview hosts the page in WebView2 on Windows. The page is served by
pywebview's own local file server (``http_server=True``), so its Content
Security Policy can say ``'self'``; the WebSocket address with its per-run token
is handed over with ``evaluate_js`` once the page has loaded, rather than put in
a URL that might be logged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).with_name("avatar_web")
INDEX = WEB_DIR / "index.html"

WIDTH = 360
HEIGHT = 560


def missing_pywebview() -> RuntimeError:
    return RuntimeError(
        "The avatar window needs pywebview. Install the avatar extra: "
        'uv sync --extra avatar   (or: pip install -e ".[avatar]"). '
        "Or run `grandpa avatar --no-window` and open the printed address."
    )


def connect_script(ws_url: str) -> str:
    """The one line of JS the window runs: hand the page its address."""
    return f"window.grandpaConnect({json.dumps(ws_url)});"


def serve_page() -> tuple[Any, int]:
    """For --no-window: serve the page's folder on loopback. Returns (server, port).

    Only ``avatar_web`` is served, read-only, on ``127.0.0.1``. It holds no
    secret: the token travels in the address the user opens, not in a file.
    """
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class _Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:  # noqa: D401 - silence
            return

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
    transparent: bool = True,
    debug: bool = False,
    webview_module: Any = None,
) -> None:
    """Open the window and block until it is closed (pywebview owns the loop)."""
    if webview_module is None:
        try:
            import webview as webview_module  # pywebview
        except ImportError as exc:
            raise missing_pywebview() from exc

    window = webview_module.create_window(
        "Grandpa",
        str(INDEX),
        width=WIDTH,
        height=HEIGHT,
        frameless=True,
        easy_drag=False,
        on_top=on_top,
        transparent=transparent,
        background_color="#000000",
    )

    def _hand_over(*_args: Any) -> None:
        window.evaluate_js(connect_script(ws_url))

    window.events.loaded += _hand_over
    webview_module.start(http_server=True, debug=debug)


__all__ = [
    "HEIGHT",
    "INDEX",
    "WEB_DIR",
    "WIDTH",
    "browser_address",
    "connect_script",
    "missing_pywebview",
    "run_window",
    "serve_page",
]
