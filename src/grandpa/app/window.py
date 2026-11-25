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
MAX_CONTEXT = 8000
MAX_MEMORY = 500


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
        self._devices: Any = None
        self._phone_live = False

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

    def upload_file(self, name: Any, data: Any) -> str | None:
        """Browser mode's Add files: the tab sends the bytes (base64), they are
        saved under ``<grandpa home>/uploads`` and attached like a picked file."""
        path = save_upload(name, data)
        if path is None:
            return None
        if self._session is not None:
            return self._session.allow_file(path)
        return path

    # --- phone access (the PC's own window only; never offered to a phone) ----

    def _phone(self) -> Any:
        if getattr(self, "_devices", None) is None:
            from grandpa.app.phone import DeviceRegistry

            self._devices = DeviceRegistry()
        return self._devices

    def phone_status(self) -> dict[str, Any]:
        from grandpa.app import phone

        settings = phone.load_settings()
        tail = phone.tailscale_status()
        live = getattr(self, "_phone_live", False)
        return {
            "enabled": settings["enabled"],
            "live": bool(live and settings["enabled"]),
            "port": settings["port"],
            "tailscale": tail,
            "address": phone.phone_address(tail.get("name", "")) if tail.get("running") else "",
            "devices": self._phone().devices(),
        }

    def phone_set_enabled(self, on: Any) -> dict[str, Any]:
        from grandpa.app import phone

        if isinstance(on, bool):
            phone.save_settings(on)
        return self.phone_status()

    def phone_share(self) -> dict[str, Any]:
        """Publish the phone port on this tailnet (``tailscale serve``)."""
        from grandpa.app import phone

        return phone.tailscale_share(phone.load_settings()["port"])

    def phone_pair(self) -> dict[str, Any]:
        from grandpa.app import phone

        tail = phone.tailscale_status()
        if not tail.get("running") or not tail.get("name"):
            return {"ok": False, "error": "Turn Tailscale on (and sign in) on this PC first."}
        started = self._phone().start_pairing()
        link = phone.pair_link(tail["name"], started["code"])
        return {
            "ok": True,
            "code": started["code"],
            "expires_in": started["expires_in"],
            "link": link,
            "qr": phone.qr_svg(link),
        }

    def phone_forget(self, device_id: Any) -> bool:
        return self._phone().forget(device_id)

    def user_name(self) -> str:
        return user_name()

    def get_profile(self) -> dict[str, Any]:
        return read_profile()

    def save_profile(self, title: Any, name: Any, email: Any) -> dict[str, Any]:
        return write_profile(title, name, email)

    def set_next_context(self, text: Any) -> bool:
        """Project instructions to go with the next message (one message only)."""
        if self._session is None or not isinstance(text, str):
            return False
        self._session.next_context = text.strip()[:MAX_CONTEXT]
        return True

    def list_memories(self) -> list[dict[str, Any]]:
        return list_memories()

    def forget_memory(self, memory_id: Any) -> bool:
        return forget_memory(memory_id)

    def add_memory(self, text: Any) -> bool:
        return add_memory(text)

    # --- Skills, Connectors, Models & API keys (grandpa.app.manage) ---------

    def list_skills(self) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.list_skills()

    def save_skill(
        self, name: Any, description: Any, instructions: Any
    ) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.save_skill(name, description, instructions)

    def delete_skill(self, name: Any) -> bool:
        from grandpa.app import manage

        return manage.delete_skill(name)

    def import_skill(self) -> dict[str, Any]:
        """Pick a SKILL.md in the file dialog and add it."""
        from grandpa.app import manage

        paths = self.pick_files()
        if not paths:
            return {"ok": False, "error": ""}
        allowed = (
            self._session.picked_files if self._session is not None else set(paths)
        )
        return manage.import_skill(paths[0], allowed)

    def skill_instructions(self, name: Any) -> str:
        from grandpa.app import manage

        return manage.skill_instructions(name)

    def mcp_status(self) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.mcp_status()

    def mcp_save_server(
        self, name: Any, command: Any, allow: Any, keys: Any
    ) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.mcp_save_server(name, command, allow, keys)

    def mcp_remove_server(self, name: Any) -> bool:
        from grandpa.app import manage

        return manage.mcp_remove_server(name)

    def mcp_toggle_server(self, name: Any, enabled: Any) -> bool:
        from grandpa.app import manage

        return manage.mcp_toggle_server(name, enabled)

    def mcp_set_off(self, off: Any) -> bool:
        from grandpa.app import manage

        return manage.mcp_set_off(off)

    def mcp_test(self, name: Any) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.mcp_test(name)

    def providers_status(self) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.providers_status()

    def provider_save(
        self, pid: Any, url: Any, key: Any, models: Any
    ) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.provider_save(pid, url, key, models)

    def provider_remove(self, pid: Any) -> bool:
        from grandpa.app import manage

        return manage.provider_remove(pid)

    def provider_models(self, pid: Any) -> dict[str, Any]:
        from grandpa.app import manage

        return manage.provider_models(pid)

    def restart_engine(self, start_ollama: Any = False) -> dict[str, Any]:
        """Retry after the engine stopped; optionally start Ollama first."""
        if start_ollama is True:
            started = start_ollama_service()
            if started != "ok":
                return {"ok": False, "error": started}
        if self._session is None or not self._session.restart():
            return {"ok": False, "error": "Grandpa is already running."}
        return {"ok": True}

    def open_orb(self) -> str:
        from grandpa.app.launch import launch

        try:
            return launch("avatar")
        except (OSError, ValueError):
            return "failed"


