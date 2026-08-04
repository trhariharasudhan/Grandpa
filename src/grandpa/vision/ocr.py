"""Optional OCR support for user-uploaded Vision Mode images."""

from __future__ import annotations

from importlib import import_module, util
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

OCR_UNAVAILABLE_MESSAGE = (
    "OCR is not available. Install OCR dependencies to extract text."
)


def ocr_status() -> dict[str, Any]:
    """Return OCR backend availability without importing heavy modules eagerly."""
    available = util.find_spec("pytesseract") is not None
    return {
        "available": available,
        "engine": "pytesseract" if available else "none",
        "error": None if available else OCR_UNAVAILABLE_MESSAGE,
    }


def extract_text_from_image_bytes(data: bytes, mime_type: str | None) -> dict[str, Any]:
    """Extract text with pytesseract when available, otherwise return a friendly placeholder."""
    if not data:
        return {
            "available": False,
            "text": "",
            "engine": "none",
            "error": "Empty image file.",
        }

    if util.find_spec("pytesseract") is None:
        return {
            "available": False,
            "text": OCR_UNAVAILABLE_MESSAGE,
            "engine": "none",
            "error": OCR_UNAVAILABLE_MESSAGE,
        }

    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            pytesseract = _load_pytesseract()
            text = pytesseract.image_to_string(image).strip()
    except (UnidentifiedImageError, OSError, ValueError):
        return {
            "available": False,
            "text": "",
            "engine": "pytesseract",
            "error": "Invalid image file.",
        }
    except Exception as exc:
        return {
            "available": False,
            "text": "",
            "engine": "pytesseract",
            "error": f"OCR failed: {exc}",
        }

    return {
        "available": True,
        "text": text,
        "engine": "pytesseract",
        "error": None,
    }


def _load_pytesseract() -> Any:
    return import_module("pytesseract")
