# Grandpa — Canonical Module Ownership

**Status:** Proposed. Nothing has been moved, renamed, merged, or deleted.
**Date:** 2026-08-26

This document answers one question per concern: **which module owns it?**
Everything else that implements the same concern is listed as a duplicate with a
disposition.

Tag legend is in `CURRENT_ARCHITECTURE.md`. Dispositions:

| Disposition | Meaning |
|---|---|
| **CANONICAL** | The single owner. All consumers should route here. |
| **ABSORB** | Its useful behaviour moves into the canonical owner; the module then goes. |
| **SHIM** | Becomes a thin deprecated re-export with a stated removal release. |
| **ARCHIVE** | Moves out of the main tree with history preserved. Not deleted. |
| **DELETE** | Removed outright. Reserved for code with zero consumers and no value. |
| **KEEP** | Correct as-is. Listed so it is not disturbed. |

---

## 0. Ownership at a glance

| Concern | CANONICAL owner | Duplicates to retire | Risk |
|---|---|---|---|
| Request dispatch | `dispatch/` **(new)** | 6 hand-written chains | H |
| Action policy + approval | `policy/` **(new)** | `local_actions.classify_permission`, `desktop/kernel/risk.py` | H |
| Intent parsing | `intent/` **(new home)** | `router/`, `jarvis/intent_router.py`, `local_actions` parser half | M |
| Model runtime | `runtime/` | `engine/` | M |
| Memory | `memory/` + `MemoryFacade` **(new)** | `memory_context.py`, dual-owner `memory.db` | **H** |
| Agent framework | `agents/` | `agent/` (executor/context/result) | H |
| Planning | `planner/` | `agent/execution/`, `workflow/` overlap, `advanced_ai.PlanStep`, `kernel/models` | M |
| Tools | `tools/` | `kernel/interfaces.py` | L |
| Desktop actuation | `desktop/` | `local_actions` executor half, `desktop_automation.py`, `windows_window_control.py`, `desktop_context.py` | **H** |
| Input automation | `automation/` | `smart_automation.py` | H |
| App discovery | `apps/` | `windows_app_resolver.py` | M |
| Screen capture / OCR / redaction | `screen/` | `screen_awareness.py`, `vision/ocr.py` | M |
| UI element graph | `vision/` | — | L |
| Browser | `browser/` | `browser_control.py`, `browser_intelligence/`, `browser_awareness/` | M |
| Voice | `voice/` + `VoiceSession` **(new)** | 4 of 5 routing paths, `jarvis/` | **H** |
| Speech backends | `speech/` | — | L |
| Cloned-voice runtime | `voice_service/` + `voice_runtime/` | — | **KEEP** |
| Files | `files/` | `file_assistant.py` overlap | M |
| Scheduling | `scheduler/` | `task_scheduler.py`, `scheduler_daemon.py` | M |
| Skills | `skills/` | `skill_builder/` overlap | L |
| Knowledge / RAG | `knowledge/` | `connectors/` overlap | M |
| Sessions | `sessions/` | `server/session_store.py` | L |
| HTTP API | `server/routers/*` **(split)** | monolithic `api_routes.py` | M |
| CLI | `cli/` | — | M |
| Config | `core/config.py` | `voice/config.py`, `screen/config.py` | L |
| Registries | `core/registry.py` | `kernel/interfaces.py` | L |
| Domain types | `core/types.py` | `kernel/models.py`, `planner/models.py` overlap | M |
| Events / telemetry / traces | `core/events.py` + `telemetry/` + `traces/` | the parallel Windows audit path | L |
| Security | `security/` | — (5 modules to wire or delete) | M |
| SDK | `sdk.py` + `system/` | — | L |
| MCP | `mcp/` | — | L |
| Native acceleration | *(none — archived)* | `rust/`, `_rust_bridge.py` | L |
| Agent protocols | *(none — archived)* | `a2a/` | L |
| Kernel contracts | `core/` | `kernel/` | M |

---

## 1. Dispatch and routing

### 1.1 Request dispatch — CANONICAL: `grandpa/dispatch/` *(new)*

