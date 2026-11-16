"""grandpa-eyes: a local vision model's plain-language look at the screen.

OCR reads the letters on the screen; it cannot say "a YouTube video is playing
next to a VS Code window with a red error". This asks the local vision model
(the ``eyes`` role, ``grandpa-eyes`` in Ollama, falling back to ``llava``) for
two or three calm sentences about the screenshot, with the redacted OCR text
as a hint.

It is an addition, never a requirement: when Ollama is not running, the model
is not installed, the image cannot be opened, or it is turned off with
``GRANDPA_SCREEN_EYES=off``, the caller gets ``available=False`` and a short
note, and describes the screen from OCR alone as before.

Safety: the caller has already refused a screen whose title or OCR text looks
like a credential or payment screen. The model sees pixels, which OCR may have
missed, so its answer is redacted the same way, and if the answer itself looks
like a credential screen the result says ``sensitive=True`` and the caller
refuses the whole description.
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.screen.redaction import is_sensitive_screen, redact_screen_text

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 1280
"""Long side, in pixels, of the image sent to the model.

A 1920x1080 screenshot is shrunk to 1280x720: text in a window stays legible,
and the model on an integrated GPU answers several times faster.
"""

MAX_SUMMARY_CHARS = 600
MAX_OCR_HINT_CHARS = 1500
DEFAULT_TIMEOUT_SECONDS = 90.0

EYES_PROMPT = (
    "You are Grandpa's eyes. Look at this screenshot of the user's Windows "
    "screen and say, in two or three short, calm sentences, what is on it: "
    "which app or page is in front, what it is showing, and anything that "
    "needs attention such as an error or a dialog. Do not repeat passwords, "
    "keys, card numbers or other secrets. Do not invent details you cannot see."
)

Analyzer = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class EyesSummary:
    """What the vision model said about the screen, or why it said nothing."""

    available: bool
    text: str = ""
    model: str | None = None
    note: str = ""
    sensitive: bool = False


def eyes_enabled() -> bool:
    """On unless ``GRANDPA_SCREEN_EYES`` is set to off/0/false/no."""
    value = os.environ.get("GRANDPA_SCREEN_EYES", "").strip().casefold()
    return value not in {"0", "off", "false", "no", "disabled"}


def eyes_timeout() -> float:
    raw = os.environ.get("GRANDPA_SCREEN_EYES_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(5.0, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def prepare_image(source: Any) -> bytes | None:
    """Return a downscaled JPEG of ``source``, or None if it is not an image.

    ``source`` is a path, raw image bytes, or a Pillow image.
    """
    try:
        from PIL import Image
    except Exception:  # pragma: no cover - Pillow is a core dependency
        return None
    try:
        if isinstance(source, Image.Image):
            image = source.copy()
        elif isinstance(source, bytes | bytearray):
            image = Image.open(io.BytesIO(bytes(source)))
            image.load()
        elif isinstance(source, str | Path):
            with Image.open(source) as opened:
                opened.load()
                image = opened.copy()
        else:
            return None
        image = image.convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()
    except Exception as exc:
        logger.debug("grandpa-eyes could not open the screenshot: %s", exc)
        return None


def build_prompt(*, ocr_text: str = "", window_title: str = "") -> str:
    parts = [EYES_PROMPT]
    if window_title:
        parts.append(f"The window in front is titled: {window_title}")
    hint = " ".join(redact_screen_text(ocr_text).text.split())[:MAX_OCR_HINT_CHARS]
    if hint:
        parts.append("Text read from the screen by OCR (may contain mistakes): " + hint)
    return "\n\n".join(parts)


def look(
    image: Any,
    *,
    ocr_text: str = "",
    window_title: str = "",
    analyze: Analyzer | None = None,
) -> EyesSummary:
    """Ask the local vision model what is on the screen."""
    if not eyes_enabled():
        return EyesSummary(False)
    data = prepare_image(image)
    if data is None:
        return EyesSummary(False, note="The screenshot could not be opened.")
    if analyze is None:
        from grandpa.vision.local_model import analyze_image_with_local_model

        analyze = analyze_image_with_local_model
    prompt = build_prompt(ocr_text=ocr_text, window_title=window_title)
    try:
        result = analyze(
            data, "screen.jpg", "image/jpeg", prompt, timeout=eyes_timeout()
        )
    except Exception as exc:
        logger.info("grandpa-eyes failed: %s", exc)
        return EyesSummary(False, note=f"grandpa-eyes failed: {exc}")
    model = result.get("model")
    if not result.get("available"):
        return EyesSummary(
            False, model=model, note=str(result.get("error") or "unavailable")
        )
    text = " ".join(str(result.get("analysis") or "").split())
    if is_sensitive_screen(text=text):
        logger.warning("grandpa-eyes described a sensitive screen; dropped")
        return EyesSummary(False, model=model, sensitive=True)
    text = redact_screen_text(text).text.strip()
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS].rstrip() + "..."
    if not text:
        return EyesSummary(False, model=model, note="grandpa-eyes said nothing.")
    return EyesSummary(True, text, model)


__all__ = [
    "EYES_PROMPT",
    "EyesSummary",
    "build_prompt",
    "eyes_enabled",
    "eyes_timeout",
    "look",
    "prepare_image",
]
