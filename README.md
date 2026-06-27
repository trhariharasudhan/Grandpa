# Grandpa

Grandpa is a local-first personal AI assistant for your desktop and command line.
It combines chat, local model routing, reminders, safe desktop actions, memory,
vision foundations, and server APIs into one Python-based assistant framework.

## Quick Start For Windows

Install Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/). Then run:

```powershell
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync
copy .env.example .env
uv run grandpa doctor
uv run grandpa chat
```

Edit `.env` only if you need custom Ollama hosts, cloud API keys, or optional
integrations.

## Ollama Setup

Start Ollama:

```powershell
ollama serve
```

In another terminal, pull a local chat model:

```powershell
ollama pull qwen2.5:3b
ollama list
```

If you configure a different model in Grandpa, make sure it appears in
`ollama list`.

## Common Commands

```powershell
uv run grandpa doctor
uv run grandpa chat
uv run grandpa start
uv run grandpa status
uv run grandpa stop
uv run grandpa reminders add "remind me in 30 minutes to drink water"
```

## Troubleshooting

- Ollama not running: start it with `ollama serve`, then retry `uv run grandpa doctor`.
- Model not installed: run `ollama pull <model-name>` and verify with `ollama list`.
- Server not running: start it with `uv run grandpa start`, check with `uv run grandpa status`, and stop it with `uv run grandpa stop`.
- Windows notifications: reminder toasts use an optional dependency. If notifications are unavailable, install the Windows notification extra or keep using CLI/server reminders without toast popups.

## What Works Now

- Local CLI chat through the `grandpa` command.
- Ollama-backed local model routing.
- OpenAI-compatible REST API server support through the server extra.
- Doctor/readiness checks for engines, local runtime, safety, and daily-use features.
- Local reminders, local-first memory, knowledge, browser snapshot, desktop diagnostics, coding analysis, and safety/audit foundations.
- Optional integrations and advanced features are available through extras and may require additional setup.

## Documentation

More setup, architecture, release, testing, and user guides live in [docs/](docs/).

## Repository Documentation

- [Repository structure](docs/development/repo-structure.md)
- [Local generated artifacts](docs/development/local-artifacts.md)

## License

Apache-2.0.