| | |
|---|---|
| **Current implementations** | `cli/chat_cmd.py` (28 handlers) · `cli/ask.py` (5) · `server/routes.py` (9) · `server/api_routes.py` (3) · `voice/assistant.py` (15) · `voice/operator.py` (11) |
| **Consumers** | Every entry surface |
| **Dependencies** | Will depend on `policy/`, `memory/`, `core.events`, and the handler modules |
| **Disposition** | Each of the six chains becomes ~10 lines calling `IntentDispatcher.dispatch()` |
| **Migration risk** | **H** — `chat_cmd.py` alone has 43 test files behind it, and 3 of the 6 surfaces (both voice modes, and the desktop handlers in `chat`) are untestable in current CI |
| **Gate** | Windows CI (AD-016) for the voice and desktop surfaces. The `ask` and HTTP surfaces can migrate earlier. |

### 1.2 Intent parsing — CANONICAL: `grandpa/intent/` *(new home)*

| | |
|---|---|
| **Duplicates** | `router/intent_router.py` (154) · `router/legacy_adapter.py` (110) · `router/skill_router.py` (163) · `router/route_models.py` (74) · `jarvis/intent_router.py` (191) · `jarvis/context_resolver.py` (135) · the allowlist-parser half of `local_actions.py` · `core_ai_brain.py` (448) · `planner/routing.py` |
| **Consumers** | `router/` ← `local_actions.py:357`, `services/planner_service.py:55,61`. `jarvis/` ← `cli/jarvis_cmd.py`, `cli/voice_cmd.py`, `voice/diagnostics.py`, `voice/operator.py:1441` |
| **Problems** | Two intent routers plus a "legacy adapter" for a system that is itself not canonical. `local_actions` ↔ `router` is a **cycle** (1/3). `local_actions` ↔ `actions` is another (1/5). |
| **Disposition** | `router/` and `jarvis/intent_router.py` **ABSORB** into `intent/`. `jarvis/context_resolver.py` **ABSORB**. `jarvis/voice_input.py` **ABSORB** into `voice/`. `core_ai_brain.py` — **[OPEN QUESTION]** its role relative to `intent/` is unclear from the code; assess before moving. |
| **Migration risk** | **M** |

---

## 2. Policy and security

### 2.1 Action policy — CANONICAL: `grandpa/policy/` *(new)*

| | |
|---|---|
| **Current implementations** | **NL path:** `local_actions.py` — `_is_dangerous()` (37 regex), allowlist parsers, `classify_permission()` → `{allowed, requires_confirmation, blocked}`, `LocalActionApprovalStore` → `local_action_approvals.db`. **API path:** `pc_control.py` + `desktop/kernel/risk.py` → `{LOW, MEDIUM, HIGH, BLOCKED}` + `APPROVAL_REQUIRED_ACTIONS` (post-remediation) → `pc_control_approvals.db`. |
| **Consumers** | `local_actions` ← 7 packages; `pc_control` ← 10 packages |
| **Problems** | Two vocabularies, two approval stores, no shared code. A rule added to one is absent from the other. |
| **Disposition** | Both **ABSORB** into `policy/`. Adopt `{LOW, MEDIUM, HIGH, BLOCKED}` plus an orthogonal `requires_approval` predicate — the post-remediation design on `claude/grandpa-codebase-audit-bf609c` already models this correctly. One approval store, out-of-band confirmation code required. |
| **Migration risk** | **H** — highest-consequence area of the product |
| **Gate** | Windows CI (AD-016) |

### 2.2 Security modules — CANONICAL: `security/`

