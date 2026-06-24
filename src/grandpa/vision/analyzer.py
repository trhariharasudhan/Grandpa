"""User-initiated image validation for Vision Mode V1."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

PLACEHOLDER_ANALYSIS = "placeholder analysis"

SUPPORTED_MIME_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/webp": "webp",
}
SUPPORTED_EXTENSIONS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


@dataclass(frozen=True)
class VisionAnalysis:
    success: bool
    filename: str
    width: int | None
    height: int | None
    format: str | None
    analysis: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "analysis": self.analysis,
            "error": self.error,
        }


class VisionAnalyzer:
    """Validate image uploads and return deterministic placeholder analysis."""

    def analyze(self, data: bytes, filename: str | None, mime_type: str | None) -> VisionAnalysis:
        safe_filename = (filename or "uploaded-image").strip() or "uploaded-image"
        normalized_mime = (mime_type or "").split(";")[0].strip().lower()
        if not data:
            return self._error(safe_filename, "Empty image file.")

        if not self._is_supported(safe_filename, normalized_mime):
            return self._error(
                safe_filename,
                "Unsupported image type. Upload a PNG, JPG, JPEG, or WEBP image.",
            )

        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                image_format = (image.format or self._format_from_hint(safe_filename, normalized_mime) or "").lower()
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError):
            return self._error(safe_filename, "Invalid image file.")

        return VisionAnalysis(
            success=True,
            filename=safe_filename,
            width=int(width),
            height=int(height),
            format=image_format,
            analysis=PLACEHOLDER_ANALYSIS,
        )

    def _error(self, filename: str, message: str) -> VisionAnalysis:
        return VisionAnalysis(
            success=False,
            filename=filename,
            width=None,
            height=None,
            format=None,
            analysis=None,
            error=message,
        )

    def _is_supported(self, filename: str, mime_type: str) -> bool:
        if mime_type in SUPPORTED_MIME_TYPES:
            return True
        return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS

    def _format_from_hint(self, filename: str, mime_type: str) -> str | None:
        if mime_type in SUPPORTED_MIME_TYPES:
            return SUPPORTED_MIME_TYPES[mime_type]
        return SUPPORTED_EXTENSIONS.get(Path(filename).suffix.lower())
