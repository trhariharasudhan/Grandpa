"""A3: the character pipeline -- the placeholder head, and Captain's grandpa.glb.

Python's half is tested for real: the .glb check (format, triangle budget,
shape keys, embedded only) and the socket delivering the checked file to a page
holding the token. The page's half is checked as written (budget constants,
imports, CSP) and was rendered in headless Chromium for the PR; WebView2 and
the Radeon iGPU are Captain's to see.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from grandpa.ui.avatar_character import (
    ENV_PATH,
    MAX_TRIANGLES,
    RELATIVE_PATH,
    SHAPE_KEYS,
    candidate_paths,
    inspect_glb,
    load_character,
)
from grandpa.ui.avatar_states import AvatarState
from grandpa.ui.avatar_window import INDEX, WEB_DIR, ensure_js_mime

pytestmark = pytest.mark.core

VENDOR = WEB_DIR / "vendor" / "three"


def make_glb(
    *,
    triangles: int = 100,
    targets: tuple[str, ...] = (),
    version: int = 2,
    extra: dict | None = None,
    indexed: bool = True,
) -> bytes:
    """A structurally valid .glb: one mesh, one primitive, a stub BIN chunk."""
    accessors = [{"count": triangles * 3, "componentType": 5126, "type": "VEC3"}]
    prim: dict = {"attributes": {"POSITION": 0}}
    if indexed:
        accessors.append(
            {"count": triangles * 3, "componentType": 5123, "type": "SCALAR"}
        )
        prim["indices"] = 1
    mesh: dict = {"primitives": [prim]}
    if targets:
        mesh["extras"] = {"targetNames": list(targets)}
    gltf = {"asset": {"version": "2.0"}, "meshes": [mesh], "accessors": accessors}
    gltf.update(extra or {})
    body = json.dumps(gltf).encode("utf-8")
    body += b" " * (-len(body) % 4)
    binary = b"\0" * 8
    total = 12 + 8 + len(body) + 8 + len(binary)
    return (
        b"glTF"
        + struct.pack("<II", version, total)
        + struct.pack("<II", len(body), 0x4E4F534A)
        + body
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


# --- the .glb check -------------------------------------------------------------


def test_a_model_within_budget_with_every_shape_key_is_used() -> None:
    report = inspect_glb(make_glb(triangles=12_000, targets=SHAPE_KEYS))
    assert report.ok, report.reason
    assert report.triangles == 12_000
    assert report.missing_keys == ()


def test_missing_shape_keys_are_reported_not_fatal() -> None:
    report = inspect_glb(make_glb(targets=("blink", "Smile")), Path("grandpa.glb"))
    assert report.ok
    assert "blink" not in report.missing_keys and "smile" not in report.missing_keys
    assert set(report.missing_keys) == {"AA", "E", "I", "O", "U", "FV", "MBP", "think"}
    assert "Missing shape keys: AA, E, I, O, U, FV, MBP, think." in report.describe()


def test_non_indexed_triangles_are_counted_too() -> None:
    assert inspect_glb(make_glb(triangles=500, indexed=False)).triangles == 500


def test_over_the_triangle_budget_is_refused() -> None:
    report = inspect_glb(make_glb(triangles=MAX_TRIANGLES + 1), Path("grandpa.glb"))
    assert not report.ok
    assert "30,001 triangles" in report.reason and "decimate" in report.reason
    assert report.describe().startswith(
        "Character: the placeholder head; grandpa.glb was not used"
    )


@pytest.mark.parametrize(
    ("data", "words"),
    [
        (b"not a model at all, just some text", "not a binary glTF"),
        (make_glb(version=1), "glTF version 1"),
        (make_glb()[:-4], "truncated"),
        (make_glb(triangles=0), "no triangle meshes"),
        (
            make_glb(extra={"buffers": [{"uri": "grandpa.bin", "byteLength": 8}]}),
            "outside files",
        ),
        (make_glb(extra={"images": [{"uri": "C:/Users/skin.png"}]}), "outside images"),
    ],
)
def test_a_file_that_is_not_a_self_contained_glb_is_refused(
    data: bytes, words: str
) -> None:
    report = inspect_glb(data)
    assert not report.ok
    assert words in report.reason


def test_without_a_model_the_placeholder_head_is_used(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(ENV_PATH, raising=False)
    monkeypatch.setattr(
        "grandpa.ui.avatar_character.candidate_paths",
        lambda cwd=None: [tmp_path / RELATIVE_PATH],
    )
    data, report = load_character(tmp_path)
    assert data is None and report.path is None
    assert "placeholder head" in report.describe()
    assert "assets/avatar/grandpa.glb" in report.describe()


def test_a_model_in_the_current_folder_is_loaded(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(ENV_PATH, raising=False)
    target = tmp_path / RELATIVE_PATH
    target.parent.mkdir(parents=True)
    glb = make_glb(triangles=2_000, targets=("blink",))
    target.write_bytes(glb)
    data, report = load_character(tmp_path)
    assert data == glb
    assert report.ok and report.path == target
    assert "grandpa.glb, 2,000 triangles" in report.describe()


def test_a_bad_model_is_not_sent(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "huge.glb"
    bad.write_bytes(make_glb(triangles=MAX_TRIANGLES * 2))
    monkeypatch.setenv(ENV_PATH, str(bad))
    data, report = load_character(tmp_path)
    assert data is None
    assert report.path == bad and not report.ok


def test_the_override_is_looked_at_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(ENV_PATH, str(tmp_path / "mine.glb"))
    paths = candidate_paths(tmp_path)
    assert paths[0] == tmp_path / "mine.glb"
    assert paths[1] == tmp_path / RELATIVE_PATH


# --- the socket delivers it, only to a page with the token ----------------------------


def test_a_page_gets_the_checked_model_after_the_snapshot() -> None:
    from websockets.sync.client import connect

    from grandpa.cli.avatar_cmd import build

    glb = make_glb(triangles=300, targets=("blink",))
    _controller, server = build(bridge=object())
    server.character = glb
    server.start()
    try:
        with connect(server.url, open_timeout=3, max_size=None) as ws:
            first = json.loads(ws.recv(timeout=3))
            assert first["type"] == "state"
            announce = json.loads(ws.recv(timeout=3))
            assert announce == {"type": "character", "v": 1, "bytes": len(glb)}
            assert ws.recv(timeout=3) == glb
    finally:
        server.stop()


def test_without_a_model_nothing_binary_is_sent() -> None:
    from websockets.sync.client import connect

    from grandpa.cli.avatar_cmd import build

    _controller, server = build(bridge=object())
    server.start()
    try:
        with connect(server.url, open_timeout=3) as ws:
            assert json.loads(ws.recv(timeout=3))["type"] == "state"
            with pytest.raises(TimeoutError):
                ws.recv(timeout=0.3)
    finally:
        server.stop()


# --- the page -------------------------------------------------------------------


def _js(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def test_the_character_module_loads_after_the_page_script() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert '<canvas id="char-gl" aria-hidden="true"></canvas>' in html
    assert html.index('src="avatar.js"') < html.index(
        '<script type="module" src="character.js">'
    )


def test_the_csp_still_allows_only_this_page_and_loopback() -> None:
    html = INDEX.read_text(encoding="utf-8")
    csp = re.search(r'content="(default-src[^"]+)"', html).group(1)
    assert "default-src 'none'" in csp
    assert "script-src 'self';" in csp
    assert "unsafe" not in csp
    # blob: is for textures embedded in the .glb, nothing from the network
    assert "connect-src ws://127.0.0.1:* blob:;" in csp


def test_the_character_imports_only_the_vendored_three() -> None:
    js = _js("character.js")
    imports = re.findall(r'^import .* from "([^"]+)";', js, flags=re.M)
    assert imports == [
        "./vendor/three/three.module.min.js",
        "./vendor/three/GLTFLoader.js",
    ]
    for name in ("GLTFLoader.js", "BufferGeometryUtils.js"):
        text = (VENDOR / name).read_text(encoding="utf-8")
        assert "from 'three'" not in text
        for spec in re.findall(r"^(?:import|\}) .*?from '([^']+)';", text, flags=re.M):
            assert spec.startswith("./"), (name, spec)
    for forbidden in ("fetch(", "innerHTML", "eval(", "http://", "https://"):
        assert forbidden not in js, forbidden


def test_vendored_three_is_pinned() -> None:
    sums = {}
    for line in (VENDOR / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        sums[name] = digest
    assert set(sums) == {
        "three.module.min.js",
        "GLTFLoader.js",
        "BufferGeometryUtils.js",
        "LICENSE",
    }
    for name, digest in sums.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name
    assert "MIT License" in (VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert 'const t="169"' in (VENDOR / "three.module.min.js").read_text(
        encoding="utf-8"
    )


def test_the_character_keeps_to_its_budget() -> None:
    js = _js("character.js")
    assert "const FRAME_MS = 1000 / 30;" in js
    assert "const MAX_DPR = 2;" in js
    assert f"const MAX_TRIANGLES = {MAX_TRIANGLES};" in js
    assert 'powerPreference: "low-power"' in js and "antialias: false" in js
    assert "document.hidden" in js and "visibilitychange" in js
    # it draws only while shown or morphing; the ring is paused while it shows
    assert "if (!shown && !morphing())" in js
    assert "if (document.hidden)" in js
    assert "ring.setPaused(true)" in js and "ring.setPaused(false)" in js
    assert "function setPaused(value)" in _js("ring.js")


def test_the_character_shows_only_in_active_states() -> None:
    js = _js("character.js")
    shown = set(
        re.search(r"const SHOW_IN = new Set\(\[([^\]]+)\]\)", js)
        .group(1)
        .replace('"', "")
        .replace(" ", "")
        .split(",")
    )
    assert shown == {"thinking", "speaking", "working", "confirm"}
    assert shown <= {str(s) for s in AvatarState}
    # the ring stays for idle, listening, done and error
    assert not shown & {"idle", "listening", "done", "error"}


def test_the_character_breathes_and_blinks_both_ways() -> None:
    js = _js("character.js")
    assert "BLINK_MS" in js and "setBlink" in js
    assert 'name.toLowerCase() === "blink"' in js  # a .glb blinks with its shape key
    assert "Math.sin(t * 1.6)" in js  # breathing


def test_binary_frames_reach_the_character() -> None:
    js = _js("avatar.js")
    assert 'socket.binaryType = "arraybuffer";' in js
    assert 'new CustomEvent("grandpa:character"' in js
    assert 'new CustomEvent("grandpa:state"' in js


def test_js_is_served_as_javascript(monkeypatch) -> None:
    import mimetypes

    monkeypatch.setitem(mimetypes.types_map, ".js", "text/plain")  # a bad registry
    ensure_js_mime()
    assert mimetypes.guess_type("character.js")[0] == "text/javascript"


# --- A5: the ring <-> character morph -------------------------------------------


def _block(js: str, start: str) -> str:
    body = js[js.index(start) :]
    return body[: body.index("\n  }\n")]


def test_the_morph_is_inside_600_ms() -> None:
    js = _js("character.js")
    ms = int(re.search(r"const MORPH_MS = (\d+);", js).group(1))
    # one frame at 30 fps can land on top before the morph is seen to end
    assert 0 < ms and ms + 1000 / 30 < 600


def test_one_clock_drives_both_canvases() -> None:
    js = _js("character.js")
    body = _block(js, "function applyMorph(m)")
    assert "canvas.style.opacity = String(m)" in body
    assert "ringCanvas.style.opacity = String(1 - m)" in body
    # CSS runs no timer of its own for the swap, so the two cannot drift
    css = (WEB_DIR / "avatar.css").read_text(encoding="utf-8")
    assert "transition" not in css[css.index("/* A3: the character") :]


def test_the_ring_pauses_only_after_the_morph_and_returns_at_once() -> None:
    js = _js("character.js")
    settle = _block(js, "function settle(now)")
    assert "morph.to === 1" in settle and "ring.setPaused(true)" in settle
    assert 'app.classList.remove("char")' in settle
    show = _block(js, "function show(value)")
    assert "ring.setPaused(false)" in show  # back: the ring draws from the first frame
    assert "ring.setPaused(true)" not in show  # in: not before the morph has ended


def test_reduced_motion_or_a_hidden_page_ends_a_morph_at_once() -> None:
    js = _js("character.js")
    assert "reduceMotion || document.hidden ? 1" in js
    # the character canvas shows only once WebGL works; a lost context drops it
    assert 'app.classList.add("char-ready")' in js
    assert 'app.classList.remove("char", "char-ready")' in js
    css = (WEB_DIR / "avatar.css").read_text(encoding="utf-8")
    assert ".char-ready #char-gl { display: block; }" in css
