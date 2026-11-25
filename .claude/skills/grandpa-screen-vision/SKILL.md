---
name: grandpa-screen-vision
description: Work on Grandpa's screen awareness - screenshots (mss), Tesseract OCR, redaction, the private-apps list and password-box protection, grandpa-eyes local vision descriptions, reading the front window through UI Automation, pressing a named button (screen_click), and the vision engine (controls, graph, matcher). Use for "what's on my screen", OCR quality, read/click-in-window features, or any change that captures pixels or accessibility text.
---

# Grandpa screen and vision

Perception is a privacy boundary: before a pixel is grabbed or a UIA element is
read, `screen/privacy.py` must say yes. Treat every screen feature as
read-only unless it is a catalogued, confirmed action (`screen_click` asks every time).

## Map

| Concern | Path |
|---|---|
| Privacy gate (private apps, password boxes) | `screen/privacy.py`; user list `~/.grandpa/screen-private.txt`; `grandpa screen private` |
| Redaction of captured text | `screen/redaction.py` (also used by `grandpa oops`) |
| Capture / monitors / windows | `screen/capture.py`, `screen/windows.py`, `screen/models.py` |
| OCR (Tesseract via pytesseract) | `screen/ocr.py`; `GRANDPA_TESSERACT_CMD`, `GRANDPA_SCREEN_OCR_LANGUAGE`, `GRANDPA_SCREEN_OCR_PREPROCESS`, `GRANDPA_SCREEN_MAX_OCR_CHARS` |
| Describe with a local VLM | `screen/eyes.py` (`grandpa-eyes`, fallback `llava`; `GRANDPA_SCREEN_EYES`, `GRANDPA_SCREEN_EYES_TIMEOUT`) |
| Read front window (UIA text, else OCR) | `screen/window_text.py` → action `read_window` |
| Press a named control (UIA Invoke/Toggle/Select, no synthetic mouse) | `screen/window_click.py` → action `screen_click` (in `_ALWAYS_CONFIRM`) |
| Service façade | `screen/service.py`, `screen/analyzer.py`, `screen/intents.py` |
| Vision engine (controls, element graph, matcher, highlight) | `vision/` (`service.py`, `uia.py`, `graph.py`, `matcher.py`, `local_model.py`) |
| Older duplicate | `screen_awareness.py` (flat module; own `OcrResult`) and `desktop_context.py` (`MonitorInfo`, protected-window keywords) |
| CLI | `grandpa screen active|capture|describe|window|read|click|private|diagnose|monitors|windows`, `grandpa vision …` |

## Workflow

1. Reproduce with the CLI in a sandbox: `GRANDPA_HOME=$(mktemp -d) uv run grandpa screen diagnose`
   (shows OCR/Tesseract/mss/pywin32 availability). Most paths are Windows-only; on Linux they must
   degrade to a clear message, not crash.
2. Decide the layer: capture → privacy gate → (UIA text | OCR) → redaction → model. A fix belongs at one layer.
3. New screen capability that *acts* → add it via `grandpa-action-layer` with confirmation; reading-only
   capability → still check the privacy gate first in your code path.
4. Tests mock capture, UIA and Tesseract; never take a real screenshot in tests (host state is pinned by
   `tests/host_state.py`). Run `uv run python -m pytest tests/test_screen_*.py tests/test_vision_*.py tests/test_screen_awareness.py -q`.
5. Manual QA: `docs/testing/vision-ocr-manual-qa.md`, `vision-mode-manual-qa.md`, `vision-local-model-manual-qa.md`.

## Constraints

- Never capture or OCR a window on the private list or a password field; never send such content to a model.
- Never write screenshots outside the sandbox/`GRANDPA_SCREENSHOTS_DIR`; clean temp images (`GRANDPA_SCREEN_TEMP_DIR`).
- No synthetic mouse for "click the button": `screen_click` uses UIA patterns by design.
- OCR text from the screen is untrusted input to the model (no injection scanning exists today); do not let it
  trigger actions without the normal confirmation path.
- `screen_awareness.py` vs `screen/` duplication: extend `screen/`, and only touch the flat module to keep callers working.
