"""Notes and Downloads commands, including their two destructive paths."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _note_files(grandpa_home: Path, title: str) -> list[Path]:
    notes_dir = grandpa_home / "notes"
    if not notes_dir.is_dir():
        return []
    return [
        path
        for path in notes_dir.glob("*.md")
        if f'"title": "{title}"' in path.read_text(encoding="utf-8")
    ]


# 9 ---------------------------------------------------------------------------
def test_notes_create_writes_a_note_that_list_and_search_find(cli, make_nonce) -> None:
    title = f"e2e shopping {make_nonce('')}"
    other = f"e2e unrelated {make_nonce('')}"

    created = cli("notes", "create", *title.split())
    cli("notes", "create", *other.split())

    assert created.returncode == 0, created.text
    assert len(_note_files(cli.grandpa_home, title)) == 1, (
        f"no note file on disk for {title!r}; CLI said: {created.tail()}"
    )
    listing = cli("notes", "list")
    assert title in listing.text and other in listing.text, listing.text
    found = cli("notes", "search", title.split()[-1])
    assert title in found.text, found.text
    assert other not in found.text, f"search returned a non-matching note: {found.text}"


# 10 --------------------------------------------------------------------------
def test_notes_append_adds_the_text_to_the_note_file(cli, make_nonce) -> None:
    title = make_nonce("e2eappend")
    line = f"buy oat milk {make_nonce('')}"
    cli("notes", "create", title)

    appended = cli("notes", "append", title, *line.split())

    assert appended.returncode == 0, appended.text
    files = _note_files(cli.grandpa_home, title)
    assert len(files) == 1, f"note file missing: {appended.tail()}"
    assert line in files[0].read_text(encoding="utf-8"), (
        f"appended text is not in {files[0].name}; CLI said: {appended.tail()}"
    )


# 11 --------------------------------------------------------------------------
def test_notes_delete_needs_yes_and_then_really_deletes(cli, make_nonce) -> None:
    title = make_nonce("e2edelete")
    cli("notes", "create", title)
    assert len(_note_files(cli.grandpa_home, title)) == 1

    unconfirmed = cli("notes", "delete", title)

    assert _note_files(cli.grandpa_home, title), (
        f"note deleted without --yes: {unconfirmed.tail()}"
    )
    assert f'Delete note "{title}"?' in unconfirmed.text, unconfirmed.text

    confirmed = cli("notes", "delete", title, "--yes")

    assert confirmed.returncode == 0, confirmed.text
    assert not _note_files(cli.grandpa_home, title), (
        f"note still on disk after --yes; CLI said: {confirmed.tail()}"
    )
    assert title not in cli("notes", "list").text


# 12 --------------------------------------------------------------------------
def test_downloads_recent_and_search_list_the_real_folder(cli, make_nonce) -> None:
    downloads = cli.home / "Downloads"
    report = downloads / f"{make_nonce('report-')}.pdf"
    archive = downloads / f"{make_nonce('archive-')}.zip"
    report.write_bytes(b"%PDF" + b"x" * 33)  # 37 B
    archive.write_bytes(b"PK" + b"y" * 51)  # 53 B

    recent = cli("downloads", "recent")

    assert recent.returncode == 0, recent.text
    assert f"{report.name} " in recent.text and "37 B" in recent.text, recent.text
    assert f"{archive.name} " in recent.text and "53 B" in recent.text, recent.text

    found = cli("downloads", "search", report.stem)
    assert report.name in found.text, found.text
    assert archive.name not in found.text, f"search listed a non-match: {found.text}"


# 13 --------------------------------------------------------------------------
def test_downloads_delete_needs_yes_and_then_deletes_only_the_target(
    cli, make_nonce
) -> None:
    downloads = cli.home / "Downloads"
    target = downloads / f"{make_nonce('old-')}.pdf"
    bystander = downloads / f"{make_nonce('keep-')}.pdf"
    target.write_bytes(b"%PDF target")
    bystander.write_bytes(b"%PDF bystander")

    unconfirmed = cli("downloads", "delete", target.name)

    assert target.exists(), f"deleted without --yes: {unconfirmed.tail()}"
    assert "Delete 1 download" in unconfirmed.text, unconfirmed.text

    confirmed = cli("downloads", "delete", target.name, "--yes")

    assert confirmed.returncode == 0, confirmed.text
    assert not target.exists(), f"file still on disk after --yes: {confirmed.tail()}"
    assert bystander.read_bytes() == b"%PDF bystander", "a non-target download changed"