| Module | LOC | External consumers | Disposition |
|---|---:|---:|---|
| `file_policy.py` | 67 | 6 | **KEEP** |
| `ssrf.py` | 138 | 3 | **KEEP** — remove the Rust-first branch |
| `capabilities.py` | 197 | 3 | **KEEP, FIX** — `_check_python` must fail **closed** |
| `scanner.py` | 224 | 1 | **KEEP** — remove the Rust-first branch |
| `taint.py` | 137 | — | **KEEP** |
| `audit.py` | 266 | 2 | **KEEP** — becomes an event-bus subscriber (AD-015) |
| `boundary.py` | 139 | 2 | **KEEP** — resolve the `SecurityBlockError` duplicate |
| `guardrails.py` | 317 | 0 external | **KEEP** — wired via `setup_security()`; resolve the `SecurityBlockError` duplicate |
| `signing.py` | 132 | 1 | **KEEP** — used by `skills/security.py` |
| `credential_stripper.py` | 31 | — | **KEEP, EXTEND** — apply to uvicorn/FastAPI loggers too |
| `types.py`, `file_utils.py`, `_stubs.py` | 175 | — | **KEEP** |
| `injection_scanner.py` | 167 | 1 (a JSON converter) | **WIRE** — into `policy/` ingress; it has never run on anything |
| `rate_limiter.py` | 113 | **0** | **WIRE** — into `policy/`; `rate_limit_enabled = True` already ships |
| `subprocess_sandbox.py` | 143 | **0** | **DELETE** — zero consumers, uses `shell=True` in a module named "sandbox" |
| `severity_policy.py` | 22 | **0** | **DELETE** |
| `merkle` (audit variant) | — | **0** | **DELETE or WIRE** — `merkle_audit` is one of the 9 inert config keys |

---

## 3. Model runtime and intelligence

### 3.1 Model runtime — CANONICAL: `runtime/`

| | |
|---|---|
| **Owns** | `ModelRuntime` ABC, `BackendAdapter`, `OllamaBackendAdapter`, `NativeAdapter`, `RuntimeManager`, exceptions, utils — 8 files, 1,364 LOC |
| **Duplicates** | `engine/` (342 LOC): `_stubs.InferenceEngine`, `_discovery.py`, `ollama.py` (23 LOC), `_base.py`, `_network.py::local_port_is_open` (**byte-identical** to `runtime/utils.py::local_port_is_open`) |
| **Consumers** | `engine/` ← 11 packages / 44 edges (cli ×19, agents ×6, core, …). `runtime/` ← 7, almost all from `engine/` |
| **Disposition** | `engine/_stubs.InferenceEngine` and `engine/_discovery.py` **ABSORB** into `runtime/`. `engine/_network.py` **DELETE**. `engine/ollama.py`, `engine/_base.py` **ABSORB**. `grandpa.engine` becomes a **SHIM** with exception aliases for one release. |
| **Migration risk** | **M** — 44 mechanical import-site edits, test-covered |
| **Blocker** | `src/grandpa/runtime/` must be tracked in git first (AD-018) |
| **KEEP unchanged** | `runtime/ollama_adapter.py`, including `_visible_stream_delta` reasoning-tag stripping |

### 3.2 Intelligence / model catalogue — CANONICAL: `intelligence/`

| | |
|---|---|
| **Owns** | `grandpa_models.py` (canonical Odin model roles + legacy compat), model catalogue |
| **Duplicates** | `models/` package (manager, security, source) overlaps; `cli/model.py` vs `cli/models_cmd.py` are two similarly-named commands |
| **Consumers** | `cli` (14 edges) |
| **Disposition** | **KEEP**. Rationalise `grandpa model` / `grandpa models` into one command. Reconcile `intelligence.default_model = "grandpa-mini:latest"` with README's `ollama pull qwen2.5:3b`. |
| **Migration risk** | **L** |

### 3.3 Learning / routing — CANONICAL: `learning/routing/`

| | |
|---|---|
| **Owns** | `complexity.py`, `learned_router.py`, `router.py`, `heuristic_policy.py`, `heuristic_reward.py` — 905 LOC total for `learning/` |
| **Note** | **[FACT]** The Rust `grandpa-learning` crate is 6,281 LOC — 7× the Python side. It implements a subsystem Python abandoned. This is direct evidence for AD-002. |
| **Disposition** | **KEEP** the Python side. The Rust crate goes with the archive. |

---

## 4. Memory and knowledge

### 4.1 Memory — CANONICAL: `memory/` + `MemoryFacade` *(new)*

| Store | Owner | File | Current owner |
|---|---|---|---|
| Facts / activity / conversation | `memory/` facts store | `personal_memory.db` | `memory_context.py` |
| Structured items | `memory/store.py` | `memory.db` | `memory/store.py` (table `memories`) |
| RAG documents | `tools/storage/sqlite.py` | **`documents.db`** *(moved)* | `tools/storage/sqlite.py` (table `documents`, **same file**) |
| Sessions / project | `sessions/`, `memory/project_memory.py` | `sessions.db`, `projects.json` | same |
| Memory file | `MemoryFilesConfig` | `~/.grandpa/MEMORY.md` | same |

