"""Tests for Grandpa's safe Downloads Manager."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from grandpa.cli.chat_cmd import _handle_downloads_slash_command
from grandpa.cli.doctor_cmd import _check_downloads_readiness
from grandpa.cli.slash_commands import get_command
from grandpa.downloads import DownloadsAutomation, DownloadsParser, DownloadsScanner
from grandpa.downloads.automation import handle_downloads_command
from grandpa.downloads.safety import DownloadsSafetyError, DownloadsSafetyPolicy
from grandpa.downloads.scanner import classify_file
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.operator import (
    execute_voice_operator_intent,
    parse_voice_operator_command,
)


def _file(path: Path, content: bytes = b"data", *, days_old: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if days_old:
        timestamp = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
        os.utime(path, (timestamp, timestamp))
    return path


def test_parser_handles_requested_download_commands() -> None:
    parser = DownloadsParser()

    assert parser.parse("show recent downloads").action == "recent"
    assert parser.parse("show downloads from today").action == "today"
    assert parser.parse("open latest download").action == "open"
    assert parser.parse("find downloaded PDF").query == "PDF"
    assert parser.parse("show large downloads").action == "large"
    assert parser.parse("show incomplete downloads").action == "incomplete"
    assert parser.parse("organize my Downloads folder").action == "organize"
    assert parser.parse("move downloaded PDFs to Documents").action == "move"
    assert parser.parse("archive old downloads").action == "archive"
    assert parser.parse("delete downloads older than 30 days").days == 30
    assert parser.parse("show duplicate downloads").action == "duplicates"
    assert parser.parse("open downloads") is None


def test_scanner_sorts_classifies_and_filters(tmp_path: Path) -> None:
    _file(tmp_path / "old.pdf", b"old", days_old=2)
    latest = _file(tmp_path / "photo.png", b"image")
    _file(tmp_path / "movie.mp4", b"video", days_old=1)
    _file(tmp_path / "partial.crdownload", b"partial", days_old=1)
    scanner = DownloadsScanner((tmp_path,))

    items = scanner.scan()

    assert items[0].path == latest
    assert classify_file(tmp_path / "old.pdf") == "pdf"
    assert classify_file(tmp_path / "photo.png") == "image"
    assert scanner.incomplete()[0].name == "partial.crdownload"
    assert scanner.search("pdf")[0].name == "old.pdf"


def test_scanner_detects_large_files_and_duplicates(tmp_path: Path) -> None:
    _file(tmp_path / "a.txt", b"same")
    _file(tmp_path / "b.txt", b"same")
    _file(tmp_path / "large.bin", b"x" * 32)
    scanner = DownloadsScanner((tmp_path,))

    large = scanner.large(min_bytes=10)
    duplicates = scanner.duplicates()

    assert {item.name for item in large} == {"large.bin"}
    assert {item.name for item in duplicates} == {"a.txt", "b.txt"}
    assert all(item.duplicate_group for item in duplicates)


def test_open_latest_safe_file_and_block_executable(tmp_path: Path) -> None:
    opened: list[Path] = []
    _file(tmp_path / "safe.pdf")
    scanner = DownloadsScanner((tmp_path,))
    result = DownloadsAutomation(scanner=scanner, opener=opened.append).handle("open latest download")

    assert result.status == "handled"
    assert opened == [tmp_path / "safe.pdf"]

    _file(tmp_path / "setup.exe")
    blocked = DownloadsAutomation(scanner=scanner, opener=opened.append).handle("open latest download")

    assert blocked.status == "blocked"
    assert "unsafe" in blocked.message


def test_move_archive_organize_and_delete_require_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    downloads = home / "Downloads"
    monkeypatch.setattr(Path, "home", lambda: home)
    _file(downloads / "one.pdf")
    _file(downloads / "two.pdf")
    _file(downloads / "old.tmp", days_old=40)
    automation = DownloadsAutomation(scanner=DownloadsScanner((downloads,)))

    move_pending = automation.handle("move downloaded PDFs to Documents")
    archive_pending = automation.handle("archive old downloads")
    delete_pending = automation.handle("delete downloads older than 30 days")

    assert move_pending.status == "needs_confirmation"
    assert archive_pending.status == "needs_confirmation"
    assert delete_pending.status == "needs_confirmation"

    moved = automation.handle("move downloaded PDFs to Documents", confirmed=True)
    archived = automation.handle("archive old downloads", confirmed=True)
    deleted = automation.handle("clear temporary download files", confirmed=True)

    assert moved.status == "handled"
    assert (home / "Documents" / "one.pdf").exists()
    assert archived.status == "handled"
    assert deleted.status == "handled"


def test_organize_downloads_by_file_type(tmp_path: Path) -> None:
    _file(tmp_path / "doc.pdf")
    _file(tmp_path / "pic.jpg")
    automation = DownloadsAutomation(scanner=DownloadsScanner((tmp_path,)))

    pending = automation.handle("organize my downloads folder")
    result = automation.handle("organize my downloads folder", confirmed=True)

    assert pending.status == "needs_confirmation"
    assert result.status == "handled"
    assert (tmp_path / "Documents" / "doc.pdf").exists()
    assert (tmp_path / "Images" / "pic.jpg").exists()


def test_path_traversal_and_external_destination_are_blocked(tmp_path: Path) -> None:
    safety = DownloadsSafetyPolicy((tmp_path / "Downloads",))

    with pytest.raises(DownloadsSafetyError):
        safety.ensure_allowed_root(tmp_path / "outside.txt")

    with pytest.raises(DownloadsSafetyError):
        safety.safe_destination(tmp_path / "Other")


def test_downloads_slash_command_routes_through_safe_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_handle(text: str):
        calls.append(text)
        return SimpleNamespace(message="Downloads listed.")

    monkeypatch.setattr("grandpa.downloads.handle_downloads_command", fake_handle)

    assert _handle_downloads_slash_command("/downloads recent") == "Downloads listed."
    assert calls == ["show recent downloads"]


def test_downloads_slash_command_is_registered_for_picker() -> None:
    command = get_command("/downloads")

    assert command is not None
    assert command.category == "Computer"
    assert "/downloads recent" in command.subcommands


def test_voice_assistant_routes_downloads_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "grandpa.downloads.handle_downloads_command",
        lambda _text: SimpleNamespace(
            should_fallback=False,
            message="Downloads listed.",
            status="handled",
            action=SimpleNamespace(query=""),
        ),
    )
    processor = VoiceCommandProcessor()

    response = processor._handle_local_pipeline("show recent downloads")

    assert response is not None
    assert response.kind == "downloads"
    assert response.text == "Downloads listed."


def test_voice_operator_routes_downloads_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    intent = parse_voice_operator_command("show recent downloads")
    assert intent.kind == "downloads"

    monkeypatch.setattr(
        "grandpa.downloads.handle_downloads_command",
        lambda _text: SimpleNamespace(
            status="handled",
            message="Downloads listed.",
            requires_confirmation=False,
        ),
    )

    result = execute_voice_operator_intent(intent)

    assert result.status == "handled"
    assert result.action["action_type"] == "downloads"


def test_handle_downloads_command_uses_temp_scanner_only(tmp_path: Path) -> None:
    _file(tmp_path / "invoice.pdf")

    result = handle_downloads_command("find downloaded invoice", scanner=DownloadsScanner((tmp_path,)))

    assert result.status == "handled"
    assert "invoice.pdf" in result.message


def test_doctor_reports_downloads_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeScanner:
        def status(self):
            return "ready", "Downloads directory ready."

    monkeypatch.setattr("grandpa.downloads.DownloadsScanner", FakeScanner)

    result = _check_downloads_readiness()

    assert result.status == "ok"
    assert result.message == "Ready"
