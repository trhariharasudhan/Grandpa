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
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from grandpa.ui.avatar_window import ensure_js_mime, missing_pywebview

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).with_name("web")
INDEX = WEB_DIR / "index.html"
SIZE = (1120, 760)
MIN_SIZE = (720, 480)
BACKGROUND = "#0b0c0c"


#: What the 📎 dialog offers: text, code and documents Grandpa can read.
FILE_TYPES = (
    "Text and documents (*.txt;*.md;*.csv;*.json;*.log;*.py;*.js;*.ts;*.html;*.css;"
    "*.toml;*.yaml;*.yml;*.xml;*.ini;*.ps1;*.bat;*.sql;*.pdf;*.docx;*.xlsx;*.pptx)",
    "All files (*.*)",
)
MAX_PICK = 5


class AppApi:
    """What the page may ask of the window (pywebview exposes these to JS).

    * pick files to attach -- the user chooses them in the system's own file
      dialog; only their paths come back, and only those paths may then be
      read for attaching;
    * read and save the profile (title, name, email) that every Grandpa
      surface uses;
    * open the orb as its own program.

    Nothing here runs a command the page chose or reaches the chat engine.
    """

    def __init__(self, session: Any = None) -> None:
        # Private: pywebview hands every public attribute of this object to the
        # page, nested objects included, so the window and the session stay
        # out of its reach.
        self._window: Any = None
        self._webview: Any = None
        self._session = session

    def _set_window(self, window: Any, webview_module: Any = None) -> None:
        # private (leading underscore): pywebview never offers it to the page
        self._window = window
        self._webview = webview_module

    def pick_files(self) -> list[str]:
        if self._window is None:
            return []
        try:
            webview = self._webview
            if webview is None:
                import webview
            dialog = getattr(webview, "FileDialog", None)
            kind = dialog.OPEN if dialog is not None else webview.OPEN_DIALOG
            chosen = self._window.create_file_dialog(
                kind, allow_multiple=True, file_types=FILE_TYPES
            )
        except Exception:  # noqa: BLE001 - no dialog is "nothing picked"
            logger.exception("file dialog failed")
            return []
        paths = [str(p) for p in (chosen or ())][:MAX_PICK]
        if self._session is not None:
            paths = [self._session.allow_file(p) for p in paths]
        return paths

    def pick_file(self) -> str | None:  # the older page's name for it
        paths = self.pick_files()
        return paths[0] if paths else None

    def user_name(self) -> str:
        return user_name()

    def get_profile(self) -> dict[str, Any]:
        return read_profile()

    def save_profile(self, title: Any, name: Any, email: Any) -> dict[str, Any]:
        return write_profile(title, name, email)

    def open_orb(self) -> str:
        from grandpa.app.launch import launch

        try:
            return launch("avatar")
        except (OSError, ValueError):
            return "failed"


def read_profile() -> dict[str, Any]:
    """The profile the page shows: title, name, email, display name."""
    try:
        from grandpa.cli.theme import resolve_display_name
        from grandpa.core.config import load_config
        from grandpa.profile import profile_from_config

        config = load_config()
        profile = profile_from_config(config)
        named = profile.username != "Username"
        return {
            "title": profile.title,
            "name": profile.username if named else "",
            "email": profile.email,
            "display": resolve_display_name(config) if named else "",
            "onboarded": bool(profile.onboarding_completed and named),
        }
    except Exception:  # noqa: BLE001
        return {"title": "", "name": "", "email": "", "display": "", "onboarded": False}


def write_profile(title: Any, name: Any, email: Any) -> dict[str, Any]:
    """Validate and save; ``{"ok": False, "error": ...}`` when a field is wrong."""
    from grandpa.core.config import load_config
    from grandpa.profile import (
        atomic_update_profile,
        config_path,
        validate_email,
        validate_title,
        validate_username,
    )

    try:
        values = {
            "title": validate_title(title),
            "username": validate_username(name),
            "email": validate_email(email),
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    atomic_update_profile(config_path(), onboarding_completed=True, **values)
    load_config.cache_clear()
    return {"ok": True, **read_profile()}


def user_name() -> str:
    """How Grandpa names the user ("Mr. Hari Hara Sudhan"), else the OS name."""
    display = read_profile().get("display")
    if display:
        return str(display)
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

    from grandpa.app.launch import claim, release

    if not browser and not claim("app"):
        echo("Grandpa app is already open (look for its window on the taskbar).")
        return 0
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
        api = AppApi(session)
        window = webview_module.create_window(
            "Grandpa",
            str(INDEX),
            js_api=api,
            width=SIZE[0],
            height=SIZE[1],
            min_size=MIN_SIZE,
            background_color=BACKGROUND,
        )
        # Without this the 📎 dialog had no window to open on and quietly did
        # nothing -- the "attaching doesn't work" Captain saw.
        api._set_window(window, webview_module)
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
        if not browser:
            release("app")


__all__ = ["INDEX", "WEB_DIR", "browser_address", "connect_script", "run", "serve_page"]