| | |
|---|---|
| **Duplicates** | `memory_context.py` (1,302 LOC, **45 importers**, second `MemoryStore`) |
| **Consumers** | `memory_context` ← `cli/`, `server/` (15 edges), `skills/`, `voice/`, `sdk.py`, 45 total |
| **Dependencies** | `memory_context` ↔ `memory` is a **cycle** (10/1) |
| **Disposition** | `memory_context.py` **ABSORB** into `memory/`, then **SHIM** for one release given 45 importers |
| **Migration risk** | **H — the highest in the repository.** Live user data; a schema collision on a file the user already has. |
| **Gate** | **Explicit approval required** (AD-010). Backup-first, idempotent, dry-runnable, revertible. |
| **Blocked on** | Q-5 — the 7 orphaned databases |

### 4.2 Knowledge / RAG — CANONICAL: `knowledge/`

| | |
|---|---|
| **Duplicates** | `connectors/` (2,332 LOC — store, retriever, embeddings) defines a second `KnowledgeStore` and a second `OllamaEmbedder` (the other in `tools/storage/embeddings.py`) |
| **Consumers** | `knowledge` ← 6 packages incl. `server` (10 edges), `skills` (9). `connectors` ← 4 |
| **Disposition** | **[OPEN QUESTION]** `knowledge/` (1,495 LOC) and `connectors/` (2,332 LOC) have overlapping but not identical roles. Assess before assigning — this is the one ownership call I cannot make from the evidence gathered. Resolve the duplicate `KnowledgeStore` and `OllamaEmbedder` regardless. |
| **Migration risk** | **M** |

---

## 5. Agents, planning, tools

### 5.1 Agent framework — CANONICAL: `agents/`

| | |
|---|---|
| **Owns** | Registry, manager, executor, context, orchestrator, simple / react / rlm / operative / monitor agents, goal_mode, loop_guard, prompt_registry, `_stubs.BaseAgent` — 6,758 LOC |
| **Duplicates** | `agent/` (5,846 LOC): colliding `AgentExecutor` (`agent/executor.py:18` vs `agents/executor.py:27`), `AgentContext`, `AgentResult`, `AgentGoal`, `AgentRuntime` (`agent/runtime.py:43` vs `system/bundles.py:42`) |
| **Consumers** | `agents/` ← `server` (15), `system` (12), `cli` (11), `sdk`. `agent/` ← `cli` (24) — the `grandpa agent`/`sprint`/`roadmap` group |
| **Disposition** | `agents/` **CANONICAL**. `agent/executor.py`, `agent/context.py`, `agent/models.py`, `agent/runtime.py` **ABSORB**. `agent/execution/` **ABSORB into `planner/`**. `agent/development/` — **[OPEN QUESTION] Q-4**, see below. |
| **Migration risk** | **H** — `agent/` backs 6 shipped CLI commands |

### 5.2 `agent/development/` — disposition deferred

| | |
|---|---|
| **Contents** | checkpoint, engine, models, planner, registry, roadmap_generator, sprint, tracker — ~2,000 LOC |
| **Consumers** | 6 CLI commands (`agent`, `sprint`, `roadmap`, `project`, `plan`, `scan`); `agent.development.roadmap_generator` has 10 import edges |
| **Docs** | `autonomous-development-workflow-v1.md`, `project-engineer-mode-v1.md`, `self-planning-engine-v1.md` |
| **Problem** | An autonomous software-development feature. **Not on the README roadmap.** Not a Windows-assistant capability. |
| **Disposition** | **[OPEN QUESTION] Q-4** — product feature, personal tool, or inherited scope? Does not block Phases 0–3. |

### 5.3 Planning — CANONICAL: `planner/`

