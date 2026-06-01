"""Local file assistant for Grandpa.

The file assistant is intentionally conservative: it searches common user
folders and the current Grandpa workspace, reads only simple document types,
and never deletes or overwrites files.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_FILE_DB = DEFAULT_CONFIG_DIR / "file_assistant.db"
NOTES_DIR = DEFAULT_CONFIG_DIR / "notes"
MAX_SCAN_FILES = 5000
MAX_READ_CHARS = 12000
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "build", "cache", ".cache"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".log", ".csv", ".json", ".toml", ".yaml", ".yml"}
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx", ".xlsx", ".pptx"}


@dataclass(frozen=True)
class FileAssistantResult:
    status: str
    kind: str
    target: str | None
    message: str
    tts_text: str | None = None
    permission: str | None = "allowed"
    pending_action: dict[str, Any] | None = None
    should_fallback: bool = False


class FileAssistantStore:
    def __init__(self, db_path: Path | str = DEFAULT_FILE_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recent_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    action TEXT NOT NULL,
                    path TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_recent_files_created "
                "ON recent_files(created_at)"
            )

    def record(self, action: str, path: Path | str, detail: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO recent_files(created_at, action, path, detail) VALUES (?, ?, ?, ?)",
                (time.time(), action, str(path), detail),
            )

    def recent(self, limit: int = 20, since: float | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, created_at, action, path, detail
                FROM recent_files
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def handle_file_command(text: str, *, store: FileAssistantStore | None = None) -> FileAssistantResult:
    command = _normalise(text)
    if not command:
        return _fallback()
    store = store or FileAssistantStore()

    if command in {"show recent files", "recent files", "show my recent files"}:
        return _show_recent_files(store)

    if command in {"what files did i use today", "what files did i use today?"}:
        return _files_used_today(store)

    if command in {"find pdf files", "show pdf files", "search pdf files"}:
        return _find_files("pdf", store)

    match = re.fullmatch(r"find (?:excel|xlsx|spreadsheet|word|docx|powerpoint|pptx|resume|invoice)(?: files| sheets| documents)?(?: about (.+))?", command)
    if match:
        query = match.group(1) or command.replace("find ", "")
        return _document_search(query, store)

    match = re.fullmatch(r"show invoices from last month", command)
    if match:
        return _document_search("invoices last month", store)

    if command in {"file intelligence diagnostics", "document diagnostics", "file diagnostics"}:
        return _document_diagnostics()

    match = re.fullmatch(r"suggest (?:file )?renames(?: for (.+))?", command)
    if match:
        return _rename_suggestions(match.group(1) or "")

    match = re.fullmatch(r"organize files(?: about (.+))?", command)
    if match:
        return _organization_dry_run(match.group(1) or "")

    match = re.fullmatch(r"search files about (.+)", command)
    if match:
        return _search_files(match.group(1).strip(), store)

    match = re.fullmatch(r"create a note called (.+)", command)
    if match:
        return _create_note(match.group(1).strip(), store)

    if command in {"read this note", "open this note", "show this note"}:
        return _read_latest_note(store)

    match = re.fullmatch(r"read (?:this )?(?:text )?file (.+)", command)
    if match:
        return _read_named_document(match.group(1).strip(), store)

    if command in {"summarize this pdf", "summarise this pdf"}:
        return _summarize_latest_pdf(store)

    match = re.fullmatch(r"summari[sz]e (.+)", command)
    if match:
        return _summarize_named_document(match.group(1).strip(), store)

    if command == "open my vs code project":
        workspace = Path("D:/Grandpa")
        if workspace.exists():
            return _open_path(workspace, store)
        return FileAssistantResult("unsupported", "file", str(workspace), "I could not find the Grandpa workspace.")

    return _fallback()


def file_assistant_summary() -> dict[str, Any]:
    store = FileAssistantStore()
    notes = []
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        notes.append(_metadata(path))
    return {
        "recent_files": store.recent(limit=30),
        "notes": notes,
        "safe_roots": [str(path) for path in _safe_roots()],
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


def search_files(query: str) -> dict[str, Any]:
    result = _search_files(query, FileAssistantStore())
    return {"message": result.message, "status": result.status}


def _document_search(query: str, store: FileAssistantStore) -> FileAssistantResult:
    from grandpa.document_intelligence import search_documents

    result = search_documents(query)
    store.record("document_search", query, result.status)
    return FileAssistantResult(result.status, "file", query, result.message, "I searched your local documents.")


def _document_diagnostics() -> FileAssistantResult:
    from grandpa.document_intelligence import diagnostics

    data = diagnostics()
    counts = ", ".join(f"{key}: {value}" for key, value in sorted(data["type_counts"].items())) or "none indexed yet"
    message = (
        "File intelligence diagnostics:\n"
        f"- Supported: {', '.join(data['supported_types'])}\n"
        f"- Indexed documents: {data['indexed_documents']}\n"
        f"- Type counts: {counts}\n"
        "- Local only: yes"
    )
    return FileAssistantResult("handled", "file", "diagnostics", message, "File diagnostics are ready.")


def _rename_suggestions(query: str) -> FileAssistantResult:
    from grandpa.document_intelligence import suggest_renames

    result = suggest_renames(query)
    return FileAssistantResult(result.status, "file", "rename_suggestions", result.message, "Prepared rename suggestions.")


def _organization_dry_run(query: str) -> FileAssistantResult:
    from grandpa.document_intelligence import organization_plan

    result = organization_plan(query, dry_run=True)
    return FileAssistantResult(result.status, "file", "organization_plan", result.message, "Prepared an organization dry run.")


def _show_recent_files(store: FileAssistantStore) -> FileAssistantResult:
    rows = store.recent(limit=10)
    if not rows:
        return FileAssistantResult("handled", "file", "recent", "I do not have recent file activity yet.", "No recent files yet.")
    lines = ["Recent files:"]
    for row in rows[:10]:
        when = datetime.fromtimestamp(row["created_at"]).strftime("%b %d %H:%M")
        lines.append(f"- {Path(row['path']).name} ({row['action']}, {when})")
    return FileAssistantResult("handled", "file", "recent", "\n".join(lines), "Here are your recent files.")


def _files_used_today(store: FileAssistantStore) -> FileAssistantResult:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = store.recent(limit=20, since=start)
    if not rows:
        return FileAssistantResult("handled", "file", "today", "I do not have file activity recorded for today yet.")
    lines = ["Files used today:"]
    for row in rows[:10]:
        lines.append(f"- {Path(row['path']).name} ({row['action']})")
    return FileAssistantResult("handled", "file", "today", "\n".join(lines), "Here are files used today.")


def _find_files(extension: str, store: FileAssistantStore) -> FileAssistantResult:
    ext = "." + extension.lstrip(".").lower()
    matches = [path for path in _iter_safe_files() if path.suffix.lower() == ext][:20]
    if not matches:
        return FileAssistantResult("handled", "file", ext, f"I did not find any {extension.upper()} files in the safe search folders.")
    lines = [f"Found {len(matches)} {extension.upper()} file(s):"]
    for path in matches[:10]:
        meta = _metadata(path)
        lines.append(f"- {path.name} — {meta['size_label']}, modified {meta['modified_label']}")
    store.record("search", ext, f"{len(matches)} matches")
    return FileAssistantResult("handled", "file", ext, "\n".join(lines), f"I found {len(matches)} files.")


def _search_files(query: str, store: FileAssistantStore) -> FileAssistantResult:
    tokens = _tokens(query)
    scored: list[tuple[int, Path]] = []
    for path in _iter_safe_files():
        haystack = path.name.lower()
        score = sum(1 for token in tokens if token in haystack)
        if score == 0 and path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size <= 200_000:
            try:
                sample = path.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
                score = sum(1 for token in tokens if token in sample)
            except OSError:
                score = 0
        if score:
            scored.append((score, path))
    scored.sort(key=lambda pair: (pair[0], pair[1].stat().st_mtime), reverse=True)
    matches = [path for _, path in scored[:10]]
    if not matches:
        return FileAssistantResult("handled", "file", query, f"I did not find files about {query} in the safe search folders.")
    lines = [f"Files about {query}:"]
    for path in matches:
        meta = _metadata(path)
        lines.append(f"- {path.name} — {meta['type']}, {meta['size_label']}")
    store.record("search", query, f"{len(matches)} matches")
    return FileAssistantResult("handled", "file", query, "\n".join(lines), f"I found files about {query}.")


def _create_note(raw_name: str, store: FileAssistantStore) -> FileAssistantResult:
    name = _safe_note_name(raw_name)
    if not name:
        return FileAssistantResult("blocked", "file", raw_name, "I blocked this note name for safety.", permission="blocked")
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTES_DIR / f"{name}.md"
    if path.exists():
        store.record("note", path, "already exists")
        return FileAssistantResult("handled", "file", str(path), f"The note already exists: {path.name}")
    path.write_text(f"# {raw_name.strip().title()}\n\n", encoding="utf-8")
    store.record("note", path, "created")
    _record_memory_activity("file", "note", str(path), "created", "handled")
    return FileAssistantResult("handled", "file", str(path), f"Created note: {path.name}", "Created the note.")


def _read_latest_note(store: FileAssistantStore) -> FileAssistantResult:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    notes = sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not notes:
        return FileAssistantResult("handled", "file", "notes", "I do not have any notes yet.")
    return _read_document(notes[0], store)


def _read_named_document(name: str, store: FileAssistantStore) -> FileAssistantResult:
    path = _find_best_match(name)
    if not path:
        return FileAssistantResult("handled", "file", name, f"I could not find a readable file matching {name}.")
    return _read_document(path, store)


def _summarize_latest_pdf(store: FileAssistantStore) -> FileAssistantResult:
    pdfs = sorted(
        [path for path in _iter_safe_files() if path.suffix.lower() == ".pdf"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not pdfs:
        return FileAssistantResult("handled", "file", "pdf", "I did not find a PDF to summarize in the safe search folders.")
    return _summarize_document(pdfs[0], store)


def _summarize_named_document(name: str, store: FileAssistantStore) -> FileAssistantResult:
    path = _find_best_match(name)
    if not path:
        return FileAssistantResult("handled", "file", name, f"I could not find a document matching {name}.")
    return _summarize_document(path, store)


def _read_document(path: Path, store: FileAssistantStore) -> FileAssistantResult:
    if path.suffix.lower() not in DOCUMENT_EXTENSIONS:
        return FileAssistantResult("unsupported", "file", str(path), "I can read txt, md, and PDF files in this phase.")
    text = _extract_text(path)
    if not text:
        return FileAssistantResult("unsupported", "file", str(path), f"I could not read text from {path.name}.")
    store.record("read", path, "read document")
    _record_memory_activity("file", "read", str(path), path.name, "handled")
    preview = text[:1500].strip()
    return FileAssistantResult("handled", "file", str(path), f"{path.name}:\n\n{preview}", f"I read {path.name}.")


def _summarize_document(path: Path, store: FileAssistantStore) -> FileAssistantResult:
    text = _extract_text(path)
    if not text:
        return FileAssistantResult("unsupported", "file", str(path), f"I could not extract text from {path.name}.")
    summary = _simple_summary(text)
    store.record("summarize", path, "summarized document")
    _record_memory_activity("file", "summarize", str(path), path.name, "handled")
    return FileAssistantResult("handled", "file", str(path), f"Summary of {path.name}:\n\n{summary}", f"Summarized {path.name}.")


def _open_path(path: Path, store: FileAssistantStore) -> FileAssistantResult:
    if not path.exists():
        return FileAssistantResult("unsupported", "file", str(path), f"I could not find {path}.")
    if sys.platform != "win32":
        return FileAssistantResult("unsupported", "file", str(path), "Opening files and folders is only supported on Windows desktop here.")
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    except OSError as exc:
        return FileAssistantResult("error", "file", str(path), f"I could not open {path}: {exc}")
    store.record("open", path, "opened path")
    _record_memory_activity("file", "open", str(path), path.name, "handled")
    return FileAssistantResult("handled", "file", str(path), f"Opening {path.name}.", f"Opening {path.name}.")


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="ignore")[:MAX_READ_CHARS]
    if suffix == ".pdf":
        from grandpa.document_intelligence import extract_document_text

        return extract_document_text(path)[:MAX_READ_CHARS]
    if suffix in {".docx", ".xlsx", ".pptx"}:
        from grandpa.document_intelligence import extract_document_text

        return extract_document_text(path)[:MAX_READ_CHARS]
    return ""


def _simple_summary(text: str) -> str:
    from grandpa.document_intelligence import smart_summary

    return smart_summary(text)


def _iter_safe_files() -> list[Path]:
    files: list[Path] = []
    for root in _safe_roots():
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for current, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for name in names:
                path = Path(current) / name
                try:
                    if path.suffix.lower() in DOCUMENT_EXTENSIONS:
                        files.append(path)
                    if len(files) >= MAX_SCAN_FILES:
                        return files
                except OSError:
                    continue
    return files


def _safe_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Downloads", home / "Documents", home / "Desktop", Path("D:/Grandpa")]
    return _dedupe_paths(roots)


def _find_best_match(query: str) -> Path | None:
    needle = query.lower().strip().strip('"')
    candidates = _iter_safe_files() + list(NOTES_DIR.glob("*.md")) if NOTES_DIR.exists() else _iter_safe_files()
    exact = [path for path in candidates if path.name.lower() == needle]
    if exact:
        return exact[0]
    partial = [path for path in candidates if needle in path.name.lower()]
    if partial:
        partial.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return partial[0]
    return None


def _metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "type": path.suffix.lower().lstrip(".") or "file",
        "size": stat.st_size,
        "size_label": _size_label(stat.st_size),
        "modified": stat.st_mtime,
        "modified_label": datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y"),
    }


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _normalise(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[?!.\s]+$", "", value)
    return re.sub(r"\s+", " ", value)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1}


def _safe_note_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:80]


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _record_memory_activity(category: str, action: str, target: str, detail: str, status: str) -> None:
    try:
        from grandpa.memory_context import record_activity

        record_activity(category, action, target, detail, status)
    except Exception:
        return


def _fallback() -> FileAssistantResult:
    return FileAssistantResult("no_match", "file", None, "", None, should_fallback=True)


__all__ = [
    "FileAssistantResult",
    "FileAssistantStore",
    "file_assistant_summary",
    "handle_file_command",
    "search_files",
]
