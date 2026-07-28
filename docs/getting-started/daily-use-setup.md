# Daily Use Setup

## Local Requirements

- Ollama with the configured model
- The project virtual environment managed by uv
- Optional microphone and Windows speech output for voice
- Optional Tesseract executable for OCR

```powershell
uv sync --extra voice --extra screen --extra server --link-mode=copy
uv run grandpa doctor
```

## Conservative Validation

```powershell
uv run python scripts/validate_daily_use.py --skip-app-launch
```

The validator checks CLI, local memory, notes/files, reminders, and safe action
parsing. It does not
delete files, overwrite user data, or run arbitrary shell automation.
