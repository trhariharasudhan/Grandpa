# Grandpa

Grandpa - personal AI assistant backend with composable intelligence primitives.

## Prerequisites

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for dependency management.
- [Ollama](https://ollama.com/) for local model inference.
- Windows, macOS, and Linux are supported for the core CLI/server workflow.

For local chat, install Ollama and pull a small model such as:

```sh
ollama pull qwen2.5:3b
```

## Quick start

```sh
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync
cp .env.example .env
# Edit .env if you need a custom Ollama host, cloud API keys, or integrations.
uv run grandpa doctor
uv run grandpa chat
```

## What works now

- Local CLI chat through the `grandpa` command.
- Ollama-backed local model routing.
- OpenAI-compatible REST API server support through the server extra.
- Doctor/readiness checks for engines, local runtime, safety, and daily-use features.
- Local-first memory, knowledge, browser snapshot, desktop diagnostics, coding analysis, and safety/audit foundations.
- Optional integrations and advanced features are available through extras and may require additional setup.

## Documentation

More setup, architecture, release, testing, and user guides live in [docs/](docs/).

## Repository Documentation

- [Repository structure](docs/development/repo-structure.md)
- [Local generated artifacts](docs/development/local-artifacts.md)

## License

Apache-2.0.