| | |
|---|---|
| **Owns** | executive, decomposer, engine, executor, validator, verifier, recovery, routing, scheduler, state_store, action_catalog, formatter, models — 4,178 LOC |
| **Duplicates** | `agent/execution/` (analyzer, approval, recovery, verifier, models, patch_*, test_runner, workspace) · `workflow/` (builder, engine, graph, loader, types — 788 LOC) · `kernel/models.py` (`ExecutionPlan`, `RiskLevel`, `ConfirmationRequest`, `VerificationResult`) · `advanced_ai.PlanStep` · `smart_automation.WorkflowResult` |
| **Duplicate types** | `ExecutionPlan` ×2 · `PlanStep` ×2 · `StepStatus` ×2 · `StepVerifier` ×2 · `ValidationResult` ×2 · `RiskLevel` ×2 · `ConfirmationRequest` ×2 · `VerificationResult` ×2 · `WorkflowResult` ×3 |
| **Consumers** | `planner` ← 9 packages incl. `agents`, `services/planner_service.py`, `voice` |
| **Disposition** | `planner/` **CANONICAL**. `agent/execution/` **ABSORB**. `workflow/` **KEEP only if** graph execution is a distinct role the planner does not cover; otherwise **ABSORB**. `advanced_ai.PlanStep`, `smart_automation.WorkflowResult` **DELETE**. |
| **Migration risk** | **M** |

### 5.4 Tools — CANONICAL: `tools/`

| | |
|---|---|
| **Owns** | `_stubs.BaseTool` + `ToolExecutor` (**53 importers**), 32 modules / ~47 tools, `tools/storage/` |
| **Duplicates** | `ToolResult` (`core/types.py:164` vs `kernel/models.py:182`) · `ToolRegistry` (`core/registry.py:189` vs `kernel/interfaces.py:78`) · `ToolExecutor` (`tools/_stubs.py:88` vs `kernel/interfaces.py:82`) · `skills/tool_adapter.py` as a third adaptation path |
| **Consumers** | 14 packages; `mcp/` → `tools/` (11 edges) is the plugin ingress |
| **Disposition** | **KEEP**. `kernel/interfaces.py` duplicates go with the `kernel/` archive. **Remove the Rust-first path in `tools/shell_exec.py:126-140`** — it discards the sanitised env and timeout and hardcodes `returncode: 0, success: True`. |
| **Migration risk** | **L** |

---

## 6. Windows actuation

### 6.1 Desktop actuation — CANONICAL: `desktop/`

| | |
|---|---|
| **Owns** | `control/` — applications, windows, files, power, clipboard, monitors, automation, registry, diagnostics. `kernel/` — approvals, audits, emergency, execution, requests, risk. Plus `operator.py`, `applications.py`, `folders.py`, `power.py`, `volume.py`, `automation.py` |
| **Duplicates** | `local_actions.py` executor half (2,203 LOC) · `pc_control.py` (1,438) · `windows_window_control.py` (1,362) · `desktop_automation.py` (384) · `desktop_context.py` (494) · `smart_automation.py` (613) |
| **Duplicate types** | `AutomationResult` (`desktop_automation.py:79` vs `automation/models.py:69`) · `WindowInfo` (`windows_window_control.py:163` vs `screen/models.py:29`) · `MonitorInfo` (`desktop_context.py:38` vs `screen/models.py:11`) |
| **Consumers** | `desktop` ← 9 · `pc_control` ← 10 · `local_actions` ← 7 · `windows_window_control` ← 7 |
| **Dependencies** | **`pc_control` ↔ `desktop` cycle, 27/16 — the heaviest in the tree.** `automation` → `windows_window_control` (13 edges) bypasses `desktop/control/windows.py`. |
| **Disposition** | `desktop/control/*` **KEEP** — the typed service layer is correct; only its callers change. `desktop/kernel/` **KEEP**, rename → `desktop/execution/`. `local_actions.py` splits: parser → `intent/`, policy → `policy/`, executor → `desktop/`. `pc_control.py` becomes a thin surface over `policy/` + `desktop/`. `windows_window_control.py` **ABSORB** into `desktop/control/windows.py`. `desktop_automation.py`, `desktop_context.py`, `smart_automation.py` **ABSORB**. |
| **Migration risk** | **H** — the product's core, Windows-only, never exercised in CI |
| **Gate** | **Hard gate on Windows CI (AD-016).** |

### 6.2 Input automation — CANONICAL: `automation/`