def start_ollama_service(wait: float = 25.0) -> str:
    """Start ``ollama serve`` (hidden, detached) and wait until it answers.

    "ok" when Ollama answers (or already did); otherwise what went wrong, in
    words for the page. Only the fixed command; nothing from the page.
    """
    import shutil
    import subprocess
    import sys
    import time

    import httpx

    def up() -> bool:
        try:
            return (
                httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.5).status_code
                == 200
            )
        except Exception:  # noqa: BLE001
            return False

    if up():
        return "ok"
    exe = shutil.which("ollama")
    if not exe:
        return "Ollama isn't installed. Get it from ollama.com, then press Retry."
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        return f"Couldn't start Ollama: {exc}"
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if up():
            return "ok"
        time.sleep(0.5)
    return "Ollama didn't answer in time. Open the Ollama app, then press Retry."


def list_memories() -> list[dict[str, Any]]:
    """What Grandpa remembers about the user, newest first (as /memory list)."""
    try:
        from grandpa.cli.chat_cmd import _user_facing_memories
        from grandpa.memory_context import MemoryStore

        items = _user_facing_memories(MemoryStore().list_memories(limit=300))
    except Exception:  # noqa: BLE001 - an empty page, never a broken one
        logger.debug("memory list failed", exc_info=True)
        return []
    return [
        {
            "id": int(item.get("id", 0)),
            "category": str(item.get("category", "")),
            "key": str(item.get("key", "")),
            "value": str(item.get("value", "")),
            "updated_at": float(item.get("updated_at") or 0),
        }
        for item in items
    ]


def forget_memory(memory_id: Any) -> bool:
    """Forget exactly one memory, by its id (never a search that could match many)."""
    if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id <= 0:
        return False
    from grandpa.memory_context import MemoryStore

    return MemoryStore().forget(str(memory_id)) == 1


def add_memory(text: Any) -> bool:
    """Remember a note the user typed on the Memory page."""
    if not isinstance(text, str):
        return False
    value = " ".join(text.split())[:MAX_MEMORY]
    if not value:
        return False
    import hashlib

    from grandpa.memory_context import MemoryStore

    key = "note_" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    MemoryStore().remember("note", key, value, source="app")
    return True


def bind_file_drop(window: Any, session: Any) -> bool:
    """Files dropped on the window: their real paths go to the page.

    pywebview adds ``pywebviewFullPath`` to a drop event's files; a dropped
    file counts as chosen by the user, like one picked in the dialog.
    """
    try:
        from webview.dom import DOMEventHandler
    except Exception:  # noqa: BLE001 - old pywebview: the + menu still works
        return False

    def ignore(_event: Any) -> None:
        return None

    def on_drop(event: Any) -> None:
        try:
            files = (event or {}).get("dataTransfer", {}).get("files", []) or []
            paths = [str(f.get("pywebviewFullPath") or "") for f in files][:MAX_PICK]
            paths = [session.allow_file(p) for p in paths if p]
        except Exception:  # noqa: BLE001
            logger.debug("drop failed", exc_info=True)
            return
        if paths:
            window.evaluate_js(
                f"window.grandpaDropped && window.grandpaDropped({json.dumps(paths)});"
            )

    events = window.dom.document.events
    events.dragover += DOMEventHandler(ignore, True, True, debounce=500)
    events.drop += DOMEventHandler(on_drop, True, True)
    return True


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


MAX_UPLOAD = 10 * 1024 * 1024
"""Largest file a browser tab may send (bytes, after decoding)."""

BROWSER_METHODS: tuple[str, ...] = (
    "upload_file", "user_name", "get_profile", "save_profile", "set_next_context",
    "list_memories", "forget_memory", "add_memory",
    "list_skills", "save_skill", "delete_skill", "skill_instructions",
    "mcp_status", "mcp_save_server", "mcp_remove_server", "mcp_toggle_server",
    "mcp_set_off", "mcp_test",
    "providers_status", "provider_save", "provider_remove", "provider_models",
    "restart_engine", "open_orb",
)
"""What a browser tab may call. Not the native dialogs (``pick_files``,
``import_skill``): they would open on the PC, behind the browser."""


