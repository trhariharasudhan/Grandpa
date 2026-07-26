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
uv run grandpa voice
uv run grandpa start
uv run grandpa status
uv run grandpa stop
uv run grandpa reminders add "remind me in 30 minutes to drink water"
```

## Application Manager

Grandpa can build a local index of installed Windows applications and use that
index from chat, voice, and CLI commands. The index is stored at
`%USERPROFILE%\.grandpa\apps.json`.

```powershell
uv run grandpa apps scan
uv run grandpa apps list
uv run grandpa apps search chrome
uv run grandpa apps running
```

Natural commands such as `Open VS Code`, `Open Spotify`, `Close Chrome`, and
`What apps are running?` route through Grandpa's existing local PC-control
safety layer. Grandpa launches only safe indexed app targets or existing
allowlisted desktop apps, avoids arbitrary shell execution, and asks for
confirmation before medium or high risk actions.

## Screen Vision

Screen Vision is Grandpa's local, read-only view of the Windows desktop. It can
inspect monitors and visible windows, capture screenshots in memory, read
visible text with Tesseract OCR, describe the current screen, and identify
likely visible errors. It never clicks, types, scrolls, submits forms, closes
windows, or executes instructions found on screen.

Install the optional fast multi-monitor capture backend, then diagnose the
local setup:

```powershell
uv sync --extra screen
uv run --no-sync grandpa screen diagnose
uv run --no-sync grandpa screen monitors
uv run --no-sync grandpa screen active
uv run --no-sync grandpa screen windows
```

Capture and analysis commands:

```powershell
uv run --no-sync grandpa screen capture
uv run --no-sync grandpa screen capture --monitor 1
uv run --no-sync grandpa screen capture --active-window
uv run --no-sync grandpa screen read --active-window
uv run --no-sync grandpa screen describe --active-window
uv run --no-sync grandpa screen error --active-window
```

Normal capture, read, describe, and error commands keep screenshots in memory.
A permanent image is written only when explicitly requested:

```powershell
uv run --no-sync grandpa screen capture --save
uv run --no-sync grandpa screen capture --output D:\Screenshots\error.png
```

The default save directory is `%USERPROFILE%\.grandpa\screenshots`. Existing
files are not overwritten unless `--overwrite` is supplied. Output paths are
validated and parent traversal is rejected.

OCR uses the local `pytesseract` package and the Tesseract executable. On
Windows, install Tesseract and make it available on `PATH`, or configure it:

```powershell
$env:GRANDPA_TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:GRANDPA_SCREEN_OCR_LANGUAGE="eng"
$env:GRANDPA_SCREEN_OCR_PREPROCESS="true"
$env:GRANDPA_SCREEN_MAX_OCR_CHARS="6000"
```

Screenshot capture and window inspection continue to work when OCR is missing.
Windows may return a blank or access-denied capture for sign-in, UAC, and other
secure desktops; Grandpa reports that protection instead of attempting to
bypass it. Windows Settings > Privacy & security may also affect capture in
some environments.

Chat and voice reuse the same local intent router. Try `What is on my screen?`,
`Read the visible text`, `Read this error`, `What window is active?`, `List open
windows`, or `Take a screenshot`. Voice responses are shortened while the
terminal retains the fuller redacted result.

Before OCR text is displayed, spoken, logged as metadata, or analyzed, Grandpa
redacts likely passwords, tokens, authorization headers, OTPs, payment-card
numbers, private keys, and database URLs. Suspected password, banking, payment,
Windows Security, or recovery-code screens are refused entirely. Raw screenshots
and OCR text are not written to normal logs.

Known limitations: OCR quality depends on display scaling, font size, language
data, and Tesseract; visible-window metadata depends on Windows APIs; minimized
or protected windows may not be capturable; and descriptions are deterministic
rather than semantic image understanding. A future UI Automation v2 should be
a separate, permission-gated package that consumes Screen Vision results. It
must not add click or keyboard actions to this read-only module.

## Voice Assistant

Grandpa includes an offline-first phrase-by-phrase voice assistant:

```powershell
uv sync --extra voice
uv run grandpa voice
```

The assistant listens through your microphone, transcribes speech locally with
faster-whisper, routes the recognized text through Grandpa's normal safe
command/chat pipeline, prints the response, and speaks it locally with Windows
SAPI voices through `pyttsx3` when available. Say `stop listening`, `exit voice
mode`, `goodbye grandpa`, `quit`, or press `Ctrl+C` to stop.

Useful commands:

```powershell
uv run grandpa voice --model tiny.en
uv run grandpa voice --no-tts
uv run grandpa voice --list-microphones
uv run grandpa voice --list-voices
uv run grandpa voice --language en --device cpu
```

Environment overrides:

```powershell
$env:GRANDPA_VOICE_STT_MODEL="base.en"
$env:GRANDPA_VOICE_LANGUAGE="en"
$env:GRANDPA_VOICE_DEVICE="cpu"
$env:GRANDPA_VOICE_COMPUTE_TYPE="int8"
$env:GRANDPA_VOICE_TTS_ENGINE="pyttsx3"
$env:GRANDPA_VOICE_RATE="175"
$env:GRANDPA_VOICE_VOLUME="1.0"
```

Windows notes:

- Check Settings > Privacy & security > Microphone and allow desktop apps to
  use the microphone.
- `pyttsx3` uses installed Windows SAPI voices.
- The first faster-whisper transcription may download the selected model.
- Audio is captured in memory as short WAV phrases; Grandpa does not store
  permanent recordings.
- Voice input goes through the same safety and confirmation layers as typed
  commands, so destructive actions are not executed directly from raw speech.

Troubleshooting:

- Missing dependencies: run `uv sync --extra voice`, then launch with
  `uv run grandpa voice`. Avoid installing project extras with a global
  `pip`; that installs them into a different Python environment.
- No microphone: run `uv run grandpa voice --list-microphones` and check Windows
  permissions.
- Environment confusion: run `uv run grandpa voice --diagnose`. It reports the
  active Python, virtual environment, Grandpa executable, optional packages,
  and microphone count.
- Windows `Access is denied` while replacing a native FAISS `.pyd`: stop
  Grandpa servers, Python, pytest, notebooks, and IDE debug sessions using the
  project environment, close their terminals, and retry
  `uv sync --extra voice`. If Windows still holds the native library, restart
  Windows and retry. Grandpa never deletes `.venv` or terminates processes
  automatically.
- Slow CPU transcription: try `uv run grandpa voice --model tiny.en --device cpu`.
- TTS unavailable: use `uv run grandpa voice --no-tts`; responses will still be
  printed.

Current limitation: wake-word detection is not always-on in this mode. Future
`openWakeWord` support should attach before `MicrophoneCapture.capture()` as a
small wake provider that gates phrase capture without changing the command
processor.

## Project Launcher and Developer Workflows

Grandpa can register local software projects, open them in a safe editor, run
approved test/lint profiles, inspect service status, and read bounded, redacted
logs. The registry is versioned and stored at
`%USERPROFILE%\.grandpa\projects.json`; commands are stored as argument arrays
and always run with `shell=False` from the registered project root.

```powershell
uv run --no-sync grandpa projects register D:\Grandpa --name Grandpa
uv run --no-sync grandpa projects discover D:\Projects --max-depth 3
uv run --no-sync grandpa projects list
uv run --no-sync grandpa projects show grandpa
uv run --no-sync grandpa projects open grandpa
uv run --no-sync grandpa projects status grandpa
uv run --no-sync grandpa projects test grandpa --profile voice
uv run --no-sync grandpa projects logs grandpa --tail 100
```

The source checkout safely bootstraps a `Grandpa` entry on first use. It reuses
the existing `grandpa start`, `stop`, and `status` lifecycle implementation and
includes validated `test`, `test:voice`, `test:chat`, `test:apps`, and `lint`
profiles. General projects receive detected metadata only; add workflows by
editing the registry with trusted argument arrays until an interactive workflow
editor is available.

Chat and voice use the same project intent handler. Examples include `List my
projects`, `Open Grandpa project`, `Check Grandpa server status`, and `Run
Grandpa voice tests`. Stop and restart require explicit confirmation through
the project CLI. Discovery is bounded to the requested directory and skips
dependency, cache, VCS, and build-output folders.

Process metadata for managed long-running workflows is stored under
`%USERPROFILE%\.grandpa\project-processes.json`. Before a stop, Grandpa checks
that the PID is live and that its executable and command line match the
registered process. Stale or reused PIDs are removed rather than terminated.
On Windows, use `grandpa projects status grandpa` to inspect a server without
calling unsafe `os.kill(pid, 0)` checks. Logs are tail-limited and redact common
authorization, cookie, password, token, and API-key values.

Limitations: project discovery never auto-registers candidates; arbitrary
commands from chat or voice are rejected; terminal targets are not opened by
the project launcher; and general project lifecycle commands must be explicitly
registered before use.

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
