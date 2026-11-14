"""FFmpeg is fetched, not committed, and only a zip with the pinned checksum is
extracted."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "voice_runtime" / "scripts" / "fetch_ffmpeg.py"
SPEC = importlib.util.spec_from_file_location("voice_runtime_fetch_ffmpeg", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fetch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch
SPEC.loader.exec_module(fetch)


def _zip(path: Path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repo_pin_is_well_formed():
    url, sha = fetch.read_pin()
    assert url.startswith("https://")
    assert len(sha) == 64


def test_non_https_url_is_refused(tmp_path):
    (tmp_path / "u").write_text("http://example.invalid/ffmpeg.zip", encoding="utf-8")
    (tmp_path / "s").write_text("0" * 64, encoding="utf-8")
    with pytest.raises(fetch.FetchError):
        fetch.read_pin(tmp_path / "u", tmp_path / "s")


def test_bad_checksum_file_is_refused(tmp_path):
    (tmp_path / "u").write_text("https://example.invalid/f.zip", encoding="utf-8")
    (tmp_path / "s").write_text("not-a-sha", encoding="utf-8")
    with pytest.raises(fetch.FetchError):
        fetch.read_pin(tmp_path / "u", tmp_path / "s")


def test_matching_zip_is_extracted_where_run_service_looks(tmp_path):
    source = tmp_path / "dl.zip"
    sha = _zip(source, {"ffmpeg-n7.1/bin/ffmpeg.exe": b"MZ"})
    tools = tmp_path / "tools"
    fetch.install(source, sha, tools)
    assert (tools / fetch.ZIP_NAME).is_file()
    found = sorted(tools.glob("ffmpeg-*/**/bin/ffmpeg.exe"))
    assert found, list(tools.rglob("*"))


def test_mismatched_zip_is_not_extracted(tmp_path):
    source = tmp_path / "dl.zip"
    _zip(source, {"ffmpeg-n7.1/bin/ffmpeg.exe": b"MZ"})
    tools = tmp_path / "tools"
    with pytest.raises(fetch.FetchError, match="checksum mismatch"):
        fetch.install(source, "0" * 64, tools)
    assert not tools.exists() or not any(tools.rglob("ffmpeg.exe"))


def test_zip_slip_is_refused(tmp_path):
    source = tmp_path / "evil.zip"
    sha = _zip(source, {"../outside.txt": b"x"})
    with pytest.raises(fetch.FetchError, match="unsafe path"):
        fetch.install(source, sha, tmp_path / "tools")
    assert not (tmp_path / "outside.txt").exists()


def test_existing_ffmpeg_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(fetch, "download", lambda *a: pytest.fail("must not download"))
    assert fetch.main([]) == 0


@pytest.mark.real_actions(reason="runs read-only `git ls-files` in the repo")
def test_ffmpeg_is_not_tracked_any_more():
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "voice_runtime/tools",
            "grandpa_tree.txt",
            "grandpa_project_structure.txt",
            "MODEL_NAMES.md",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode != 0:
        pytest.skip("not a git checkout")
    assert tracked.stdout.strip() == ""
