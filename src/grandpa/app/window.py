"""Open the desktop app: engine + local WebSocket + a native window.

The window is pywebview (Edge WebView2 on Windows, GTK/Qt WebKit on Linux).
The page talks to Python only through :class:`AvatarServer`: loopback, a
per-run token, two inbound message kinds. The token is handed to the page with
``evaluate_js`` after it loads, never put in a file or a logged URL.

``--browser`` skips the window and prints an address for a normal browser tab,
which is also how the page is tested without pywebview.
"""

from __future__ import annotations

import functools
import json
import threading
from pathlib import Path
from typing import Any, Callable

from grandpa.ui.avatar_window import ensure_js_mime, missing_pywebview

WEB_DIR = Path(__file__).with_name("web")
INDEX = WEB_DIR / "index.html"
SIZE = (1120, 760)
MIN_SIZE = (720, 480)
BACKGROUND = "#0b0c0c"


def connect_script(ws_url: str) -> str:
    return f"window.grandpaConnect && window.grandpaConnect({json.dumps(ws_url)});"


def serve_page() -> tuple[Any, int]:
    """Serve ``web/`` read-only on loopback (for ``--browser``)."""
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class _Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

    ensure_js_mime()
    handler = functools.partial(_Quiet, directory=str(WEB_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(
        target=server.serve_forever, name="grandpa-app-page", daemon=True
    ).start()
    return server, server.server_address[1]


def browser_address(ws_url: str, page_port: int) -> str:
    from urllib.parse import quote

    return f"http://127.0.0.1:{page_port}/index.html#ws={quote(ws_url, safe='')}"


def _storage_dir() -> str | None:
    """Where the window keeps the chat list (localStorage) between runs."""
    try:
        from grandpa.runtime_paths import grandpa_home

        folder = grandpa_home() / "app_webview"
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder)
    except Exception:  # noqa: BLE001
        return None


def run(
    *,
    chat_args: list[str] | None = None,
    browser: bool = False,
    debug: bool = False,
    echo: Callable[[str], None] = print,
    webview_module: Any = None,
    wait: Callable[[], None] | None = None,
) -> int:
    """Run the app until the window is closed (or Ctrl+C with ``--browser``)."""
    from grandpa.app.session import AppSession
    from grandpa.ui.avatar_server import AvatarServer

    holder: dict[str, Any] = {}

    def publish(message: dict[str, Any]) -> None:
        server = holder.get("server")
        if server is not None:
            server.broadcast(message)

    session = AppSession(publish, chat_args=chat_args)
    server = AvatarServer(
        on_send=session.send,
        on_talk=None,
        on_cancel=session.cancel,
        snapshot=session.snapshot,
    )
    holder["server"] = server
    server.start(timeout=20)
    session.start()

    try:
        if browser:
            _page, port = serve_page()
            echo("Grandpa app: open this address in your browser:")
            echo("  " + browser_address(server.url, port))
            echo("Press Ctrl+C to stop.")
            if wait is not None:
                wait()
            else:
                threading.Event().wait()
            return 0

        if webview_module is None:
            try:
                import webview as webview_module  # pywebview
            except ImportError as exc:
                raise missing_pywebview() from exc
        ensure_js_mime()
        window = webview_module.create_window(
            "Grandpa",
            str(INDEX),
            width=SIZE[0],
            height=SIZE[1],
            min_size=MIN_SIZE,
            background_color=BACKGROUND,
        )
        window.events.loaded += lambda *_a: window.evaluate_js(
            connect_script(server.url)
        )
        storage = _storage_dir()
        kwargs: dict[str, Any] = {"http_server": True, "debug": debug}
        if storage:
            kwargs.update(private_mode=False, storage_path=storage)
        webview_module.start(**kwargs)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        session.stop()
        server.stop()


__all__ = ["INDEX", "WEB_DIR", "browser_address", "connect_script", "run", "serve_page"]