| | |
|---|---|
| **Owns** | keyboard, mouse, locator, pipeline, confirmation, executor, planner, service, windows, models — 2,859 LOC |
| **Duplicates** | `smart_automation.py` (613); `desktop/control/automation.py` overlaps |
| **Consumers** | ← 5 packages incl. `voice` (10 edges) |
| **Disposition** | **KEEP**. **Preserve `automation/locator.py`'s redaction call** — it is one of only three places redaction is applied today. |
| **Migration risk** | **H** — synthetic input is the highest-consequence capability |

### 6.3 App discovery — CANONICAL: `apps/`

| | |
|---|---|
| **Owns** | inventory, launcher, process_manager, registry, resolver, safety, scanner, automation, models |
| **Duplicates** | `windows_app_resolver.py` (675 LOC, 4 importers) vs `apps/resolver.py` |
| **Disposition** | `windows_app_resolver.py` **ABSORB** into `apps/resolver.py`, then **SHIM** |
| **Migration risk** | **M** |

### 6.4 Screen — CANONICAL: `screen/`

| | |
|---|---|
| **Owns** | capture, ocr, analyzer, **redaction**, models, windows, intents, config, errors, service — 1,541 LOC |
| **Duplicates** | `screen_awareness.py` (664 LOC, **7 importers**, second `OcrResult`) · `desktop_context.py` (second `MonitorInfo`) · `vision/ocr.py` |
| **Consumers** | ← 6 packages incl. `vision` (11 edges), `automation` (6) |
| **Disposition** | **KEEP — the cleanest subsystem in the repository.** `screen_awareness.py` **ABSORB** then **SHIM**. `vision/ocr.py` defers to `screen/ocr.py`. |
| **Migration risk** | **L–M** |
| **KEEP unchanged** | `screen/redaction.py` — 7 pattern classes, applied on the paths that have it. **Never bypass.** |

### 6.5 Vision — CANONICAL: `vision/`

| | |
|---|---|
| **Owns** | UIA, graph, matcher, extractor, analyzer, actions, session, local_model, service, models, ocr — 1,614 LOC |
| **Consumers** | ← 6 packages |
| **Disposition** | **KEEP**. Owns the semantic UI-element graph on top of `screen/`. Redaction is already applied (`vision/graph.py:63`) — preserve. |
| **Migration risk** | **L** |

### 6.6 Browser — CANONICAL: `browser/` *(consolidated)*

| Current package | LOC | Importers | Disposition |
|---|---:|---:|---|
| `browser/` | 1,113 | 6 | **CANONICAL** → becomes `browser/control` |
| `browser_intelligence/` | 2,247 | 4 | **ABSORB** → `browser/read` |
| `browser_awareness/` | 498 | 2 | **ABSORB** → `browser/awareness` |
| `browser_control.py` | 1,264 | **10** | **ABSORB** then **SHIM** |

| | |
|---|---|
| **Duplicated module names across packages** | `safety.py` (browser/, browser_awareness/) · `parser.py` (both) · `automation.py` (both) |
| **Problem** | **No redaction on any browser path** — `redact_screen_text` is applied in `screen/`, `vision/`, `automation/locator.py`, but in none of these four. Browser page text is the largest volume of untrusted content the assistant ingests. |
| **Disposition — priority order** | **1. Apply redaction at every extraction boundary. This is a security fix and should land first, independently.** 2. Consolidate. |
| **Migration risk** | **M** |

---

## 7. Voice

### 7.1 Voice — CANONICAL: `voice/` + `VoiceSession` *(new)*

| Current routing path | Handlers | Disposition |
|---|---:|---|
| `voice/assistant.py` | 15 | **CANONICAL basis** — the most complete |
| `voice/operator.py` (1,613 LOC) | 11 | **ABSORB** — becomes an operator *mode* |
| `voice/session.py` | — | **ABSORB** |
| `voice/cli_session.py` | — | **ABSORB** |
| `voice/loop.py` | — | **ABSORB** — becomes a continuous *mode* |
| `jarvis/voice_input.py` (367 LOC) | — | **ABSORB** |

| | |
|---|---|
| **Consumers** | `voice` ← 5 packages; **`cli` ↔ `voice` cycle (18/7)** |
| **Problems** | A fix in one path does not reach the other four. No `VoiceConfig` in `GrandpaConfig` despite a live `[voice]` section in `~/.grandpa/config.toml`. 74 `GRANDPA_VOICE_*` env vars. 9 of 13 test failures and **both** suite hangs live here. |
| **Migration risk** | **H** — hardware-dependent, never exercised in CI |
| **Gate** | **Hard gate on Windows CI (AD-016).** |

