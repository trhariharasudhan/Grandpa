"""Deterministic indexing helpers for Grandpa's local knowledge engine."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".txt", ".md", ".json"}
FUTURE_EXTENSIONS = {".pdf", ".docx", ".html"}
TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.-]{2,}")


def normalize_text(text: str) -> str:
    """Normalize text for storage and deterministic retrieval."""

    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text):
        clean = token.lower().strip(".,;:!?()[]{}\"'")
        if clean:
            tokens.append(clean)
    return tokens


def infer_title(source: str, content: str, title: str | None = None) -> str:
    if title and title.strip():
        return title.strip()
    for line in content.splitlines():
        clean = line.strip().strip("#").strip()
        if clean:
            return clean[:120]
    if source:
        return Path(source).stem or source[:120]
    return "Untitled knowledge document"


def infer_tags(source: str, content: str, tags: list[str] | tuple[str, ...] | None = None) -> list[str]:
    found = {tag.strip().lower() for tag in (tags or []) if tag and tag.strip()}
    suffix = Path(source).suffix.lower()
    source_lower = source.lower().replace("\\", "/")
    if suffix:
        found.add(suffix.lstrip("."))
    if "/docs/" in f"/{source_lower}" or source_lower.startswith("docs/"):
        found.add("docs")
    lowered = content.lower()
    keyword_tags = {
        "project": ("project", "roadmap", "architecture", "repo"),
        "grandpa": ("grandpa", "assistant"),
        "development": ("python", "fastapi", "api", "automation", "powershell"),
        "docs": ("installation", "setup", "troubleshooting", "guide"),
        "knowledge": ("knowledge", "index", "retrieval", "summary"),
    }
    for tag, keywords in keyword_tags.items():
        if any(word in lowered for word in keywords):
            found.add(tag)
    return sorted(found)


def chunk_text(text: str, *, max_words: int = 180, overlap: int = 30) -> list[dict[str, Any]]:
    words = normalize_text(text).split()
    if not words:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    step = max(1, max_words - overlap)
    while start < len(words):
        part = words[start : start + max_words]
        chunk_text_value = " ".join(part)
        chunks.append(
            {
                "index": index,
                "text": chunk_text_value,
                "keywords": sorted(set(tokenize(chunk_text_value)))[:80],
                "word_count": len(part),
            }
        )
        if start + max_words >= len(words):
            break
        start += step
        index += 1
    return chunks


def read_supported_file(path: str | Path) -> tuple[str, dict[str, Any]]:
    """Read a phase-1 supported knowledge file."""

    file_path = Path(path)
    suffix = file_path.suffix.lower()
    metadata = {"path": str(file_path), "extension": suffix, "future_supported": suffix in FUTURE_EXTENSIONS}
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported knowledge source for v1: {suffix or 'no extension'}")
    raw = file_path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        try:
            parsed = json.loads(raw)
            raw = json.dumps(parsed, indent=2, ensure_ascii=True)
            metadata["json_valid"] = True
        except Exception:
            metadata["json_valid"] = False
    return raw, metadata


__all__ = [
    "FUTURE_EXTENSIONS",
    "SUPPORTED_EXTENSIONS",
    "chunk_text",
    "infer_tags",
    "infer_title",
    "normalize_text",
    "read_supported_file",
    "tokenize",
]
