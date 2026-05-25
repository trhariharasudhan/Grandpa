from pathlib import Path

from grandpa import file_assistant
from grandpa.file_assistant import FileAssistantStore, handle_file_command


def _store(tmp_path: Path) -> FileAssistantStore:
    return FileAssistantStore(tmp_path / "files.db")


def _isolate_file_assistant(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "safe"
    notes = tmp_path / "notes"
    root.mkdir()
    notes.mkdir()
    monkeypatch.setattr(file_assistant, "NOTES_DIR", notes)
    monkeypatch.setattr(file_assistant, "_safe_roots", lambda: [root])
    monkeypatch.setattr(file_assistant, "_record_memory_activity", lambda *args: None)
    return root


def test_create_and_read_note(tmp_path: Path, monkeypatch) -> None:
    _isolate_file_assistant(tmp_path, monkeypatch)
    store = _store(tmp_path)

    created = handle_file_command("create a note called ideas", store=store)
    assert created.status == "handled"
    assert "ideas.md" in created.message

    read = handle_file_command("read this note", store=store)
    assert read.status == "handled"
    assert "ideas.md" in read.message


def test_find_pdf_files_uses_safe_roots(tmp_path: Path, monkeypatch) -> None:
    root = _isolate_file_assistant(tmp_path, monkeypatch)
    (root / "FastAPI Guide.pdf").write_bytes(b"%PDF-1.4")

    result = handle_file_command("find PDF files", store=_store(tmp_path))

    assert result.status == "handled"
    assert "FastAPI Guide.pdf" in result.message


def test_search_files_about_reads_text_samples(tmp_path: Path, monkeypatch) -> None:
    root = _isolate_file_assistant(tmp_path, monkeypatch)
    (root / "notes.md").write_text("FastAPI routing and dependency injection", encoding="utf-8")

    result = handle_file_command("search files about FastAPI", store=_store(tmp_path))

    assert result.status == "handled"
    assert "notes.md" in result.message


def test_unrelated_question_falls_back(tmp_path: Path, monkeypatch) -> None:
    _isolate_file_assistant(tmp_path, monkeypatch)

    result = handle_file_command("What is Python?", store=_store(tmp_path))

    assert result.should_fallback is True
