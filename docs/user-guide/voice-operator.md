# Voice Operator Mode

Voice Operator Mode is a command-first desktop control loop for Grandpa. It is
not a chatbot mode: spoken or typed phrases are interpreted as local operator
commands and routed through Grandpa's existing safe PC control layer.

Run:

```powershell
uv run grandpa voice-operator
```

If microphone or speech-to-text support is unavailable, Grandpa falls back to
typed input automatically.

Push-to-talk behavior:

- Press `Enter` to record one command.
- Or type a command directly at the prompt.
- Default recording duration is 4 seconds.

Options:

```powershell
uv run grandpa voice-operator --duration 4
uv run grandpa voice-operator --device 1
uv run grandpa voice-operator --typed
uv run grandpa voice-operator --no-tts
```

Environment variables:

- `GRANDPA_VOICE_DEVICE=1`
- `GRANDPA_VOICE_DURATION=4`
- `GRANDPA_VOICE_TYPED=1`

## Microphone Diagnostics

Check microphone and STT readiness:

```powershell
uv run grandpa voice doctor
```

List available input devices:

```powershell
uv run grandpa voice devices
```

Use the device index with:

```powershell
uv run grandpa voice-operator --device <index>
```

If Grandpa says it did not hear anything, check:

- Windows Settings > Privacy & security > Microphone.
- Allow desktop apps to access the microphone.
- Your default input device.
- Whether the selected microphone shows a non-zero level in `grandpa voice doctor`.

Before opening apps by arbitrary installed app name, scan the local app
inventory:

```powershell
uv run grandpa apps scan
uv run grandpa apps list
uv run grandpa apps find chrome
```

## Supported Commands

Applications:

- `open chrome`
- `open edge`
- `open vscode`
- `open notepad`
- `open calculator`
- `open file explorer`
- `scan my apps`
- `list apps`
- `what apps do I have`
- `find app chrome`
- `open spotify` after it appears in the app inventory

Windows:

- `close this window`
- `minimize this window`
- `maximize this window`
- `restore this window`
- `switch to chrome`
- `focus vscode`

Screen:

- `screenshot`
- `what is on my screen`
- `read my screen`

Keyboard:

- `type hello`
- `press enter`
- `press escape`
- `press tab`

Exit:

- `stop listening`
- `exit`
- `quit`

## Safety Rules

Voice Operator Mode never runs arbitrary shell, PowerShell, or command prompt
instructions from natural language. Desktop actions are converted into existing
Grandpa local action requests, so the same blocking, audit, approval, and
protected-window checks still apply.

Dangerous commands such as deleting all files, formatting drives, shutdown,
restart, or direct shell execution are blocked.

The app inventory scans only bounded Windows app locations: Start Menu
shortcuts, `Program Files`, `Program Files (x86)`, and Grandpa's existing
Windows app resolver. It does not scan the whole drive. Only discovered `.exe`
and `.lnk` launch targets are allowed.

## Speech and Fallback

Grandpa first tries user-initiated local voice input when running in an
interactive terminal. If speech dependencies, microphone access, or local STT
are unavailable, it prints the error and switches to typed commands.

TTS is best-effort. If speech output is unavailable, Grandpa prints the
response only.