### 7.2 Speech backends — CANONICAL: `speech/`

**KEEP.** faster-whisper STT; pyttsx3 / Kokoro / grandpa_voice TTS.

### 7.3 Cloned-voice runtime — CANONICAL: `voice_service/` + `voice_runtime/`

| | |
|---|---|
| **Disposition** | **KEEP — do not change the boundary.** |
| **Why** | The out-of-process F5 runtime (separate venv, HTTP on `:8765`) keeps `torch` out of the main environment. This is one of the best decisions in the codebase and is the pattern for any future heavy dependency. |
| **Note** | `voice_service/` has zero in-degree in the import graph *by design* — it is invoked over HTTP, not imported. |
| **Separate issue** | `voice_runtime/` vendors 207.6 MB of LGPL ffmpeg (91.6% of the git pack) plus the original 62 MB zip. A repository-hygiene problem, not an architecture one. |

---

## 8. Platform substrate

### 8.1 Core — CANONICAL: `core/`

| Module | LOC | Fan-in | Disposition |
|---|---:|---:|---|
| `config.py` | 1,302 | 112 | **KEEP — extend only.** Per `AUDIT.md` the best-engineered module in the repo. Add Desktop/Screen/Automation/Voice/Vision sections; remove `A2AConfig`. **Never restructure** the precedence model, the generic validator, or the back-compat shims. |
| `registry.py` | 235 | 95 | **KEEP.** 12 typed registries. |
| `types.py` | 325 | 78 | **KEEP — extend.** Resolve the `ToolResult` duplicate against `kernel/models.py`. |
| `events.py` | 198 | 47 | **KEEP — extend** with desktop/screen/voice/policy `EventType` members (AD-015). |
| `credentials.py`, `runtime_context.py` | 310 | — | **KEEP** |

**Rule D1:** `core/` must import nothing from `grandpa.*`. Today there are four
single back-edges to break: `core → security`, `core → engine`, `core → tools`,
`core → agents`.

### 8.2 Observability — CANONICAL: `core/events.py` + `telemetry/` + `traces/`

| | |
|---|---|
| **Duplicates** | The parallel Windows audit path: `pc_control` audit (sqlite + jsonl), `local_action_approvals.db`, `security/audit.py`, `desktop/kernel/audits.py` |
| **Problem** | `local_actions.py` and `pc_control.py` publish **zero** events; `EventType` has no desktop member |
| **Disposition** | **KEEP** the platform plane. Windows layer starts publishing. Audit becomes a **subscriber**. |
| **Migration risk** | **L** — additive |
| **KEEP unchanged** | Zero network egress. Verified today; verify again after. |

### 8.3 SDK / system — CANONICAL: `sdk.py` + `system/`

| | |
|---|---|
| **Owns** | `Grandpa`, `GrandpaSystem`, `MemoryHandle`, `SystemBuilder` — the only public exports of `grandpa/__init__.py` |
| **Duplicates** | `AgentRuntime` (`system/bundles.py:42` vs `agent/runtime.py:43`) · `SecurityContext` (`system/bundles.py:24` vs `security/__init__.py:33`) |
| **Disposition** | **KEEP** as a secondary surface (AD-003). Correct `pyproject.toml` and `__init__.py` to describe the assistant first. Needs a doc page. |
| **Blocked on** | Q-1 |

### 8.4 MCP — CANONICAL: `mcp/`

| | |
|---|---|
| **Owns** | client, server, protocol, transport (stdio / SSE / StreamableHTTP), bridge — 885 LOC |
| **Consumers** | `tools/` (11 edges, bidirectional); wired at `system/builder.py:314,339-465` |
| **Disposition** | Client **KEEP**. Server **gate behind explicit opt-in** (AD-004) pending Q-2. Needs a doc page. |

### 8.5 Server — CANONICAL: `server/routers/*` *(split)*

