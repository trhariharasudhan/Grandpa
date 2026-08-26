---
title: Installation
description: Install the Grandpa local Windows assistant
---

# Installation

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- Git

Optional local capabilities:

- Tesseract OCR for screen text
- A microphone for voice commands
- Rust for the native acceleration workspace

## Install

```powershell
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync --extra voice --extra screen --extra server
copy .env.example .env
```

Start Ollama and install a local model:

```powershell
ollama serve
ollama pull qwen2.5:3b
```

Verify the environment:

```powershell
uv run grandpa doctor
uv run grandpa --help
```

## First Session

```powershell
uv run grandpa chat
```

For local voice:

```powershell
uv run grandpa voice --diagnose
uv run grandpa voice
```

For action-first voice operation:

```powershell
uv run grandpa voice-operator
```

## Optional API Server

```powershell
uv run grandpa serve --host 127.0.0.1 --port 8000
```

The server is for trusted local integrations. It is not required for CLI chat
or voice use.

## Native Workspace

The Rust workspace is retained for native acceleration:

```powershell
uv run maturin develop -m rust/crates/grandpa-python/Cargo.toml
```

If this optional build is unavailable, the Python CLI and most local assistant
features continue to work.

## Updating

Grandpa is distributed as a git checkout, not as a published package. Update
from your own clone:

```powershell
uv run grandpa self-update
```

That runs `git pull && uv sync` in the checkout. `--check` prints the command
without running it.

`self-update` deliberately refuses on any other install shape. The name
`grandpa` on PyPI belongs to an unrelated project, so `pip install --upgrade
grandpa` and `uv tool upgrade grandpa` would install someone else's software
over your environment — Grandpa never runs either command. For the same reason
there is no automatic "new version available" check: there is no Grandpa
release feed to poll.
