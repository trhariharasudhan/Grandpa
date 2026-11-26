"""Browser mode of the desktop app: the page's API over the socket."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from grandpa.app import window as app_window
from grandpa.app.window import BROWSER_METHODS, AppApi, browser_dispatch, save_upload
from grandpa.ui.avatar_server import parse_api

WEB = Path(app_window.WEB_DIR)


def test_only_whitelisted_methods_parse() -> None:
    allowed = ("list_skills",)
    ok = json.dumps({"type": "api", "id": 3, "method": "list_skills", "args": []})
    assert parse_api(ok, allowed) == (3, "list_skills", [])
    for bad in (
        {"type": "api", "id": 3, "method": "pick_files", "args": []},
        {"type": "api", "id": 3, "method": "_set_window", "args": []},
        {"type": "api", "id": "3", "method": "list_skills", "args": []},
        {"type": "api", "id": True, "method": "list_skills", "args": []},
        {"type": "api", "id": 3, "method": "list_skills", "args": {"a": 1}},
        {"type": "api", "id": 3, "method": "list_skills", "args": list(range(20))},
        {"type": "send", "text": "hi"},
    ):
        assert parse_api(json.dumps(bad), allowed) is None
    assert parse_api("not json", allowed) is None


def test_the_tab_cannot_reach_native_dialogs_or_private_parts() -> None:
    for name in BROWSER_METHODS:
        assert not name.startswith("_")
        assert callable(getattr(AppApi, name)), name
    assert "pick_files" not in BROWSER_METHODS
    assert "import_skill" not in BROWSER_METHODS
    call = browser_dispatch(AppApi())
    with pytest.raises(ValueError):
        call("pick_files", [])
    with pytest.raises(ValueError):
        call("_set_window", [None])


def test_an_upload_is_saved_and_attached(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    class Session:
        def __init__(self) -> None:
            self.allowed: list[str] = []

        def allow_file(self, path: str) -> str:
            self.allowed.append(path)
            return path

    session = Session()
    data = base64.b64encode(b"mango").decode()
    path = AppApi(session).upload_file("..\\..\\evil/notes.txt", data)
    assert path is not None and session.allowed == [path]
    saved = Path(path)
    assert saved.parent == tmp_path / "uploads"
    assert saved.name.endswith("-notes.txt") and saved.read_bytes() == b"mango"


def test_bad_uploads_are_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    assert save_upload("a.txt", "!!not base64!!") is None
    assert save_upload("", base64.b64encode(b"x").decode()) is None
    assert save_upload(5, "eA==") is None
    too_big = base64.b64encode(b"x" * (app_window.MAX_UPLOAD + 1)).decode()
    assert save_upload("big.bin", too_big) is None


def test_the_page_builds_its_api_from_the_socket() -> None:
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'msg.type === "api_methods"' in js and 'msg.type === "api_result"' in js
    assert "a.upload_file(" in js and "readAsDataURL" in js
    assert "failCalls()" in js


websockets = pytest.importorskip("websockets")


def test_a_tab_calls_the_api_and_gets_only_its_own_answer() -> None:
    from websockets.sync.client import connect

    from grandpa.ui.avatar_server import AvatarServer

    seen: list[tuple[str, list]] = []

    def api(method: str, args: list):
        seen.append((method, args))
        return {"echo": args}

    server = AvatarServer(on_send=lambda _t: None, api=api, api_methods=("user_name",))
    server.start()
    try:
        with connect(server.url, open_timeout=3) as ws:
            hello = json.loads(ws.recv(timeout=3))
            assert hello == {"type": "api_methods", "methods": ["user_name"]}
            ws.send(json.dumps({"type": "api", "id": 7, "method": "user_name", "args": [1]}))
            reply = json.loads(ws.recv(timeout=3))
            ws.send(json.dumps({"type": "api", "id": 8, "method": "forget_memory", "args": [1]}))
    finally:
        server.stop()
    assert reply == {"type": "api_result", "id": 7, "ok": True, "value": {"echo": [1]}}
    assert seen == [("user_name", [1])]


def test_the_orb_server_offers_no_api() -> None:
    from websockets.sync.client import connect

    from grandpa.ui.avatar_server import AvatarServer

    sent: list[str] = []
    server = AvatarServer(on_send=sent.append)
    server.start()
    try:
        with connect(server.url, open_timeout=3) as ws:
            ws.send(json.dumps({"type": "api", "id": 1, "method": "user_name", "args": []}))
            with pytest.raises(TimeoutError):
                ws.recv(timeout=0.5)
    finally:
        server.stop()
    assert sent == []
