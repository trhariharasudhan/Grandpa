"""A3b: the committed Wise Grandpa model passes the A3 checks.

Guards assets/avatar/grandpa.glb: if a re-export breaks the budget, embeds an
outside file, or loses a shape key, this fails before `grandpa avatar` silently
falls back to the placeholder head.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from grandpa.ui.avatar_character import (
    MAX_TRIANGLES,
    RELATIVE_PATH,
    SHAPE_KEYS,
    inspect_glb,
)

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parents[2]
GLB = REPO / RELATIVE_PATH
BUILD_SCRIPT = REPO / "assets" / "avatar" / "source" / "build_grandpa_avatar.py"


def _gltf_json(data: bytes) -> dict:
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + length])


@pytest.fixture(scope="module")
def glb_bytes() -> bytes:
    if not GLB.is_file():
        pytest.skip("assets/avatar/grandpa.glb is not in this checkout")
    return GLB.read_bytes()


def test_model_passes_the_a3_check(glb_bytes: bytes) -> None:
    report = inspect_glb(glb_bytes, GLB)
    assert report.ok, report.reason
    assert 0 < report.triangles <= MAX_TRIANGLES


def test_model_has_every_shape_key(glb_bytes: bytes) -> None:
    report = inspect_glb(glb_bytes, GLB)
    assert report.missing_keys == ()


def test_shape_keys_rest_at_zero(glb_bytes: bytes) -> None:
    # Blender 5.x creates new shape keys at 1.0; exported like that, every
    # expression would be on at once and Grandpa would load mid-scream.
    gltf = _gltf_json(glb_bytes)
    for mesh in gltf["meshes"]:
        for weight in mesh.get("weights") or []:
            assert weight == 0


def test_head_mesh_is_named_for_the_viewer(glb_bytes: bytes) -> None:
    # The face shape keys live on one node the viewer can find (and frame) by name.
    gltf = _gltf_json(glb_bytes)
    nodes = {node.get("name") for node in gltf["nodes"]}
    assert "Grandpa_Head" in nodes
    head = next(n for n in gltf["nodes"] if n.get("name") == "Grandpa_Head")
    names = gltf["meshes"][head["mesh"]]["extras"]["targetNames"]
    assert tuple(names) == SHAPE_KEYS


def test_build_script_matches_the_checker() -> None:
    # The Blender script keeps its own copy of the rules; keep them in step.
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert f"MAX_TRIANGLES = {MAX_TRIANGLES:_}" in source
    assert repr(SHAPE_KEYS).replace("'", '"') in source


def test_body_textures_are_embedded(glb_bytes: bytes) -> None:
    # Normal map + AO colour baked in stage_bake, stored inside the .glb.
    gltf = _gltf_json(glb_bytes)
    images = gltf.get("images") or []
    assert len(images) >= 2
    assert all("bufferView" in img and "uri" not in img for img in images)
    body = next(n for n in gltf["nodes"] if n.get("name") == "Grandpa_Body")
    prims = gltf["meshes"][body["mesh"]]["primitives"]
    material = gltf["materials"][prims[0]["material"]]
    assert "normalTexture" in material
    assert "baseColorTexture" in material["pbrMetallicRoughness"]


def test_viewer_frames_the_head_node() -> None:
    # character.js frames head-and-chest on this node name; keep them in step.
    js = (REPO / "src" / "grandpa" / "ui" / "avatar_web" / "character.js").read_text(
        encoding="utf-8"
    )
    assert 'const FRAME_NODE = "Grandpa_Head";' in js
    assert '"Grandpa_Head"' in BUILD_SCRIPT.read_text(encoding="utf-8")
