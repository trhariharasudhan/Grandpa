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


TRAY_OFF = "Tray: off (install the tray extra: uv sync --extra avatar --extra tray)."


class AvatarTray:
    """The tray icon (A6): left-click shows or hides the window; Quit closes it.

    It only shows, hides and closes this one window. It reaches nothing in
    Grandpa, so it cannot become a way around a confirmation.
    """

    def __init__(self, window: Any, pystray_module: Any, image: Any = None) -> None:
        self._window = window
        self._pystray = pystray_module
        self._image = image
        self.visible = True
        self.icon: Any = None
        self._lock = threading.Lock()

    def toggle(self, *_args: Any) -> bool:
        with self._lock:
            if self.visible:
                self._window.hide()
            else:
                self._window.show()
            self.visible = not self.visible
        self._refresh()
        return self.visible

    def quit(self, *_args: Any) -> None:
        self.stop()
        self._window.destroy()

    def label(self, *_args: Any) -> str:
        return "Hide Grandpa" if self.visible else "Show Grandpa"

    def menu(self) -> Any:
        item = self._pystray.MenuItem
        return self._pystray.Menu(
            item(self.label, self.toggle, default=True),
            item("Quit Grandpa", self.quit),
        )

    def start(self) -> None:
        if self._image is None:
            from grandpa.tray import create_placeholder_icon

            self._image = create_placeholder_icon()
        self.icon = self._pystray.Icon(
            "grandpa-avatar", icon=self._image, title="Grandpa", menu=self.menu()
        )
        run_detached = getattr(self.icon, "run_detached", None)
        if callable(run_detached):
            run_detached()
        else:  # pragma: no cover - older pystray
            threading.Thread(
                target=self.icon.run, name="grandpa-avatar-tray", daemon=True
            ).start()

    def stop(self) -> None:
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001 - the window still closes
                pass

    def _refresh(self) -> None:
        update = getattr(self.icon, "update_menu", None)
        if callable(update):
            try:
                update()
            except Exception:  # noqa: BLE001 - a stale label is harmless
                pass


def start_tray(window: Any, *, pystray_module: Any = None) -> AvatarTray | None:
    """Start the tray icon for ``window``; ``None`` when pystray is missing."""
    if pystray_module is None:
        try:
            import pystray as pystray_module
        except Exception:  # noqa: BLE001 - ImportError, or no display backend
            return None
    tray = AvatarTray(window, pystray_module)
    try:
        tray.start()
    except Exception:  # noqa: BLE001 - no tray is not a broken avatar
        return None
    return tray


def run_window(
    ws_url: str,
    *,
    on_top: bool = True,
    debug: bool = False,
    tray: bool = False,
    echo: Any = None,
    webview_module: Any = None,
    pystray_module: Any = None,
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
    icon = None
    if tray:
        icon = start_tray(window, pystray_module=pystray_module)
        if echo is not None:
            echo(
                "Tray: click the Grandpa icon to show or hide him."
                if icon
                else TRAY_OFF
            )
    try:
        webview_module.start(http_server=True, debug=debug)
    finally:
        if icon is not None:
            icon.stop()


__all__ = [
    "AvatarTray",
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
    "start_tray",
    "TRAY_OFF",
]
