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


class AppApi:
    """What the page may ask of the window (pywebview exposes these to JS).

    Two things, both read-only: pick a file to attach (the user chooses it in
    Windows' own dialog; only its path comes back) and Captain's name for the
    bottom-left corner. Nothing here reaches the chat engine or acts.
    """

    def __init__(self) -> None:
        self.window: Any = None

    def pick_file(self) -> str | None:
        if self.window is None:
            return None
        try:
            import webview

            chosen = self.window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False
            )
        except Exception:  # noqa: BLE001
            return None
        return str(chosen[0]) if chosen else None

    def user_name(self) -> str:
        return user_name()


def user_name() -> str:
    """The name Grandpa calls the user (``[user] username``), else the OS name."""
    try:
        from grandpa.core.config import load_config

        name = str(load_config().user.username or "").strip()
        if name and name != "Username":  # "Username" is the unset default
            return name
    except Exception:  # noqa: BLE001
        pass
    import getpass

    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "You"


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
        on_talk=session.talk,
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
        api = AppApi()
        window = webview_module.create_window(
            "Grandpa",
            str(INDEX),
            js_api=api,
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