| | |
|---|---|
| **Current** | `routes.py` (60 endpoints, 1,343 LOC) · `api_routes.py` (114 endpoints across 26 named sub-routers, 2,256 LOC) · `approval_routes.py` (3) · `upload_router.py` (2) — **179 total** |
| **Duplicates** | `SessionStore` (`server/session_store.py:16` vs `sessions/session.py:65`) · two approval endpoints for the same action |
| **Dependencies** | Widest fan-out in the tree: `services` (16), `agents` (15), `memory_context` (15), `core` (14), `voice` (13), `knowledge` (10), `pc_control` (9) |
| **Disposition** | Split `api_routes.py` into `server/routers/<name>.py`, one per existing sub-router — the 26 sub-routers already define the seams. Typed Pydantic models on every action endpoint (`POST /api/local-action` currently takes a bare `dict[str, Any]`). One approval endpoint. |
| **Migration risk** | **M** |
| **KEEP unchanged** | Middleware order (auth outermost — correct); `check_bind_safety()`; the post-remediation default-on auth. |

### 8.6 CLI — CANONICAL: `cli/`

| | |
|---|---|
| **Owns** | 63 modules, 18,722 LOC, 51 lazily-imported commands |
| **Disposition** | **KEEP** the lazy loader and `safe_output.py` / `theme.py` / `hints.py`. Split `chat_cmd.py` (2,156 LOC) into `chat/dispatch.py` + `chat/slash.py` + `chat/render.py` **after** `IntentDispatcher` exists. Merge `grandpa model` / `grandpa models`. |
| **Migration risk** | **M** — `chat_cmd.py` has 43 test files behind it |

### 8.7 Services façade — CANONICAL: `services/`

| | |
|---|---|
| **Owns** | base, registry, and 8 service wrappers (desktop, vision, browser, planner, skill, workflow, burnin, release) |
| **Consumers** | `server` (16 edges) |
| **Disposition** | **KEEP**. This is a genuine assistant-facing façade over platform primitives, and it is one of the few places the two layers meet cleanly. **[RECOMMENDATION]** Once `IntentDispatcher` exists, evaluate whether `services/` and the handler set are the same abstraction under two names. |

---

## 9. Archive list

| Component | LOC | `src/` consumers | Disposition | Depends on |
|---|---:|---:|---|---|
| `rust/` (17 crates) | 27,035 | 0 at runtime | **ARCHIVE** | AD-002, Q-3, Q-7 |
| `kernel/` | 3,272 | 1 | **ARCHIVE** after folding `files/kernel_adapter.py` | AD-012 |
| `a2a/` + `A2AConfig` | 460 | **0** | **ARCHIVE** | AD-001, AD-012 |
| `_rust_bridge.py` | 180 | 16 | **SHIM** one release → **DELETE** | AD-002 |
| `templates/` | 115 | **0** | **ARCHIVE** | — |
| `daemon/` | 34 | **0** | **ARCHIVE** | — |
| `security/subprocess_sandbox.py` | 143 | **0** | **DELETE** | AD-013 |
| `security/severity_policy.py` | 22 | **0** | **DELETE** | AD-013 |
| `.dockerignore` | — | — | **DELETE** (no Dockerfile exists) | — |

**Total: ~31,300 LOC** leaving the main tree, ~31,000 of it recoverable from an
archive branch.

---

## 10. Ownership rules going forward

**[RECOMMENDATION]** Adopt these as review criteria so the ownership map does
not regress.

1. **One owner per concern.** A new module that implements something an existing
   module already owns is rejected. Extend the owner instead.
2. **No new flat top-level modules under `src/grandpa/`.** Every new module goes
   in a package. This rule alone would have prevented `local_actions.py`,
   `pc_control.py`, `windows_window_control.py`, `memory_context.py`,
   `browser_control.py`, and `screen_awareness.py`.
3. **No duplicate domain type names.** A class name defined twice is a review
   blocker. There are 31 today.
4. **No new SQLite database files** without an entry in the memory ownership
   table. There are 29 filenames today, 7 of them orphaned.
5. **Deprecation is time-boxed.** A **SHIM** carries a stated removal release. A
   shim with no removal date becomes a second live implementation, which is how
   most of the duplicates above came to exist.
6. **Import direction is CI-enforced** (rules D1–D8 in `TARGET_ARCHITECTURE.md`
   §6). A rule that is not enforced regresses.
