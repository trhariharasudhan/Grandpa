# Release Checklist

## Automated Gates

```powershell
uv lock
uv sync --extra dev --extra server --extra voice --extra screen
python -m compileall -q src scripts tests
uv run --no-sync ruff check src tests scripts
python -m pytest -q
git diff --check
uv build
```

## Windows Smoke Tests

Run on a clean Windows user profile:

```powershell
uv run grandpa --help
uv run grandpa doctor
uv run grandpa status
uv run grandpa apps scan
uv run grandpa screen active
uv run grandpa automation --help
uv run grandpa reminders --help
```

Manually verify one Ollama chat turn, push-to-talk diagnostics, screen OCR, and
a harmless application action. Do not automate real clicks, destructive
actions, email sending, or calendar changes in release tests.

## Security Review

- API defaults to loopback.
- Destructive actions require confirmation.
- No remote analytics or cloud inference fallback is enabled.
- OAuth credentials and `%USERPROFILE%\.grandpa` data are absent from artifacts.
- Wheel contents contain no deleted bridge, deployment, or research packages.
