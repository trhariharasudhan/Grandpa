"""Phone access: pairing, device keys, the one-port server, Tailscale calls."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from grandpa.app import phone
from grandpa.app.phone import PHONE_METHODS, DeviceRegistry
from grandpa.app.window import BROWSER_METHODS, WEB_DIR, AppApi


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    return tmp_path


def registry(tmp_path) -> tuple[DeviceRegistry, Clock]:
    clock = Clock()
    return DeviceRegistry(tmp_path / "devices.json", clock=clock), clock


def test_a_code_pairs_one_phone_once(tmp_path) -> None:
    reg, _ = registry(tmp_path)
    code = reg.start_pairing()["code"]
    token = reg.claim(code.lower(), "Android phone")
    assert token and reg.check(token)
    assert reg.claim(code, "again") is None  # one use
    stored = (tmp_path / "devices.json").read_text()
    assert token not in stored  # only a hash is kept
    assert [d["name"] for d in reg.devices()] == ["Android phone"]


def test_codes_expire_and_guessing_ends_them(tmp_path) -> None:
    reg, clock = registry(tmp_path)
    code = reg.start_pairing()["code"]
    clock.now += phone.PAIR_SECONDS + 1
    assert reg.claim(code) is None
    code = reg.start_pairing()["code"]
    for _ in range(phone.PAIR_TRIES):
        assert reg.claim("WRONG000") is None
    assert reg.claim(code) is None  # too many wrong tries: the code is gone
    assert reg.claim(None) is None and reg.claim(123) is None


def test_forget_locks_the_phone_out(tmp_path) -> None:
    reg, _ = registry(tmp_path)
    token = reg.claim(reg.start_pairing()["code"], "Phone")
    device = reg.devices()[0]
    assert reg.forget(device["id"]) and not reg.check(token)
    assert not reg.forget("nope") and not reg.forget(5)
    assert not reg.check("") and not reg.check(None) and not reg.check("x" * 43)


def test_a_phone_gets_a_short_safe_list() -> None:
    assert set(PHONE_METHODS) <= set(BROWSER_METHODS)
    for risky in (
        "mcp_save_server", "mcp_toggle_server", "provider_save", "save_skill",
        "restart_engine", "open_orb", "phone_pair", "phone_share", "pick_files",
    ):
        assert risky not in PHONE_METHODS
    # the phone controls are the PC window's alone
    for name in ("phone_status", "phone_pair", "phone_share", "phone_forget", "phone_set_enabled"):
        assert callable(getattr(AppApi, name)) and name not in BROWSER_METHODS


def test_settings_default_off_and_are_kept() -> None:
    assert phone.load_settings() == {"enabled": False, "port": phone.DEFAULT_PORT}
    phone.save_settings(True)
    assert phone.load_settings()["enabled"] is True


def test_tailscale_status_and_share_use_fixed_arguments() -> None:
    calls: list = []

    def run(args, timeout=10.0):
        calls.append(args)
        if args[1] == "status":
            out = json.dumps({"BackendState": "Running", "Self": {"DNSName": "pc.tail1.ts.net."}})
            return subprocess.CompletedProcess(args, 0, out, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    st = phone.tailscale_status("ts", run=run)
    assert st == {"installed": True, "running": True, "state": "Running", "name": "pc.tail1.ts.net"}
    assert phone.tailscale_share(47710, "ts", run=run) == {"ok": True}
    assert calls[-1] == ["ts", "serve", "--bg", "47710"]  # serve (tailnet only), never funnel
    assert phone.tailscale_share(80, "ts", run=run)["ok"] is False
    assert phone.tailscale_status(None, run=run) if phone.tailscale_cli() else True
    assert phone.pair_link("pc.tail1.ts.net", "ABCD2345") == "https://pc.tail1.ts.net/index.html#pair=ABCD2345"


def test_pairing_needs_tailscale_running(monkeypatch) -> None:
    monkeypatch.setattr(phone, "tailscale_status", lambda: {"installed": False, "running": False, "name": ""})
    assert AppApi().phone_pair()["ok"] is False
    monkeypatch.setattr(phone, "tailscale_status", lambda: {"installed": True, "running": True, "name": "pc.t.ts.net"})
    r = AppApi().phone_pair()
    assert r["ok"] and r["link"].endswith("#pair=" + r["code"])
    if r["qr"]:
        assert r["qr"].startswith("data:image/svg+xml;base64,")


def test_the_phone_page_pairs_and_connects_on_its_own_origin() -> None:
    js = (Path(WEB_DIR) / "app.js").read_text(encoding="utf-8")
    html = (Path(WEB_DIR) / "index.html").read_text(encoding="utf-8")
    assert "/pair/claim?code=" in js and "history.replaceState" in js
    assert '"/avatar?device="' in js and '"wss://"' in js
    assert "connect-src 'self' ws://127.0.0.1:*" in html
    assert 'id="phone-tab"' in html and 'id="phone-pair"' in html


websockets = pytest.importorskip("websockets")


def _server(tmp_path):
    from grandpa.ui.avatar_server import AvatarServer

    reg, _ = registry(tmp_path)
    seen: list = []
    server = AvatarServer(
        on_send=seen.append,
        api=lambda method, args: {"called": method},
        api_methods=("user_name", "provider_save"),
        device_methods=("user_name",),
        device_ok=reg.check,
        pair_claim=reg.claim,
        static_dir=WEB_DIR,
    )
    server.start()
    return server, reg, seen


def _get(port: int, path: str) -> tuple[int, bytes, dict]:
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read()
    headers = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, body, headers


def test_one_port_serves_the_page_and_nothing_else(tmp_path) -> None:
    server, _reg, _ = _server(tmp_path)
    try:
        status, body, headers = _get(server.port, "/")
        assert status == 200 and b"<!doctype html>" in body.lower()
        assert headers["x-frame-options"] == "DENY" and headers["x-content-type-options"] == "nosniff"
        assert _get(server.port, "/app.js")[0] == 200
        for bad in ("/../pyproject.toml", "/%2e%2e/x.js", "/web/app.js", "/.hidden.js", "/x.py", "/app.js/../../a.js"):
            assert _get(server.port, bad)[0] == 404, bad
    finally:
        server.stop()


def test_pairing_over_http_then_a_device_socket(tmp_path) -> None:
    from websockets.sync.client import connect

    server, reg, seen = _server(tmp_path)
    try:
        code = reg.start_pairing()["code"]
        status, body, _ = _get(server.port, "/pair/claim?code=WRONG000&name=x")
        assert status == 403
        status, body, _ = _get(server.port, f"/pair/claim?code={code}&name=Android%20phone")
        token = json.loads(body)["token"]
        assert status == 200 and reg.check(token)

        base = f"ws://127.0.0.1:{server.port}/avatar"
        with connect(f"{base}?device={token}", open_timeout=3) as ws:
            assert json.loads(ws.recv(timeout=3)) == {"type": "api_methods", "methods": ["user_name"]}
            ws.send(json.dumps({"type": "api", "id": 1, "method": "provider_save", "args": []}))
            ws.send(json.dumps({"type": "send", "text": "hello from the phone"}))
            ws.send(json.dumps({"type": "api", "id": 2, "method": "user_name", "args": []}))
            reply = json.loads(ws.recv(timeout=3))
        assert reply["id"] == 2 and reply["ok"]  # provider_save never answered: not allowed
        # the PC's own page keeps its fuller list
        with connect(server.url, open_timeout=3) as ws:
            assert json.loads(ws.recv(timeout=3))["methods"] == ["user_name", "provider_save"]
        for bad in ("", "?device=nope", "?token=nope"):
            with pytest.raises(Exception):
                with connect(base + bad, open_timeout=3):
                    pass
    finally:
        server.stop()
    assert seen == ["hello from the phone"]


def test_a_phone_cannot_open_the_pc_microphone(tmp_path) -> None:
    from websockets.sync.client import connect

    from grandpa.ui.avatar_server import AvatarServer

    reg, _ = registry(tmp_path)
    talks: list = []
    server = AvatarServer(
        on_send=lambda _t: None, on_talk=lambda: talks.append(1), device_ok=reg.check,
        static_dir=WEB_DIR,
    )
    server.start()
    try:
        token = reg.claim(reg.start_pairing()["code"], "Phone")
        with connect(f"ws://127.0.0.1:{server.port}/avatar?device={token}", open_timeout=3) as ws:
            ws.send(json.dumps({"type": "talk"}))
        with connect(server.url, open_timeout=3) as ws:
            ws.send(json.dumps({"type": "talk"}))
        import time

        time.sleep(0.3)
    finally:
        server.stop()
    assert talks == [1]  # only the PC's own page
