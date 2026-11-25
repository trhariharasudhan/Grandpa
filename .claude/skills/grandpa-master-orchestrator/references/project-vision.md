# GRANDPA project vision and product rules

Shared knowledge for every GRANDPA skill. Verified against `main` @ `fde2164`
(2026-11-24). The owner (addressed as **Captain** in code and docs) decides
scope. Claude proposes, and does not decide scope.

## What Grandpa is

A **privacy-focused, local, Windows-first personal AI assistant**. It controls
applications, windows, files, keyboard, mouse, screen and system operations
through natural-language **voice and CLI** commands (README, first paragraph).

- Primary runtime: Python (`src/grandpa`, console script `grandpa`).
- Local inference through **Ollama**. "Odin" is the internal codename of the
  local model family. It is not a separate product.
- Every desktop action passes through Grandpa's permission, confirmation and
  audit layers (the action layer).

## Engineering principles (from `docs/development/roadmap.md`)

1. Local inference and local data by default.
2. Typed actions instead of arbitrary shell execution.
3. Explicit confirmation for destructive or sensitive actions.
4. Short, testable adapters around Windows APIs.
5. No dependency on a bundled graphical client.
6. Graceful behaviour when optional speech, OCR or server dependencies are absent.
7. Regression tests for stale PIDs, device changes, protected paths and
   unavailable applications.

## Product priorities (README "Focused Roadmap", same order)

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

When two requests compete, prefer the one higher on this list unless Captain
says otherwise.

## Target machine (design for it, measure on it)

The code repeatedly cites the owner's laptop: **Ryzen 5 7520U, integrated GPU,
16 GB RAM shared with Ollama** (`ui/avatar_budget.py`). Assume no discrete GPU,
no admin rights (`scripts/install.ps1` needs none), Windows 11, and that Smart App
Control may block unsigned executables (the reason `grandpa.cmd` exists instead
of `grandpa.exe`).

## Languages

The owner uses English, Tamil and Tanglish. `core_ai_brain.detect_language`
returns `en`, `ta` or `ta-en`. A Tamil TTS backend (`mms_tamil`) exists. Treat
mixed-language input as a normal case, not an edge case.

## Scope notes and drift

- The README says there is "no bundled web dashboard, desktop shell, browser
  extension, mobile client, or third-party plugin runtime". Since then, plugins
  (G2), phone pairing (`devices/`) and an avatar window have landed. The
  sentence is stale; the intent behind it (no heavy bundled client, no cloud
  dependency) still holds.
- Cloud features exist only as explicit opt-ins (ElevenLabs TTS, Gmail and
  Calendar OAuth, web search). Never make a cloud path the default.
- The fork's upstream attribution (Apache-2.0) must stay intact
  (`NOTICE`, `docs/architecture/ARCHITECTURE_DECISIONS.md` AD-019).

## Phases (current vs future)

| Phase | Areas | Skills |
|---|---|---|
| Now: build and harden the Windows assistant | voice, intent, actions, screen, memory, models, UI, workflows, API, security, tests | the 19 current `grandpa-*` skills |
| Next: home server and phone | Pironman headless node and phone pairing exist; grow them carefully | `grandpa-api-server`, `grandpa-security-governance` |
| Future: smart home, IoT, hardware, robotics | no code yet (`capability-status.md`) | create `grandpa-smart-home-iot` and `grandpa-hardware-robotics` only when that work starts |
