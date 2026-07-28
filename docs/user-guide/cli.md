# Command-Line Interface

Run commands from the repository with `uv run grandpa`.

## Daily Commands

```powershell
uv run grandpa doctor
uv run grandpa chat
uv run grandpa start
uv run grandpa status
uv run grandpa stop
uv run grandpa voice --diagnose
uv run grandpa voice-operator
```

## Windows Control

```powershell
uv run grandpa apps scan
uv run grandpa apps list
uv run grandpa automation --help
uv run grandpa screen active
uv run grandpa screen describe --active-window
```

## Personal Data

```powershell
uv run grandpa reminders list
uv run grandpa reminders add "remind me in 30 minutes to drink water"
uv run grandpa skill list
```

Skills are loaded only from the workspace `skills` directory and the user's
`%USERPROFILE%\.grandpa\skills` directory. Remote skill marketplaces and
source-sync commands are not supported.

## Local Inference

Ollama is the supported engine:

```powershell
ollama serve
ollama pull qwen2.5:3b
uv run grandpa chat --engine ollama --model qwen2.5:3b
```

## Local API

```powershell
uv run grandpa serve --host 127.0.0.1 --port 8000
```

The API is optional. Chat, voice, and desktop automation do not require a
public server.
