"""Security, path safety, and checksum verification for local model artifacts."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path


class ModelSecurityError(ValueError):
    """Raised when a model filename or destination path fails security checks."""


class ChecksumMismatchError(ValueError):
    """Raised when a downloaded model file fails SHA-256 hash validation."""


_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-\.\:\+]+$")


def validate_gguf_filename(filename: str) -> str:
    """Validate and sanitize a GGUF filename.

    Guarantees that the filename is a single basename ending in ``.gguf`` without
    path traversal sequences or directory separators.
    """
    if not filename or not isinstance(filename, str):
        raise ModelSecurityError("Model filename cannot be empty.")

    clean_name = filename.strip()
    base_name = os.path.basename(clean_name)

    if base_name != clean_name:
        raise ModelSecurityError(
            f"Path traversal detected in model filename: {filename!r}"
        )

    if ".." in clean_name or "/" in clean_name or "\\" in clean_name:
        raise ModelSecurityError(f"Invalid characters in model filename: {filename!r}")

    if not clean_name.lower().endswith(".gguf"):
        raise ModelSecurityError(
            f"Model file must have a .gguf extension, got: {filename!r}"
        )

    # Ensure no control characters or shell injection characters
    if not _SAFE_FILENAME_RE.match(clean_name):
        raise ModelSecurityError(
            f"Model filename contains illegal characters: {filename!r}"
        )

    return clean_name


def validate_safe_destination_path(destination: Path, allowed_parent: Path) -> Path:
    """Ensure the destination path resides strictly within the allowed directory."""
    dest_resolved = destination.resolve()
    parent_resolved = allowed_parent.resolve()

    try:
        dest_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ModelSecurityError(
            f"Destination path {dest_resolved} is outside allowed model directory {parent_resolved}"
        ) from exc

    return dest_resolved


def verify_sha256(file_path: Path, expected_sha256: str) -> bool:
    """Verify that a file matches the expected SHA-256 digest."""
    if not file_path.is_file():
        return False

    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)

    actual = hasher.hexdigest().lower()
    expected = expected_sha256.strip().lower()

    if not hmac.compare_digest(actual, expected):
        raise ChecksumMismatchError(
            f"SHA-256 checksum mismatch for {file_path.name}: expected {expected}, got {actual}"
        )
    return True


__all__ = [
    "ChecksumMismatchError",
    "ModelSecurityError",
    "validate_gguf_filename",
    "validate_safe_destination_path",
    "verify_sha256",
]
