"""Small, screen-free helpers for the terminal interface.

* :func:`copy_text` puts text on the system clipboard (Windows, macOS, Linux).
* :func:`export_markdown` saves the conversation as a Markdown file.
* :func:`file_suggestions` and :func:`expand_file_mentions` handle ``@file``:
  type ``@`` and a path to attach a text file's contents to a message.

Attaching is read-only, limited in size, and refuses binary files and files
outside the current folder and the home folder.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

MAX_ATTACH_BYTES = 100_000
SKIP_DIRS = {
    ".git",
    ".venv",
    ".venv-old",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".idea",
    ".vscode",
}

# @path, where path is quoted ("@\"my file.txt\"") or runs to the next space.
_MENTION = re.compile(r'(?<![\w@])@(?:"([^"]+)"|([^\s"]+))')


# --- clipboard -----------------------------------------------------------------


def _clipboard_commands() -> list[list[str]]:
    if sys.platform == "win32":
        return [["clip.exe"]]
    if sys.platform == "darwin":
        return [["pbcopy"]]
    commands = []
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        commands += [
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    return commands


def copy_text(text: str) -> bool:
    """Copy to the system clipboard. False when no clipboard tool worked."""
    for command in _clipboard_commands():
        if shutil.which(command[0]) is None:
            continue
        try:
            encoding = "utf-16-le" if command[0] == "clip.exe" else "utf-8"
            subprocess.run(
                command,
                input=text.encode(encoding),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


# --- export --------------------------------------------------------------------


@dataclass
class Turn:
    role: str  # "user" or "grandpa"
    text: str
    at: datetime


def export_markdown(
    turns: Iterable[Turn], folder: Path, now: datetime | None = None
) -> Path:
    """Write the conversation to ``folder/grandpa-chat-YYYYmmdd-HHMMSS.md``."""
    now = now or datetime.now()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"grandpa-chat-{now:%Y%m%d-%H%M%S}.md"
    lines = [f"# Grandpa conversation, {now:%d %b %Y %H:%M}", ""]
    for turn in turns:
        who = "You" if turn.role == "user" else "Grandpa"
        lines += [f"**{who}** · {turn.at:%H:%M}", "", turn.text.rstrip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- @file -----------------------------------------------------------------------


def mention_at_cursor(text: str) -> str | None:
    """The partial ``@path`` being typed at the end of ``text``, without ``@``."""
    match = re.search(r'(?:^|\s)@("?[^\s"]*)$', text)
    if not match:
        return None
    return match.group(1).lstrip('"')


def file_suggestions(
    partial: str, base: Path | None = None, limit: int = 8
) -> list[str]:
    """Paths under ``base`` that match what was typed after ``@``."""
    base = base or Path.cwd()
    partial = partial.replace("\\", "/")
    folder_part, _, name_part = partial.rpartition("/")
    folder = (base / folder_part) if folder_part else base
    try:
        entries = sorted(
            folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        )
    except OSError:
        return []
    found = []
    lowered = name_part.lower()
    for entry in entries:
        if entry.name in SKIP_DIRS or (
            entry.name.startswith(".") and not lowered.startswith(".")
        ):
            continue
        if lowered and not entry.name.lower().startswith(lowered):
            continue
        shown = f"{folder_part}/{entry.name}" if folder_part else entry.name
        found.append(shown + ("/" if entry.is_dir() else ""))
        if len(found) >= limit:
            break
    return found


def _allowed(path: Path, base: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    roots = [base.resolve(), Path.home().resolve()]
    return any(resolved == root or root in resolved.parents for root in roots)


def read_attachment(raw: str, base: Path | None = None) -> tuple[str | None, str]:
    """``(contents, note)``. Contents is None when the file can't be attached."""
    base = base or Path.cwd()
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        path = base / path
    if not _allowed(path, base):
        return (
            None,
            f"{raw}: only files in this folder or your home folder can be attached",
        )
    if not path.is_file():
        return None, f"{raw}: no such file"
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            data = handle.read(MAX_ATTACH_BYTES + 1)
    except OSError as exc:
        return None, f"{raw}: {exc.strerror or exc}"
    if b"\x00" in data[:4096]:
        return None, f"{raw}: looks like a binary file, not attached"
    note = ""
    if len(data) > MAX_ATTACH_BYTES:
        data = data[:MAX_ATTACH_BYTES]
        note = f"{raw}: only the first {MAX_ATTACH_BYTES // 1000} KB of {size // 1000} KB attached"
    return data.decode("utf-8", errors="replace"), note


def expand_file_mentions(
    text: str, base: Path | None = None
) -> tuple[str, list[str], list[str]]:
    """Attach every ``@file`` in ``text``.

    Returns ``(message, attached, notes)``: the message with the files' contents
    appended, the names attached, and anything the user should know.
    """
    attached: list[str] = []
    notes: list[str] = []
    blocks: list[str] = []
    for match in _MENTION.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw in attached:
            continue
        contents, note = read_attachment(raw, base)
        if note:
            notes.append(note)
        if contents is None:
            continue
        attached.append(raw)
        fence = "````" if "```" in contents else "```"
        blocks.append(f"File: {raw}\n{fence}\n{contents.rstrip()}\n{fence}")
    if not blocks:
        return text, attached, notes
    return text + "\n\n" + "\n\n".join(blocks), attached, notes


__all__ = [
    "MAX_ATTACH_BYTES",
    "Turn",
    "copy_text",
    "expand_file_mentions",
    "export_markdown",
    "file_suggestions",
    "mention_at_cursor",
    "read_attachment",
]
