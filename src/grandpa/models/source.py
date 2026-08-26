"""Provider-neutral model acquisition sources and Hugging Face GGUF downloader."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx

from grandpa.models.security import (
    validate_gguf_filename,
    validate_safe_destination_path,
    verify_sha256,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedModelArtifact:
    """Metadata describing a resolved remote model artifact."""

    source_type: str
    repo_id: str
    filename: str
    download_url: str
    revision: str = "main"
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelSource(ABC):
    """Abstract interface for model download sources."""

    @abstractmethod
    def resolve(
        self,
        source_ref: str,
        filename: Optional[str] = None,
        revision: str = "main",
    ) -> ResolvedModelArtifact:
        """Resolve a reference string and optional filename to an artifact descriptor."""

    @abstractmethod
    def download(
        self,
        artifact: ResolvedModelArtifact,
        destination_dir: Path,
        *,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        expected_sha256: Optional[str] = None,
    ) -> Path:
        """Download the artifact into destination_dir and return the final Path."""


class HuggingFaceModelSource(ModelSource):
    """Acquires GGUF model files from Hugging Face model repositories.

    Hugging Face is utilized strictly as an artifact repository/source; all inference
    remains completely in-process and native.
    """

    DEFAULT_BASE_URL = "https://huggingface.co"

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def resolve(
        self,
        source_ref: str,
        filename: Optional[str] = None,
        revision: str = "main",
    ) -> ResolvedModelArtifact:
        """Resolve a repo ID or full HuggingFace path to a ResolvedModelArtifact."""
        ref = source_ref.strip()

        # Handle full URL e.g. https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/model.gguf
        if "huggingface.co/" in ref:
            url_part = ref.split("huggingface.co/", 1)[1]
            parts = [p for p in url_part.split("/") if p]
            if len(parts) >= 4 and parts[2] == "resolve":
                repo_id = f"{parts[0]}/{parts[1]}"
                revision = parts[3]
                filename = parts[4]
            elif len(parts) >= 3 and parts[2] == "blob":
                repo_id = f"{parts[0]}/{parts[1]}"
                revision = parts[3] if len(parts) > 3 else "main"
                filename = parts[-1]
            elif len(parts) >= 3:
                repo_id = f"{parts[0]}/{parts[1]}"
                filename = parts[2]

        # Handle composite string e.g. "Qwen/Qwen2.5-0.5B-Instruct-GGUF/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        elif "/" in ref:
            parts = [p for p in ref.split("/") if p]
            if len(parts) == 3 and parts[2].lower().endswith(".gguf"):
                repo_id = f"{parts[0]}/{parts[1]}"
                filename = parts[2]
            elif len(parts) == 2:
                repo_id = f"{parts[0]}/{parts[1]}"
            else:
                repo_id = ref
        else:
            repo_id = ref

        if not filename:
            raise ValueError(
                f"A GGUF filename must be provided when downloading from Hugging Face repository {repo_id!r}."
            )

        sanitized_filename = validate_gguf_filename(filename)
        download_url = (
            f"{self.base_url}/{repo_id}/resolve/{revision}/{sanitized_filename}"
        )

        return ResolvedModelArtifact(
            source_type="huggingface",
            repo_id=repo_id,
            filename=sanitized_filename,
            download_url=download_url,
            revision=revision,
            sha256=None,
        )

    def download(
        self,
        artifact: ResolvedModelArtifact,
        destination_dir: Path,
        *,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        expected_sha256: Optional[str] = None,
    ) -> Path:
        """Download the GGUF file with atomic replace, chunking, and hash validation."""
        destination_dir.mkdir(parents=True, exist_ok=True)
        final_dest = destination_dir / artifact.filename
        validate_safe_destination_path(final_dest, destination_dir)

        # Temporary file in the same directory to allow atomic os.replace across filesystems
        fd, temp_file_path = tempfile.mkstemp(
            dir=destination_dir,
            prefix=f".{artifact.filename}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_file_path)

        downloaded_bytes = 0
        total_bytes: Optional[int] = None

        try:
            with os.fdopen(fd, "wb") as f_out:
                with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                    with client.stream("GET", artifact.download_url) as resp:
                        resp.raise_for_status()

                        content_len = resp.headers.get("content-length")
                        if content_len and content_len.isdigit():
                            total_bytes = int(content_len)

                        for chunk in resp.iter_bytes(chunk_size=65536):
                            if not chunk:
                                continue
                            f_out.write(chunk)
                            downloaded_bytes += len(chunk)
                            if progress_callback is not None:
                                progress_callback(downloaded_bytes, total_bytes)

                        f_out.flush()
                        os.fsync(f_out.fileno())

            # Validate checksum if supplied in arguments or artifact
            target_hash = expected_sha256 or artifact.sha256
            if target_hash:
                verify_sha256(temp_path, target_hash)

            # Atomic rename / replace
            shutil.move(str(temp_path), str(final_dest))
            return final_dest

        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise


__all__ = [
    "HuggingFaceModelSource",
    "ModelSource",
    "ResolvedModelArtifact",
]