def save_upload(name: Any, data: Any) -> str | None:
    """Write one uploaded file; ``None`` for a bad name, bad data or too big."""
    import base64
    import binascii
    import re
    import time

    if not isinstance(name, str) or not isinstance(data, str):
        return None
    if len(data) > MAX_UPLOAD * 4 // 3 + 8:
        return None
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ()]", "_", base).strip(" .")[:120]
    if not base:
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > MAX_UPLOAD:
        return None
    from grandpa.runtime_paths import grandpa_home

    folder = grandpa_home() / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{base}"
    target.write_bytes(raw)
    return str(target)


def browser_dispatch(api: "AppApi") -> Callable[[str, list], Any]:
    """The browser tab's way in: whitelisted method names only."""

    def call(method: str, args: list) -> Any:
        if method not in BROWSER_METHODS:
            raise ValueError("not allowed")
        return getattr(api, method)(*args)

    return call


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


def clear_page_cache(folder: Path) -> None:
    """Forget the cached copies of the page, so an update shows at once.

    The window keeps its storage between runs (that is where the chat list
    lives), and with it WebView2's HTTP cache: after ``git pull`` the window
    could still show yesterday's page. Only the caches go; Local Storage (the
    chats) stays.
    """
    for profile in folder.glob("EBWebView/*/"):
        for name in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
            target = profile / name
            if not target.is_dir():
                continue
            # deepest first, by full path (a file in use stays; that's fine)
            for path in sorted(
                target.rglob("*"), key=lambda p: len(p.parts), reverse=True
            ):
                try:
                    path.rmdir() if path.is_dir() and not path.is_symlink() else path.unlink()
                except OSError:
                    pass
            try:
                target.rmdir()
            except OSError:
                pass


def _storage_dir() -> str | None:
    """Where the window keeps the chat list (localStorage) between runs."""
    try:
        from grandpa.runtime_paths import grandpa_home

        folder = grandpa_home() / "app_webview"
        folder.mkdir(parents=True, exist_ok=True)
        clear_page_cache(folder)
        return str(folder)
    except Exception:  # noqa: BLE001
        return None


def run(
    *,
    chat_args: list[str] | None = None,
    browser: bool = False,
    open_browser: bool = False,
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
    api = AppApi(session)
    extra: dict[str, Any] = {}
    phone_extra: dict[str, Any] = {}
    from grandpa.app import phone

    phone_settings = phone.load_settings()
    if phone_settings["enabled"]:
        # One fixed loopback port for page and socket; tailscale serve
        # publishes it to your own devices. Nothing listens on the network.
        phone_extra = {
            "api": browser_dispatch(api),
            "device_methods": phone.PHONE_METHODS,
            "device_ok": api._phone().check,
            "pair_claim": api._phone().claim,
            "static_dir": WEB_DIR,
            "port": phone_settings["port"],
            "max_frame": MAX_UPLOAD * 4 // 3 + 4096,
        }
    if browser:
        # The tab has no pywebview bridge, so the same methods go over the
        # (token-protected, loopback) socket instead.
        extra.update(
            api=browser_dispatch(api),
            api_methods=BROWSER_METHODS,
            max_frame=MAX_UPLOAD * 4 // 3 + 4096,
        )

    def make_server(with_phone: bool) -> Any:
        return AvatarServer(
            on_send=session.send,
            on_talk=session.talk,
            on_cancel=session.cancel,
            snapshot=session.snapshot,
            **{**(phone_extra if with_phone else {}), **extra},
        )

    server = make_server(bool(phone_extra))
    holder["server"] = server
    try:
        server.start(timeout=20)
        api._phone_live = bool(phone_extra)
    except RuntimeError:
        if not phone_extra:
            raise
        # the phone port is taken (another copy?): run without phone access
        echo(f"Phone access: port {phone_settings['port']} is busy; starting without it.")
        server.stop()
        server = make_server(False)
        holder["server"] = server
        server.start(timeout=20)
    session.start()

    try:
        if browser:
            _page, port = serve_page()
            echo("Grandpa app: open this address in your browser:")
            address = browser_address(server.url, port)
            echo("  " + address)
            if open_browser:
                import webbrowser

                webbrowser.open(address)
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
            js_api=api,
            width=SIZE[0],
            height=SIZE[1],
            min_size=MIN_SIZE,
            background_color=BACKGROUND,
        )
        # Without this the 📎 dialog had no window to open on and quietly did
        # nothing -- the "attaching doesn't work" Captain saw.
        api._set_window(window, webview_module)
        dropping: dict[str, bool] = {}

        def _loaded(*_a: Any) -> None:
            window.evaluate_js(connect_script(server.url))
            if not dropping:
                try:
                    dropping["on"] = bind_file_drop(window, session)
                except Exception:  # noqa: BLE001 - drag and drop is a nicety
                    logger.debug("drop binding failed", exc_info=True)

        window.events.loaded += _loaded
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


__all__ = ["BROWSER_METHODS", "INDEX", "WEB_DIR", "browser_address", "browser_dispatch", "save_upload", "connect_script", "run", "serve_page"]
