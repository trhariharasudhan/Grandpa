# Daily Use Setup

Grandpa can run with only the core Python package, but the daily assistant
features work best when these optional local tools are ready.

## Required For Typical Daily Use

- **Ollama**: install from <https://ollama.com/download>, start Ollama, then pull
  your default model, for example `ollama pull qwen2.5:3b`.
- **Node.js 22+**: install from <https://nodejs.org/> so the frontend and
  Node-backed integrations can build.
- **Docker Desktop**: install from <https://www.docker.com/products/docker-desktop/>
  and wait for the daemon to finish starting before running Docker validation.

## Screen, OCR, And Desktop Control

- **Pillow**: included in Grandpa dependencies; refresh with
  `uv sync --extra server --link-mode=copy`.
- **pyautogui**: included in Grandpa dependencies; refresh with
  `uv sync --extra server --link-mode=copy`.
- **pytesseract**: included in Grandpa dependencies; refresh with
  `uv sync --extra server --link-mode=copy`.
- **Tesseract OCR executable**: install the Windows Tesseract package and add
  `tesseract.exe` to `PATH`. This is separate from the Python `pytesseract`
  package.

## Validation

Run the doctor first:

```powershell
uv run grandpa doctor
```

For a fuller daily-use smoke pass:

```powershell
uv run python scripts/validate_daily_use.py
```

If you do not want the script to open Notepad while testing the local action
pipeline, use:

```powershell
uv run python scripts/validate_daily_use.py --skip-app-launch
```

The validation script is intentionally conservative. It does not delete files,
overwrite files, run shell automation, or perform dangerous actions. It does
exercise local memory, notes/files, reminders, frontend build, and Docker build
when Docker is available.
