from __future__ import annotations

import zipfile
from pathlib import Path

from grandpa.files import (
    FileAutomation,
    FileExecutor,
    FileParser,
    handle_file_automation,
)
from grandpa.files.paths import find_matches, resolve_destination, resolve_path
from grandpa.files.safety import FileSafetyPolicy
from grandpa.voice.operator import parse_voice_operator_command


def test_parser_natural_file_commands() -> None:
    parser = FileParser()

    assert parser.parse("Create folder AI Projects").action == "create_folder"
    assert parser.parse("Create file notes.txt").action == "create_file"
    assert parser.parse("Rename notes.txt to todo.txt").action == "rename"
    assert parser.parse("Copy report.pdf to Desktop").action == "copy"
    assert parser.parse("Move image.png to Pictures").action == "move"
    assert parser.parse("Delete temp.txt").action == "delete"
    assert parser.parse("Find invoice.pdf").action == "search"
    assert parser.parse("Open latest PDF").action == "open"
    assert parser.parse("Compress Project Folder").action == "zip"
    assert parser.parse("Extract project.zip").action == "extract"
    assert parser.parse("Show properties of report.pdf").action == "properties"
    assert parser.parse("What is the weather?") is None


def test_path_resolution_aliases_and_relative_paths(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GRANDPA_FILE_SAFE_ROOTS", str(tmp_path))

    assert resolve_destination("Desktop").name == "Desktop"
    assert resolve_path("notes.txt", roots=(tmp_path,)) == tmp_path / "notes.txt"


def test_find_matches_reports_ambiguity_inputs(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = tmp_path / "a" / "report.pdf"
    second = tmp_path / "b" / "report.pdf"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    matches = find_matches("report.pdf", roots=(tmp_path,))

    assert matches == sorted(
        [first.resolve(strict=False), second.resolve(strict=False)],
        key=lambda path: str(path).casefold(),
    )


def test_safety_blocks_protected_and_traversal_paths() -> None:
    safety = FileSafetyPolicy()

    assert safety.is_protected(Path(r"C:\Windows\System32\drivers\etc\hosts"))
    assert safety.is_protected(Path.home() / ".grandpa" / "config.toml")
    assert safety.blocks_traversal("..\\secret.txt")


def test_create_file_and_folder(tmp_path: Path) -> None:
    automation = FileAutomation(roots=(tmp_path,))

    folder = automation.handle("Create folder AI Projects")
    file_result = automation.handle("Create file notes.txt")

    assert folder.status == "handled"
    assert (tmp_path / "ai projects").exists()
    assert file_result.status == "handled"
    assert (tmp_path / "notes.txt").exists()


def test_copy_move_rename_and_overwrite_protection(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_text("report", encoding="utf-8")
    (tmp_path / "copies").mkdir()
    automation = FileAutomation(roots=(tmp_path,))

    copied = automation.handle("Copy report.pdf to copies/report.pdf")
    renamed = automation.handle("Rename report.pdf to final.pdf")
    blocked = automation.handle("Create file final.pdf")

    assert copied.status == "handled"
    assert copied.destination == (tmp_path / "copies" / "report.pdf").resolve(
        strict=False
    )
    assert renamed.status == "handled"
    assert (tmp_path / "final.pdf").exists()
    assert blocked.status == "needs_confirmation"


def test_delete_requires_confirmation_and_then_deletes(tmp_path: Path) -> None:
    target = tmp_path / "temp.txt"
    target.write_text("x", encoding="utf-8")
    automation = FileAutomation(roots=(tmp_path,))

    prompt = automation.handle("Delete temp.txt")
    deleted = automation.handle("Delete temp.txt", confirm=lambda *_args: True)

    assert prompt.status == "needs_confirmation"
    assert not target.exists()
    assert deleted.status == "handled"


def test_search_open_properties_zip_and_extract(tmp_path: Path) -> None:
    opened: list[Path] = []
    source = tmp_path / "Project Folder"
    source.mkdir()
    note = source / "report.txt"
    note.write_text("Grandpa report", encoding="utf-8")
    automation = FileAutomation(roots=(tmp_path,), opener=opened.append)

    search = automation.handle("Find report.txt")
    opened_result = automation.handle("Open report.txt")
    info = automation.handle("Show properties of report.txt")
    archive = automation.handle("Zip Project Folder")
    extract = automation.handle("Extract Project Folder.zip to extracted")

    assert search.status == "handled"
    assert "report.txt" in search.message
    assert opened_result.status == "handled"
    assert opened == [note.resolve(strict=False)]
    assert "Size:" in info.message
    assert archive.status == "handled"
    assert zipfile.is_zipfile(tmp_path / "Project Folder.zip")
    assert extract.status == "handled"


def test_archive_rejects_unsafe_members(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../bad.txt", "bad")
    result = handle_file_automation("Extract bad.zip", roots=(tmp_path,))

    assert result.status == "blocked"


def test_open_missing_path_returns_friendly_error(tmp_path: Path) -> None:
    result = FileAutomation(roots=(tmp_path,), opener=lambda _path: None).handle(
        "Open missing.txt"
    )

    assert result.status == "error"
    assert "could not find" in result.message.lower()


def test_file_executor_open_is_mockable(tmp_path: Path) -> None:
    opened: list[Path] = []
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    executor = FileExecutor(roots=(tmp_path,), opener=opened.append)
    action = FileParser().parse("Open note.txt")

    result = executor.execute(action)

    assert result.status == "handled"
    assert opened == [target.resolve(strict=False)]


def test_files_slash_command_routes_to_file_automation(
    tmp_path: Path, monkeypatch
) -> None:
    from grandpa import file_assistant
    from grandpa.cli.chat_cmd import _handle_files_slash_command

    monkeypatch.setattr(file_assistant, "_safe_roots", lambda: [tmp_path])

    message = _handle_files_slash_command("/files create-file slash.txt")

    assert "File created" in message
    assert (tmp_path / "slash.txt").exists()


def test_voice_operator_parses_file_command() -> None:
    intent = parse_voice_operator_command("Create file operator.txt")

    assert intent.kind == "file_automation"
    assert intent.action == "create_file"
