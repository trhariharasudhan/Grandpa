# Contributing

Grandpa targets a privacy-focused local Windows assistant. Changes should
strengthen voice, automation, screen understanding, local inference, safety, or
trusted personal integrations.

## Setup

```powershell
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync --extra dev --extra server --extra voice --extra screen
```

## Validation

Run focused tests first, then:

```powershell
python -m compileall -q src scripts tests
uv run --no-sync ruff check src tests scripts
python -m pytest -q
git diff --check
uv build
```

Tests must mock desktop input, microphone, OAuth, browser, and network behavior.
Never let an automated test click the real desktop, send mail, alter a calendar,
or call a live model provider.

## Design Rules

- Parse natural language separately from execution.
- Route actions through typed requests and the existing safety policy.
- Require confirmation for destructive, financial, authentication, or
  system-wide actions.
- Keep Ollama and loopback services local by default.
- Avoid remote analytics, cloud inference fallback, arbitrary shell execution,
  and hidden credential access.
- Preserve existing public command behavior unless the change documents a
  migration.
