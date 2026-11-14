"""Fetch the voice runtime's FFmpeg build, verified against a pinned SHA-256.

FFmpeg used to be committed under ``voice_runtime/tools`` (a 62 MB zip plus its
217 extracted files). It is now downloaded on setup instead:

* the URL is read from ``voice_runtime/diagnostics/ffmpeg_asset_url.txt``;
* the expected checksum from ``voice_runtime/diagnostics/ffmpeg_asset.sha256``;
* the zip lands in ``voice_runtime/tools/`` and is extracted next to it, which is
  exactly where ``run_service._find_ffmpeg`` already looks.

Nothing is extracted unless the checksum matches. An ``ffmpeg`` already on PATH,
or an already extracted ``ffmpeg.exe`` under ``tools/``, means there is nothing
to do. Standard library only, so it runs before any venv exists.

Usage::

    python voice_runtime/scripts/fetch_ffmpeg.py [--force] [--zip PATH]

``--zip`` verifies and extracts a zip you downloaded yourself.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
URL_FILE = RUNTIME_ROOT / "diagnostics" / "ffmpeg_asset_url.txt"
SHA_FILE = RUNTIME_ROOT / "diagnostics" / "ffmpeg_asset.sha256"
TOOLS_DIR = RUNTIME_ROOT / "tools"
ZIP_NAME = "ffmpeg-7.1-lgpl-shared.zip"
EXTRACT_DIR_NAME = "ffmpeg-7.1-lgpl-shared"


class FetchError(RuntimeError):
    pass


def read_pin(url_file: Path = URL_FILE, sha_file: Path = SHA_FILE) -> tuple[str, str]:
    url = url_file.read_text(encoding="utf-8").strip()
    sha = sha_file.read_text(encoding="utf-8").split()[0].strip().lower()
    if not url.startswith("https://"):
        raise FetchError(f"refusing non-https FFmpeg URL: {url!r}")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise FetchError(f"{sha_file} does not hold a SHA-256")
    return url, sha


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def existing_ffmpeg(tools_dir: Path = TOOLS_DIR) -> str:
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    found = sorted(tools_dir.glob("ffmpeg-*/**/bin/ffmpeg.exe"))
    return str(found[-1]) if found else ""


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - https only
        with destination.open("wb") as out:
            shutil.copyfileobj(response, out)


def safe_extract(zip_path: Path, target: Path) -> None:
    """Extract, refusing any member that would land outside ``target``."""

    target = target.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (target / member.filename).resolve()
            if destination != target and target not in destination.parents:
                raise FetchError(f"unsafe path in zip: {member.filename}")
        archive.extractall(target)


def install(
    zip_path: Path,
    expected_sha: str,
    tools_dir: Path = TOOLS_DIR,
) -> Path:
    actual = sha256_of(zip_path)
    if actual != expected_sha:
        raise FetchError(
            "FFmpeg zip checksum mismatch: expected "
            f"{expected_sha}, got {actual}. Not extracting it."
        )
    tools_dir.mkdir(parents=True, exist_ok=True)
    final_zip = tools_dir / ZIP_NAME
    if zip_path.resolve() != final_zip.resolve():
        shutil.copyfile(zip_path, final_zip)
    target = tools_dir / EXTRACT_DIR_NAME
    safe_extract(final_zip, target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="Fetch even if found.")
    parser.add_argument("--zip", type=Path, help="Use this local zip instead.")
    args = parser.parse_args(argv)

    if not args.force and not args.zip:
        found = existing_ffmpeg()
        if found:
            print(f"FFmpeg already available: {found}")
            return 0

    try:
        url, sha = read_pin()
        if args.zip:
            target = install(args.zip, sha)
        else:
            with tempfile.TemporaryDirectory() as scratch:
                downloaded = Path(scratch) / ZIP_NAME
                print(f"Downloading {url}")
                download(url, downloaded)
                target = install(downloaded, sha)
    except (FetchError, OSError, zipfile.BadZipFile) as exc:
        print(f"FFmpeg setup failed: {exc}", file=sys.stderr)
        print(
            "Install FFmpeg yourself (for example `winget install Gyan.FFmpeg`) so "
            "`ffmpeg` is on PATH, or pass a verified zip with --zip.",
            file=sys.stderr,
        )
        return 1
    print(f"FFmpeg ready under {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
