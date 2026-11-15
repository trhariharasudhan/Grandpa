"""A3: which 3D character the avatar shows, and whether Captain's model fits.

The page always has a character: a small procedural low-poly head (breathing
and blinking) drawn by ``character.js``. When ``assets/avatar/grandpa.glb``
exists -- Captain models it in Blender -- Python reads it, checks it, and sends
it to the page over the avatar's own WebSocket as one binary frame. It is not
put on a file server, so it needs no new port, route or CSP rule, and only a
page holding the per-run token ever gets it.

What is checked, before a single byte goes to the page:

* it is a binary glTF 2.0 file (the ``glTF`` magic, version 2, a JSON chunk);
* it is at most :data:`MAX_BYTES`;
* it has at most :data:`MAX_TRIANGLES` triangles (the A3 budget for the
  Ryzen 5 7520U's integrated GPU, which Ollama is also using);
* which of the shape keys A4/A6 animate are present (:data:`SHAPE_KEYS`).
  Missing ones are reported, not fatal: blink and breathing still work.

A file that fails is not sent; the placeholder head stays and ``grandpa
avatar`` prints why. Nothing here downloads or generates a character.
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

RELATIVE_PATH = Path("assets") / "avatar" / "grandpa.glb"
"""Where Captain's model goes, relative to the repo (or the current folder)."""

ENV_PATH = "GRANDPA_AVATAR_GLB"
"""Optional override: the full path of a ``.glb`` to use instead."""

MAX_BYTES = 12 * 1024 * 1024
MAX_TRIANGLES = 30_000

SHAPE_KEYS: tuple[str, ...] = (
    "AA",
    "E",
    "I",
    "O",
    "U",
    "FV",
    "MBP",
    "smile",
    "think",
    "blink",
)
"""Shape keys (glTF morph targets) the character pipeline animates."""

_GLB_MAGIC = b"glTF"
_CHUNK_JSON = 0x4E4F534A
_TRIANGLES = 4
_TRIANGLE_STRIP = 5
_TRIANGLE_FAN = 6


@dataclass(frozen=True)
class CharacterReport:
    """What ``grandpa avatar`` says about the character it will show."""

    path: Path | None
    ok: bool
    reason: str = ""
    triangles: int = 0
    shape_keys: tuple[str, ...] = field(default_factory=tuple)

    @property
    def missing_keys(self) -> tuple[str, ...]:
        have = {key.lower() for key in self.shape_keys}
        return tuple(key for key in SHAPE_KEYS if key.lower() not in have)

    def describe(self) -> str:
        if self.path is None:
            return (
                "Character: the placeholder head "
                f"(put your model at {RELATIVE_PATH.as_posix()} to use it)."
            )
        if not self.ok:
            return f"Character: the placeholder head; {self.path.name} was not used: {self.reason}"
        line = (
            f"Character: {self.path.name}, {self.triangles:,} triangles "
            f"(budget {MAX_TRIANGLES:,})."
        )
        if self.missing_keys:
            line += " Missing shape keys: " + ", ".join(self.missing_keys) + "."
        return line


def candidate_paths(cwd: Path | None = None) -> list[Path]:
    """Where to look, first match wins: the env override, the current folder, the repo."""
    paths: list[Path] = []
    override = os.environ.get(ENV_PATH, "").strip()
    if override:
        paths.append(Path(override).expanduser())
    paths.append((cwd or Path.cwd()) / RELATIVE_PATH)
    # src/grandpa/ui/avatar_character.py -> the repo root, in an editable install
    repo = Path(__file__).resolve().parents[3]
    paths.append(repo / RELATIVE_PATH)
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def find_character(cwd: Path | None = None) -> Path | None:
    for path in candidate_paths(cwd):
        if path.is_file():
            return path
    return None


def _triangles(gltf: dict) -> int:
    accessors = gltf.get("accessors") or []
    total = 0
    meshes = gltf.get("meshes") or []
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            mode = prim.get("mode", _TRIANGLES)
            index = prim.get("indices")
            if index is None:
                index = (prim.get("attributes") or {}).get("POSITION")
            if not isinstance(index, int) or not 0 <= index < len(accessors):
                continue
            count = int(accessors[index].get("count", 0))
            if mode == _TRIANGLES:
                total += count // 3
            elif mode in (_TRIANGLE_STRIP, _TRIANGLE_FAN):
                total += max(0, count - 2)
    return total


def _shape_keys(gltf: dict) -> tuple[str, ...]:
    names: list[str] = []
    for mesh in gltf.get("meshes") or []:
        targets = (mesh.get("extras") or {}).get("targetNames") or []
        for name in targets:
            if isinstance(name, str) and name not in names:
                names.append(name)
    return tuple(names)


def inspect_glb(data: bytes, path: Path | None = None) -> CharacterReport:
    """Check a ``.glb`` file's bytes against the A3 budget."""
    if len(data) > MAX_BYTES:
        return CharacterReport(
            path,
            False,
            f"it is {len(data) // (1024 * 1024)} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB.",
        )
    if len(data) < 20 or data[:4] != _GLB_MAGIC:
        return CharacterReport(path, False, "it is not a binary glTF (.glb) file.")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        return CharacterReport(
            path, False, f"it is glTF version {version}; export glTF 2.0."
        )
    if length != len(data):
        return CharacterReport(path, False, "the file is truncated or damaged.")
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != _CHUNK_JSON or 20 + chunk_length > len(data):
        return CharacterReport(path, False, "the file is truncated or damaged.")
    try:
        gltf = json.loads(data[20 : 20 + chunk_length].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return CharacterReport(path, False, "its glTF description is not valid JSON.")
    if not isinstance(gltf, dict):
        return CharacterReport(path, False, "its glTF description is not valid JSON.")
    for buffer in gltf.get("buffers") or []:
        if isinstance(buffer, dict) and "uri" in buffer:
            return CharacterReport(
                path,
                False,
                "it refers to outside files; export as one .glb with everything embedded.",
            )
    for image in gltf.get("images") or []:
        if isinstance(image, dict) and "uri" in image:
            return CharacterReport(
                path,
                False,
                "it refers to outside images; export as one .glb with textures embedded.",
            )
    triangles = _triangles(gltf)
    keys = _shape_keys(gltf)
    if triangles == 0:
        return CharacterReport(path, False, "it has no triangle meshes.", 0, keys)
    if triangles > MAX_TRIANGLES:
        return CharacterReport(
            path,
            False,
            f"it has {triangles:,} triangles; the budget is {MAX_TRIANGLES:,} (decimate it in Blender).",
            triangles,
            keys,
        )
    return CharacterReport(path, True, "", triangles, keys)


def load_character(cwd: Path | None = None) -> tuple[bytes | None, CharacterReport]:
    """The bytes to send to the page (``None`` = placeholder head) and the report."""
    path = find_character(cwd)
    if path is None:
        return None, CharacterReport(None, False)
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            return None, CharacterReport(
                path,
                False,
                f"it is {size // (1024 * 1024)} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB.",
            )
        data = path.read_bytes()
    except OSError as exc:
        return None, CharacterReport(
            path, False, f"it could not be read ({exc.strerror or exc})."
        )
    report = inspect_glb(data, path)
    return (data if report.ok else None), report


__all__ = [
    "CharacterReport",
    "ENV_PATH",
    "MAX_BYTES",
    "MAX_TRIANGLES",
    "RELATIVE_PATH",
    "SHAPE_KEYS",
    "candidate_paths",
    "find_character",
    "inspect_glb",
    "load_character",
]
