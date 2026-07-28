# Contributing to Grandpa

Grandpa is a privacy-first, local Windows assistant. Contributions should
strengthen reliable voice interaction, safe desktop automation, screen
understanding, personal organization, and local Ollama inference.

## Good Contributions

- Reproducible Windows bug fixes with regression tests
- Safety improvements for desktop, browser, file, and process actions
- Voice, wake-word, speech-to-text, and text-to-speech reliability
- Accessibility, OCR, and screen-awareness improvements
- Local memory, reminders, notes, Gmail, and Calendar integration quality
- Documentation and focused test coverage

Open an issue before starting a large refactor, adding a major dependency, or
changing a public API. Grandpa does not accept new social-channel adapters,
cloud inference providers, telemetry collection, model-training pipelines, or
unrestricted shell automation.

## Development Setup

Prerequisites:

- Windows 10 or 11
- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/download/windows)

```powershell
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync --extra dev --extra server --extra voice --extra screen
uv run pre-commit install
```

Start Ollama and pull a local model:

```powershell
ollama serve
ollama pull qwen3.5:2b
```

## Validation

Run focused tests for the code you change first, then the broader checks:

```powershell
uv run python -m pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
git diff --check
```

Tests must not perform real clicks, key presses, microphone capture, purchases,
email/calendar mutations, or other external side effects. Mock those boundaries.

## Pull Requests

- Keep each pull request focused and behavior-preserving.
- Add regression tests for fixes and safety tests for new actions.
- Document user-visible commands and configuration.
- Use Conventional Commits, for example:

```text
fix(voice): stop capture promptly on cancellation
feat(automation): add confirmed window action
docs: clarify local Ollama setup
```

See [Development Guide](docs/development/contributing.md),
[Repository Structure](docs/development/repo-structure.md), and
[Security](SECURITY.md) for more detail.
