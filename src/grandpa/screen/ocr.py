"""Lazy local OCR for in-memory screenshots."""

from __future__ import annotations

import logging
import shutil
import time
from importlib import import_module, util
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter

from grandpa.screen.config import ScreenConfig
from grandpa.screen.errors import OcrProcessingError, OcrUnavailableError
from grandpa.screen.models import OcrBlock, OcrResult

logger = logging.getLogger(__name__)
COMMON_TESSERACT_PATHS = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


def normalize_ocr_text(text: str, *, max_chars: int = 6000) -> str:
    lines = [
        " ".join(line.split())
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if cleaned and not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False
    return "\n".join(cleaned).strip()[:max_chars]


def find_tesseract(configured: str = "") -> str:
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() else ""
    discovered = shutil.which("tesseract")
    if discovered:
        return discovered
    return str(next((path for path in COMMON_TESSERACT_PATHS if path.is_file()), ""))


def preprocess_image(image: Image.Image) -> Image.Image:
    processed = image.convert("L")
    if min(processed.size) < 900:
        processed = processed.resize((processed.width * 2, processed.height * 2))
    processed = ImageEnhance.Contrast(processed).enhance(1.35)
    return processed.filter(ImageFilter.SHARPEN)


class TesseractOcrEngine:
    def __init__(self, config: ScreenConfig | None = None) -> None:
        self.config = config or ScreenConfig.load()

    def status(self) -> dict[str, Any]:
        package = util.find_spec("pytesseract") is not None
        executable = find_tesseract(self.config.tesseract_cmd)
        return {
            "available": package and bool(executable),
            "provider": "pytesseract" if package else "none",
            "executable": executable,
            "language": self.config.ocr_language,
            "message": (
                "Tesseract OCR is ready."
                if package and executable
                else "Tesseract OCR is not available. Screenshot capture and window inspection still work. "
                "Install Tesseract OCR or configure GRANDPA_TESSERACT_CMD to enable text reading."
            ),
        }

    def extract_text(
        self, image: Image.Image, *, language: str | None = None
    ) -> OcrResult:
        status = self.status()
        if not status["available"]:
            raise OcrUnavailableError(str(status["message"]))
        started = time.perf_counter()
        try:
            pytesseract = import_module("pytesseract")
            pytesseract.pytesseract.tesseract_cmd = status["executable"]
            candidate = (
                preprocess_image(image) if self.config.preprocess_ocr else image.copy()
            )
            lang = language or self.config.ocr_language
            raw = pytesseract.image_to_string(candidate, lang=lang)
            text = normalize_ocr_text(raw, max_chars=self.config.max_ocr_chars)
            blocks, confidence = _extract_blocks(pytesseract, candidate, lang)
        except OcrUnavailableError:
            raise
        except Exception as exc:
            raise OcrProcessingError("OCR could not process the screenshot.") from exc
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "Screen OCR completed provider=pytesseract chars=%s duration_ms=%.1f",
            len(text),
            duration_ms,
        )
        return OcrResult(
            text=text,
            confidence=confidence,
            word_count=len(text.split()),
            language=lang,
            duration_ms=duration_ms,
            blocks=blocks,
            message="OCR completed locally."
            if text
            else "OCR ran but no readable text was detected.",
        )


def _extract_blocks(
    pytesseract: Any, image: Image.Image, language: str
) -> tuple[tuple[OcrBlock, ...], float]:
    try:
        data = pytesseract.image_to_data(
            image, lang=language, output_type=pytesseract.Output.DICT
        )
    except Exception:
        return (), 0.0
    blocks: list[OcrBlock] = []
    confidences: list[float] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            confidence = -1
        if confidence >= 0:
            confidences.append(confidence)
        bounds = (
            int(data.get("left", [0])[index]),
            int(data.get("top", [0])[index]),
            int(data.get("width", [0])[index]),
            int(data.get("height", [0])[index]),
        )
        blocks.append(OcrBlock(text, max(0.0, confidence / 100), bounds))
    average = sum(confidences) / len(confidences) / 100 if confidences else 0.0
    return tuple(blocks[:500]), average


__all__ = [
    "TesseractOcrEngine",
    "find_tesseract",
    "normalize_ocr_text",
    "preprocess_image",
]
