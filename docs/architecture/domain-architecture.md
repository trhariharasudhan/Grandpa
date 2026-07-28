# Domain Boundaries

The public Python package is `src/grandpa`. Its major runtime domains are:

- `cli`: console entrypoints, chat, diagnostics, and lifecycle commands.
- `voice` and `speech`: microphone capture, wake phrase, STT, and TTS.
- `engine`: local Ollama discovery and generation.
- `router`, `jarvis`, and `operators`: deterministic intent routing.
- `automation`, `desktop`, and `apps`: permission-aware Windows control.
- `screen`, `vision`, and `browser_awareness`: visible-state capture and OCR.
- `files`, `downloads`, and `projects`: bounded local filesystem operations.
- `safety` and `security`: policy, confirmation, redaction, and audit.
- `memory`, `sessions`, and `reminders`: local context and scheduled work.
- `gmail` and `calendar`: optional personal OAuth integrations.
- `server`: trusted loopback API used by local clients.
- `skills` and `workflow`: trusted local reusable procedures.
- `telemetry` and `traces`: local diagnostics only.

## Dependency Direction

Interfaces call routers; routers create typed requests; safety evaluates those
requests; executors call narrow Windows or integration adapters. Executors must
not call back into chat or infer permission from model text.

## Compatibility Surfaces

Several broad modules remain because they are established public/runtime
surfaces, including `local_actions.py`, `pc_control.py`, `sdk.py`, and
`_rust_bridge.py`. They should be decomposed only through focused,
behavior-preserving changes with regression tests.

The optional Rust workspace is audited separately. Python fallbacks remain the
default where native bindings are unavailable.
