# Grandpa

Grandpa is a privacy-focused local Windows AI assistant designed to control
applications, windows, files, keyboard, mouse, screen interactions, and system
operations through natural-language voice and CLI commands.

The primary runtime is Python. Ollama provides local language-model inference,
and every desktop action passes through Grandpa's permission, confirmation, and
audit layers. There is no bundled web dashboard, desktop shell, browser
extension, mobile client, or third-party plugin runtime.

## Quick Start on Windows

Install Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/), then run:

```powershell
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync --extra voice --extra screen --extra server
ollama pull qwen2.5:3b
uv run grandpa doctor
uv run grandpa chat
```

Start Ollama first if it is not already running:

```powershell
ollama serve
```

## Core Commands

```powershell
uv run grandpa --help
uv run grandpa doctor
uv run grandpa chat
uv run grandpa voice
uv run grandpa voice-operator
uv run grandpa status
uv run grandpa start
uv run grandpa stop
uv run grandpa automation --help
uv run grandpa screen active
uv run grandpa screen describe --active-window
uv run grandpa apps scan
uv run grandpa projects list
uv run grandpa reminders add "remind me in 30 minutes to drink water"
```

## Voice Assistant

Install the local speech stack:

```powershell
uv sync --extra voice
uv run grandpa voice --diagnose
uv run grandpa voice
```

Grandpa records short phrases only while local voice mode is active, transcribes
them with faster-whisper, routes the text through the same safety layer used by
the CLI, and speaks responses through Windows SAPI when available. Voice mode
does not permit raw shell execution or bypass action confirmation.

Useful diagnostics:

```powershell
uv run grandpa voice --list-microphones
uv run grandpa voice --list-voices
uv run grandpa voice --model tiny.en --device cpu
```

## Windows Automation

Grandpa supports permission-aware application discovery, window control,
keyboard and mouse automation, screen element location, screenshots, OCR,
files, folders, processes, and selected system operations.

Low-risk actions such as focusing a window or reading the screen may run
directly. Destructive, authentication-related, payment-related, or system power
actions require confirmation or are blocked. Grandpa never treats model output
as permission.

Examples:

```text
Open VS Code.
Focus Chrome.
Read the active window.
Find the Save button.
Scroll down.
Type hello in Notepad.
Show my Downloads.
What processes are using the most memory?
```

## Screen Understanding

Install optional capture support and verify OCR:

```powershell
uv sync --extra screen
uv run grandpa screen diagnose
uv run grandpa screen monitors
uv run grandpa screen active
uv run grandpa screen read --active-window
uv run grandpa screen describe --active-window
```

Screenshots remain in memory unless a save option is explicitly requested.
Grandpa redacts likely passwords, tokens, OTPs, payment-card numbers, private
keys, and authorization data before displaying or logging recognized text.
Secure desktops and protected windows are not bypassed.

## Local API

The optional FastAPI server is retained for local integrations and
OpenAI-compatible clients:

```powershell
uv sync --extra server
uv run grandpa serve --host 127.0.0.1 --port 8000
```

The server binds to loopback by default and is authenticated by default: on
first run it generates an API key, prints it, and stores it in
`~/.grandpa/config.toml`. Pass it as `Authorization: Bearer <key>`, or override
it with `GRANDPA_API_KEY`. Use `--no-auth` only where every local process is
trusted. Browser origins are not enabled by default; configure CORS explicitly
only for a trusted local client.

## Development

```powershell
uv sync --extra dev --extra server --extra voice --extra screen
uv run --with pytest python -m pytest
uv run --with ruff ruff check src tests
cargo test --manifest-path rust/Cargo.toml
git diff --check
```

## Troubleshooting

- **Ollama unavailable:** run `ollama serve`, then `uv run grandpa doctor`.
- **Model missing:** run `ollama pull <model-name>` and verify with `ollama list`.
- **Microphone unavailable:** check Windows microphone privacy settings and run
  `uv run grandpa voice --list-microphones`.
- **OCR unavailable:** install Tesseract OCR and place `tesseract.exe` on
  `PATH`, or set `GRANDPA_TESSERACT_CMD`.
- **Server stopped:** use `uv run grandpa start` and `uv run grandpa status`.
- **Windows notifications unavailable:** reminders still work without the
  optional toast-notification dependency.

## Focused Roadmap

1. Reliable voice-command pipeline
2. Accurate intent parsing
3. Windows application control
4. Screen understanding
5. Mouse and keyboard automation
6. File and folder management
7. Safe system operations
8. Context-aware multi-step automation
9. Local AI performance improvements
10. Voice feedback and error recovery
11. Permission controls and audit logs
12. Comprehensive Windows regression testing

## Documentation

- [Installation](docs/getting-started/installation.md)
- [Quick start](docs/getting-started/quickstart.md)
- [Repository structure](docs/development/repo-structure.md)
- [Roadmap](docs/development/roadmap.md)
- [Security](docs/user-guide/security.md)

## Origins and Attribution

Grandpa is a derivative work of [OpenJarvis](https://github.com/open-jarvis),
an Apache-2.0 project by The OpenJarvis Authors, which is itself derived in
part from IPW (Intelligence-per-Watt). This repository retains the upstream
commit history: work up to 2026-05-22 is the OpenJarvis contributors'; Grandpa
was established on 2026-05-23 and has since been substantially rewritten around
a Windows-first local assistant, where OpenJarvis was a general agent and
inference platform.

Copyright and attribution for both works are recorded in [LICENSE](LICENSE) and
[NOTICE](NOTICE). Third-party components, including the vendored FFmpeg build
used by the optional voice runtime, are listed in [NOTICE](NOTICE).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
