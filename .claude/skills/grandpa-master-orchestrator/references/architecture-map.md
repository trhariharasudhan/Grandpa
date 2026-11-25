# GRANDPA architecture map (as built)

Verified against `main` @ `fde2164` (2026-11-24). Numbers come from commands run
on that tree; re-measure before quoting them as current.

## Scale

| Measure | Value |
|---|---|
| Python source | 688 files, ~167k lines under `src/grandpa/` |
| Tests | 527 `test_*.py` files, ~123k lines under `tests/` |
| Rust workspace | 17 crates, 124 files, ~27k lines under `rust/` (inherited, optional) |
| CLI commands | 60 registered in `src/grandpa/cli/__init__.py` (lazy-loaded) |
| HTTP route decorators | ~188 across `src/grandpa/server/` |
| Catalogued actions | 174 in `src/grandpa/action_layer/catalogue.py` |
| `except Exception` sites | ~1,005 |

## Origin (why the tree looks the way it does)

The repo started as an inherited "composable intelligence platform" (OpenJarvis,
itself derived from IPW) and was rebranded to Grandpa on 2026-05-23. The
platform packages (`core/`, `agents/`, `tools/`, `engine/`, `security/`,
`telemetry/`, `traces/`, `skills/`, `workflow/`, `mcp/`, `rust/`) are the
substrate; the Windows assistant was built afterwards, partly as flat modules at
`src/grandpa/*.py` (`pc_control.py`, `memory_context.py`, `browser_control.py`,
`windows_window_control.py`, ...). Expect duplicate concepts. See
`docs/architecture/CURRENT_ARCHITECTURE.md` (dated 2026-08-26, partly stale).

## Layers

```
ENTRY SURFACES
  grandpa chat / ask (cli/chat_cmd.py, cli/ask.py)      grandpa voice / voice-operator / jarvis
  grandpa bubble / avatar (ui/)                          FastAPI server (server/), phone devices
        │
INTENT / ROUTING
  deterministic phrase handlers first: grandpa.local.handle_local_action (local/),
  cli/_*_route.py modules, router/, jarvis/, workflow phrase triggers
  then the model: action-layer tool loop (action_layer/loop.py, on by default in chat
  via [tools] chat_tool_loop) or agents/ + tools/ for agent mode
        │
POLICY + EXECUTION (the one door)
  action_layer/executor.execute(): lookup → validate → confirm → call → audit
  risk tiers mirrored from pc_control (LOW/MEDIUM/HIGH/BLOCKED); plugin__* and mcp__* actions
        │
ACTUATION (Windows)
  desktop/control/* services, automation/, apps/, files/, browser*/, screen/, vision/,
  notes/, downloads/, gmail/, calendar/, web_search/, reminders.py, task_scheduler.py
        │
MODEL RUNTIME
  engine/ (thin shim, many importers) → runtime/ (ModelRuntime, OllamaBackendAdapter,
  NativeAdapter) → Ollama :11434 ; Odin roles in intelligence/odin_registry.py
        │
STATE (all under GRANDPA_HOME, default ~/.grandpa)
  ~32 distinct SQLite filenames: personal_memory.db, memory.db, scheduler.db,
  reminders.db, knowledge.db, telemetry.db, devices.db, ...; action audit JSONL under runtime/
```

## Module map (major subsystems)

| Subsystem | Location | Status | Notes |
|---|---|---|---|
| CLI | `src/grandpa/cli/` (86 files) | Implemented | `chat_cmd.py` ~2.3k lines; commands lazy-loaded |
| Action layer | `src/grandpa/action_layer/` | Implemented, canonical | catalogue, executor, loop, tool_schema, model |
| Legacy policy | `src/grandpa/pc_control.py`, `desktop/kernel/` | Implemented, legacy | risk tables that the catalogue mirrors; approval store, emergency stop |
| Phrase router | `src/grandpa/local/` | Implemented | allowlisted phrases, never arbitrary shell |
| Desktop services | `src/grandpa/desktop/control/` | Implemented (Windows) | applications, windows, power, clipboard, monitors, automation, diagnostics |
| Screen / vision | `src/grandpa/screen/`, `vision/`, `screen_awareness.py` | Implemented, duplicated | privacy list, OCR (Tesseract), UIA, grandpa-eyes |
| Voice | `src/grandpa/voice/`, `speech/`, `voice_service/` | Implemented | push-to-talk, VAD, openWakeWord, TTS registry |
| UI | `src/grandpa/ui/` | Implemented | tk bubble, pywebview avatar (three.js vendored) |
| Models | `src/grandpa/runtime/`, `engine/`, `intelligence/`, `models/`, repo `models/Modelfile.*` | Implemented | Ollama only in practice |
| Memory | `memory_context.py`, `memory/`, `knowledge/`, `connectors/`, `tools/storage/` | Implemented, fragmented | two memory systems; `memory.db` has two writers |
| Agents / planning | `agents/`, `agent/`, `planner/`, `workflow/`, `kernel/` | Partial, duplicated | two agent frameworks, several planners |
| Workflows | `workflow/` (YAML via `load_yaml_workflow`, triggers) | Implemented | F1–F3 |
| Plugins | `plugins/` (host, manifest), repo `plugins/hello/` | Implemented | off until enabled, file fingerprints |
| MCP | `mcp/` (client, server, stdio servers) | Implemented | stdio servers deny-by-default, HIGH risk |
| Server | `server/` | Implemented | FastAPI, API key auth by default, headless mode |
| Devices | `devices/` | Implemented | LAN phone pairing, remote approvals at the PC |
| Security | `security/`, `security_safety.py` | Mixed | secret store, SSRF, guardrails; injection scanner reported orphaned |
| Rust | `rust/`, `_rust_bridge.py` | Optional / inherited | Python fallbacks everywhere since PR #59 |

## Known structural problems (for refactor work)

- Heavy import cycles, worst `pc_control` ↔ `desktop`; `cli` ↔ `voice`.
- Duplicate class names (35 at last count), e.g. two `MemoryStore`, two `SchedulerStore`,
  three `WorkflowResult`.
- Two unrelated packages named kernel: `kernel/` (near-dead) and `desktop/kernel/` (live).
- `engine/` is a shim over `runtime/` but has the larger fan-in.
- Plans for consolidation: `docs/architecture/MIGRATION_PLAN.md`, `TARGET_ARCHITECTURE.md`.
  Do not start a large refactor without the owner's go-ahead (CONTRIBUTING asks for an issue first).
