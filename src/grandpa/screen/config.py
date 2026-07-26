"""Environment-backed Screen Vision configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.screen.errors import ScreenConfigurationError


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return (
        default
        if value is None
        else value.strip().casefold() not in {"0", "false", "no", "off"}
    )


def _int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError as exc:
        raise ScreenConfigurationError(f"{name} must be an integer.") from exc


@dataclass(frozen=True)
class ScreenConfig:
    ocr_language: str = "eng"
    preprocess_ocr: bool = True
    max_ocr_chars: int = 6000
    tesseract_cmd: str = ""
    screenshots_dir: Path = DEFAULT_CONFIG_DIR / "screenshots"
    temp_dir: Path = DEFAULT_CONFIG_DIR / "screen-temp"

    @classmethod
    def load(cls) -> ScreenConfig:
        return cls(
            ocr_language=os.environ.get("GRANDPA_SCREEN_OCR_LANGUAGE", "eng").strip()
            or "eng",
            preprocess_ocr=_bool_env("GRANDPA_SCREEN_OCR_PREPROCESS", True),
            max_ocr_chars=_int_env("GRANDPA_SCREEN_MAX_OCR_CHARS", 6000, minimum=200),
            tesseract_cmd=os.environ.get("GRANDPA_TESSERACT_CMD", "").strip(),
            screenshots_dir=Path(
                os.environ.get(
                    "GRANDPA_SCREENSHOTS_DIR", DEFAULT_CONFIG_DIR / "screenshots"
                )
            ).expanduser(),
            temp_dir=Path(
                os.environ.get(
                    "GRANDPA_SCREEN_TEMP_DIR", DEFAULT_CONFIG_DIR / "screen-temp"
                )
            ).expanduser(),
        )


__all__ = ["ScreenConfig"]
