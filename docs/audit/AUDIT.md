# Grandpa Repository Audit

**Audit date:** 2026-08-25
**Commit audited:** `a031346a` (`main`, identical to `origin/main`)
**Auditor environment:** Windows 11, Python 3.11.14 (`D:\Grandpa\.venv`), uv 0.10.6, Ollama 0.32.15 (running, 14 models), cargo 1.96.0, Node 24.19.0
**Method:** static reading of the full tree, plus live execution — `grandpa doctor`, `grandpa ask`, `grandpa serve` + HTTP probes, full `pytest` run (31m48s), `ruff`, `cargo clippy`, GitHub Actions API, PyPI API.

---

## 0. Remediation Status

> This section is a running log appended after the audit. **The findings below
> are a point-in-time record as of 2026-08-25 and have deliberately not been
> rewritten** — consult this table for what has since changed.

**Fixed 2026-08-25 (all P0 items, plus P1-4):**

| ID | Item | Verification |
|---|---|---|
| P0-1 | `.gitignore` `runtime/` → `/runtime/`; `src/grandpa/runtime/` tracked | Clean-clone collection `56 errors` → `0`; `doctor` `ModuleNotFoundError` → `38 passed`; wheel now ships all 8 modules |
| P0-2 | 3 phantom test paths removed from `ci.yml` | CI selection: exit 4 → **exit 0, 229 passed** |
| P0-3 | Synthetic input re-tiered to require approval; command-surface hotkeys blocked | `keyboard_type` → `approval_required`; `win+r` → `blocked` at staging |
| P0-4 | API authenticated by default; key generated on first run | All `/v1` + `/api` routes `200` → **`401`** without a key; `200` with it; `/health` stays open |
| P0-5 | Out-of-band approval codes | Self-approval with a returned `action_id` → `invalid_approval_token`; code appears only on the operator console |
| P1-4 | Orphaned submodule gitlink removed | `git submodule status` no longer errors |

**Knowingly still open** (unchanged from the findings below): the 12 remaining
stale test failures (P1-3), the `Fatal Python error` daemon-thread crash at
interpreter shutdown (P1-2, exit 127 — the CI-selected subset is unaffected and
exits 0), the red `rust` clippy job (P1), the PyPI name collision and
`self-update` target (P1-1), and the inert security config keys (P1-6).

**Two side-findings surfaced while fixing the above:**

- `tests/cli/test_voice_cmd.py::test_voice_runtime_diagnostics_reports_active_interpreter`
  asserts `project_root.endswith("Grandpa")`, so the suite cannot pass from any
  checkout not named exactly `Grandpa`. Pre-existing; add to P1-3.
- The hang in `test_voice_operator_cmd.py` is a leaked
  `grandpa-listening-animation` daemon thread — the same class of leak behind
  the P1-2 exit-127 crash.

---

## 1. Executive Summary

Grandpa is a **large, genuinely working, Windows-first local AI assistant** (130k LOC Python / 27k LOC Rust / 70k LOC tests) with a real safety architecture, a real local-inference path, and a real desktop-automation layer. On this machine it works: `doctor` reports 39 passed / 0 failures, `ask` answers correctly via Ollama, the FastAPI server starts and serves OpenAI-compatible completions, and 4,424 of 4,437 executed tests pass.

That is the local reality. **The published repository is a different story.** Five findings dominate everything else:

| # | Finding | Severity |
|---|---|---|
| 1 | `.gitignore:120` `runtime/` silently excludes `src/grandpa/runtime/` (8 files, 1,364 LOC). It is **not tracked and not on GitHub**. A clean clone cannot import `grandpa.security`, `grandpa.engine`, or run `grandpa doctor`; 56 test files fail to collect. | **P0 / CRITICAL** |
| 2 | **Every CI workflow on `main` is red** — CI, Docs, Auto-tag, PyPI. The `test` job references 3 test files that do not exist, so it fails before running anything. | **P0 / CRITICAL** |
| 3 | `POST /api/local-action` is **unauthenticated by default** and `keyboard_type` / `keyboard_hotkey` / `mouse_click` are classified MEDIUM risk → **execute with no approval**. This is arbitrary code execution that bypasses the `shell_run` block. Verified live with dry-runs. | **P0 / CRITICAL** |
| 4 | The PyPI name `grandpa` belongs to an **unrelated third party** (Bizerba AI Team, v0.6.3). `grandpa self-update` runs `pip install --upgrade grandpa`, and the CLI phones `pypi.org/pypi/Grandpa/json` on nearly every invocation. | **P1 / HIGH** |
| 5 | Two tests **hang forever** on a machine with audio hardware, so the documented `pytest` command never completes; the suite also **crashes at shutdown** (`Fatal Python error: _enter_buffered_busy`, exit 127) from leaked daemon threads. | **P1 / HIGH** |

Underneath those, the architecture has one structural problem worth naming plainly: **there is no single dispatcher.** `chat` wires 14 natural-language handlers, `ask` wires 5, the REST API wires 4, and `voice-operator` wires 9 — four hand-maintained chains with divergent capability. `docs/architecture/overview.md` claims "Voice and CLI input share one intent-routing and safety path." They do not.

**Recommendation:** do not build features yet. Fix items 1–3 (each is small and mechanical), then unify the dispatcher. Everything else can wait.

---

## 2. Current Project Purpose

The repository currently contains **two products in one tree**, and they describe themselves differently:

- **README.md:** "a privacy-focused local Windows AI assistant designed to control applications, windows, files, keyboard, mouse, screen interactions, and system operations through natural-language voice and CLI commands."
- **pyproject.toml:** "Grandpa — personal AI assistant backend with composable intelligence primitives."

Both are accurate descriptions of code that exists:

**Product A — the Windows assistant** (what README/docs describe, and what most of the LOC serves): `chat` / `ask` / `voice` / `voice-operator` → deterministic regex intent parsing → typed local actions → permission + confirmation + audit → Windows APIs. Ollama is used for conversation, *not* for choosing actions. This is the shipped, working product.

**Product B — the agent platform/SDK** (undocumented in README): `grandpa.sdk` / `SystemBuilder` / `GrandpaSystem` → agent registry (simple, orchestrator, react, rlm, operative, monitor) → tool registry (47 tools) → MCP client+server → A2A protocol → workflow engine → scheduler → telemetry/traces → capability RBAC. This is a general-purpose LLM agent framework.

They meet at exactly one seam: after all deterministic handlers decline, `chat`/`ask` fall through to an agent with tools. They share `core.config`, `core.registry`, `core.types`, `engine`/`runtime`, and `security`.

Historical evidence in the tree shows the project was previously **OpenJarvis**, then **Odin**, now **Grandpa** — see §20.

---

## 3. Repository Structure

```
Grandpa/                                 1,552 tracked files · 226.6 MB · 839 commits
├── .github/          CI, docs, autotag, pypi-publish workflows; CODEOWNERS; templates
├── configs/grandpa/  config.toml example, persona prompts (grandpa.md, neutral.md)
├── docs/             51 markdown pages + gen_ref_pages.py (mkdocs-material)
├── examples/         5 SDK examples (browser_assistant, code_companion, doc_qa, …)
├── models/           6 Ollama Modelfiles (mini, fast, brain, coder, eyes, guard)
├── rust/             17 crates · 124 .rs files · 27,035 LOC (optional, not built)
├── scripts/          burnin, index_docs, oauth_all, production_audit, validate_daily_use
├── src/grandpa/      607 .py files · 130,352 LOC · 53 sub-packages + 30 root modules
├── tests/            349 test files · 69,587 LOC · 4,234 test functions
├── voice_runtime/    247 tracked files — F5-TTS runtime scripts + 207 MB vendored ffmpeg
├── pyproject.toml    hatchling; 21 optional-dependency extras
├── uv.lock           1.0 MB (tracked, intentional)
├── grandpa_tree.txt          3.5 MB generated tree dump (committed)
└── grandpa_project_structure.txt  7.2 MB generated dump (committed)
```

**Missing from the tracked tree but required to run:** `src/grandpa/runtime/` (see §20).

**Largest source modules** (all top-level, not packages):

| File | LOC |
|---|---|
| `src/grandpa/local_actions.py` | 2,203 |
| `src/grandpa/cli/chat_cmd.py` | 2,156 |
| `src/grandpa/server/api_routes.py` | 2,256 |
| `src/grandpa/pc_control.py` | 1,438 |
| `src/grandpa/voice/operator.py` | 1,613 |
| `src/grandpa/memory_context.py` | ~1,500 |
| `src/grandpa/server/routes.py` | 1,343 |

---

## 4. Current Technology Stack

| Layer | Technology | Status |
|---|---|---|
| Language | Python ≥3.10 (tested on 3.11/3.12) | Primary |
| Packaging | hatchling + uv; `uv.lock` tracked | Working |
| CLI | Click 8, lazy-imported subcommands, Rich, prompt-toolkit | Working (51 commands) |
| Inference | Ollama HTTP (`runtime/ollama_adapter.py`); llama-cpp-python (`native_adapter.py`, optional) | Ollama working; native untested |
| API | FastAPI + uvicorn (`server` extra), 230 endpoints | Working |
| STT | faster-whisper | Working |
| TTS | pyttsx3 (SAPI), Kokoro (ONNX), F5-TTS via out-of-process `voice_runtime` service | Working |
| Screen | mss, Pillow ImageGrab, pyautogui, pytesseract/Tesseract, pywin32 UIA | Working |
| Storage | SQLite (28 separate DBs under `~/.grandpa/`) | Working, fragmented |
| Vector/RAG | hash-based local embeddings; optional faiss / ColBERT / BM25 extras | Partial |
| Native accel | Rust workspace, 17 crates, PyO3 via `grandpa-python` + maturin | **Not built, not used** |
| Lint | ruff (E, F, I, W) | **Clean — 0 findings** |
| Tests | pytest, pytest-asyncio, respx, pytest-cov | 13 failures + 2 hangs |
| Docs | mkdocs-material + mkdocstrings | Build failing in CI |

Note: `pyautogui` and `pytesseract` are **core** dependencies, not extras — every install pulls desktop-automation and OCR libraries even for API-only use.

---

## 5. Existing Features

### IMPLEMENTED (verified working)

| Feature | Evidence |
|---|---|
| Ollama inference + streaming | `runtime/ollama_adapter.py`; live: `ask "2+2"` → `4` |
| Reasoning-tag stripping in stream | `ollama_adapter.py:_visible_stream_delta` (strips `<think>`, `<thinking>`, `<analysis>`, `<reasoning>`) |
| Readiness diagnostics | `cli/doctor_cmd.py`; live: 39 passed / 8 optional / 1 warning / **0 failures** |
| CLI surface | 51 registered commands, all lazily imported (`cli/__init__.py`) |
| OpenAI-compatible API | live: `POST /v1/chat/completions` → valid `chatcmpl` response |
| Local action safety layer | `local_actions.py` — allowlist parser + 37-pattern denylist + confirm + audit |
| PC-control risk tiers | `pc_control.py:50–125`; unknown action → `BLOCKED` (default-deny) |
| Approval store + expiry + emergency stop | `pc_control.py:_approve_local_action_impl`, `emergency_stop` |
| Screen capture + OCR + redaction | `screen/service.py`, `screen/redaction.py` (7 pattern classes) |
| Vision UI element graph | `vision/` (UIA + OCR); redaction applied (`vision/graph.py:63`) |
| Windows app resolver | `windows_app_resolver.py`; doctor: "10 allowlisted apps" resolved |
| Window control | `windows_window_control.py` (1,204 LOC) |
| Voice STT/TTS/wake-word/VAD | `voice/` 22 modules, 7,322 LOC; doctor reports voice stack Ready |
| F5 cloned-voice out-of-process runtime | `voice_service/service.py` + `voice_runtime/scripts/` |
| Personal memory (facts + activity) | `memory_context.py` → `~/.grandpa/personal_memory.db` |
| Structured memory V1 | `memory/` (store, short/long-term, preferences, project, retrieval) |
| Agent framework | `agents/` — 8 registered agents; used by `serve`, `ask`, `chat` fallback |
| Tool framework | `tools/` — 47 tools, capability + taint + timeout hooks |
| MCP client **and** server | `mcp/` — stdio, SSE, StreamableHTTP transports |
| Workflow / scheduler / skills / sessions | `workflow/`, `scheduler/`, `skills/`, `sessions/` |
| Telemetry + traces (local-only) | `telemetry/`, `traces/` — verified **no network egress** |
| Security scanners + guardrails | `security/scanner.py`, `guardrails.py`, wired via `setup_security()` |
| SSRF protection | `security/ssrf.py`, used by `tools/http_request.py`, `browser.py`, `web_search.py` |
| Credential-stripping log formatter | `cli/log_config.py:SanitizingFormatter` |
| Config system | `core/config.py` (1,302 LOC), 30 sections, back-compat shims, key validation |
| Ruff clean | `ruff check src tests` → **All checks passed!** |

### PARTIALLY IMPLEMENTED

| Feature | Gap |
|---|---|
| Model runtime abstraction | Two parallel layers: `grandpa.runtime` (ModelRuntime/BackendAdapter) and `grandpa.engine` (InferenceEngine). `engine` is a thin shim; `engine/_network.py::local_port_is_open` is a byte-identical duplicate of `runtime/utils.py::local_port_is_open`. Migration is half-done. |
| Native (llama.cpp) engine | `runtime/native_adapter.py` exists (12 KB); `llama-cpp-python` not installed; doctor: "Not configured", "No GGUF files found". Never exercised. |
| Rust acceleration | 27k LOC across 17 crates. `grandpa_rust` is **not installed**; 16 Python modules try it and silently fall back. `cargo clippy` **fails in CI**. |
| Semantic memory search | `memory_context.py:_embed_text` is an FNV-1a **hashed bag-of-words + trigram** vector, not a learned embedding — despite `SEMANTIC_MODEL = "grandpa-local-semantic-v1"`. Real embeddings only via `memory-faiss`/`memory-colbert` extras. |
| Capability RBAC | `CapabilitiesConfig.enabled = False` by default; `CapabilityPolicy(default_deny=False)` **fails open** even when a policy exists but no grant matches (`capabilities.py:_check_python`). |
| Server auth | `AuthMiddleware` works and is tested, but is only added when an API key is configured — and no key is configured by default, nor documented in `.env.example`. |
| Browser control | `browser_control.py` (43 KB) + `browser/` + `browser_intelligence/` + `browser_awareness/` — four packages, **no redaction** applied to extracted page text. |
| Redaction coverage | Applied in `screen/`, `vision/`, `automation/locator.py`. **Not** applied in `browser*/`. |

### BROKEN

| Feature | Evidence |
|---|---|
| **Clean-clone install** | `src/grandpa/runtime/` untracked → `ModuleNotFoundError: No module named 'grandpa.runtime'` on `grandpa doctor`; 56/349 test files fail collection. |
| **All CI workflows** | GitHub Actions API: CI / Docs / Auto-tag / PyPI all `failure` on the last two `main` pushes. |
| **`.env` support** | README says `copy .env.example .env`. Nothing in the codebase reads `.env`; `python-dotenv` is not a dependency. The file is inert. |
| **`grandpa self-update`** | `_install_detect.py` emits `pip install --upgrade grandpa` → installs an unrelated PyPI package. |
| **Version-check** | `cli/_version_check.py:18` polls `https://pypi.org/pypi/Grandpa/json`, which is a third party's package. |
| **Two hanging tests** | `test_voice_operator_cmd.py::test_voice_operator_command_typed_quit` and `::test_voice_operator_command_typed_fallback_action` — `timeout 60` → exit 124. Marked `core` by conftest. |
| **Suite shutdown crash** | `Fatal Python error: _enter_buffered_busy: could not acquire lock for <_io.BufferedWriter name='<stderr>'> at interpreter shutdown, possibly due to daemon threads` → exit **127**. |
| **13 test failures** | See §18. |
| **Orphaned git submodule** | `voice_runtime/rvc/source` is mode `160000` with **no `.gitmodules`**. `git submodule status` → `fatal: no submodule mapping found`. |
| **`grandpa auth generate-key`** | Referenced in `auth_middleware.py:94` error text; no `auth` command exists. |

### DOCUMENTED ONLY (in docs/changelog, not in code)

| Claim | Reality |
|---|---|
| CHANGELOG 1.0.1: ACE optimizer (`learning/agents/ace_optimizer.py`) | File absent; `learning/` contains only `_stubs.py` + `routing/` |
| CHANGELOG 1.0.1: DSPy and GEPA policies | Zero references in `src/` |
| CHANGELOG 1.0.1: analytics module + `DO_NOT_TRACK` / `grandpa_NO_ANALYTICS` | Zero references; no `[analytics]` config section |
| CHANGELOG 1.0.1: `docs/learning/ace.md`, `docs/telemetry.md`, `install.sh` | None exist |
| `docs/development/repo-structure.md`: "`safety` … own policy and audit" | No `src/grandpa/safety/` package |
| `docs/architecture/overview.md`: "Voice and CLI input share one intent-routing and safety path" | Four divergent chains (§8) |
| Config keys `rate_limit_enabled`, `rate_limit_rpm`, `enforce_tool_confirmation`, `merkle_audit`, `ssrf_protection`, `local_engine_bypass`, `local_tool_bypass`, `signing_key_path`, `vault_key_path` | **All 9 declared in `SecurityConfig` and read nowhere outside `core/config.py`** |
| `.dockerignore` | Present; **no Dockerfile or compose file anywhere** |

### IMPLEMENTED BUT UNDOCUMENTED (answers audit item 9)

| Feature | Why it matters |
|---|---|
| **MCP client + server** with 4 transports (`mcp/`, wired into `SystemBuilder`) | README explicitly claims "no … third-party plugin runtime". This *is* one. No docs page, no CLI command. |
| **Python SDK** (`sdk.py`, 21 KB — `Grandpa`, `GrandpaSystem`, `SystemBuilder`, `MemoryHandle`) | Exported from `grandpa/__init__.py`; no docs page |
| **Agent Runtime V1** (`agent/`, 5,846 LOC) + `grandpa agent` CLI group | Separate from `agents/`; barely documented |
| **Executive planner** (`planner/`, 4,178 LOC) | Doc page exists but is orphaned from mkdocs nav |
| **Knowledge / connectors / RAG** (`knowledge/`, `connectors/`, `tools/storage/`) | ~4,600 LOC, no user docs |
| `grandpa sprint`, `grandpa project`, `grandpa roadmap`, `grandpa operators`, `grandpa vault`, `grandpa skill_builder` | Present in CLI; absent from README's "Core Commands" |
| Auto-generated API reference (607 pages via `docs/gen_ref_pages.py`) | Generated, then **not referenced by `nav:`** — unreachable |

### MISSING

- Any Windows CI runner (product is Windows-only; CI is `ubuntu-latest` only).
- Dockerfile (despite `.dockerignore`).
- `.env` loading.
- Authentication on by default for the local API.
- A shared dispatcher across entry points.
- Rate limiting (module exists, never wired).
- Prompt-injection scanning at ingestion points (module exists, never wired).
- Integration tests that exercise chat → handler → action end-to-end.

### UNKNOWN (could not verify in this environment)

- Whether the Rust workspace compiles: MSVC `link.exe` is **not installed** on this machine (`error: linker 'link.exe' not found`). I could not reproduce the CI clippy failure locally.
- Whether native llama.cpp inference works: `llama-cpp-python` not installed, no GGUF models present.
- Gmail / Google Calendar OAuth flows: no client secrets configured.
- Web search: no `TAVILY_API_KEY` / `BRAVE_SEARCH_API_KEY`.
- Whether the published PyPI package (if it ever succeeded) is functional.
- Behaviour of `wip/floating-bubble-final` (2 unmerged commits) and 2 other unmerged branches.

---

## 6. Current Architecture

```
                    ┌──────────── ENTRY POINTS (4, divergent) ────────────┐
  grandpa chat ─────┤ 14 handlers                                          │
  grandpa ask  ─────┤  5 handlers                                          │
  POST /v1/chat ────┤  4 handlers                                          │
  voice-operator ───┤  9 handlers                                          │
                    └────────────────────┬─────────────────────────────────┘
                                         │  (each chain is hand-written,
                                         │   ~12 lines of boilerplate per probe)
                    ┌────────────────────▼─────────────────────────────────┐
                    │ DETERMINISTIC INTENT HANDLERS                        │
                    │ local_actions · desktop.automation · browser ·       │
                    │ file_assistant · task_scheduler · notes · gmail ·    │
                    │ calendar · downloads · web_search · projects ·       │
                    │ planner.routing · runtime_context (datetime)         │
                    └────────────────────┬─────────────────────────────────┘
                       handled │                       │ no_match / fallback
                    ┌──────────▼──────────┐   ┌────────▼──────────────────┐
                    │ SAFETY POLICY       │   │ LLM PATH                  │
                    │ • _is_dangerous()   │   │ agents registry           │
                    │   37 regex denylist │   │   + ToolRegistry (47)     │
                    │ • allowlist parser  │   │   + MCP tools             │
                    │ • classify_permission│  │   + memory context        │
                    │ • pc_control risk   │   └────────┬──────────────────┘
                    │   LOW/MED/HIGH/BLOCK│            │
                    │ • approval store    │   ┌────────▼──────────────────┐
                    │ • audit (sqlite+jsonl)│ │ security.GuardrailsEngine │
                    └──────────┬──────────┘   │ (secret + PII scanners)   │
                               │              └────────┬──────────────────┘
                    ┌──────────▼──────────┐   ┌────────▼──────────────────┐
                    │ WINDOWS ACTUATION   │   │ grandpa.engine (shim)     │
                    │ pyautogui · pywin32 │   │      ↓                    │
                    │ UIA · mss · OCR     │   │ grandpa.runtime  ◄── UNTRACKED
                    │ os.startfile        │   │ OllamaBackendAdapter      │
                    └─────────────────────┘   │      ↓  httpx             │
                                              │ Ollama :11434             │
                                              └───────────────────────────┘

SHARED KERNEL (healthy):  core.config (111 importers) · core.registry (95) ·
                          core.types (78) · core.events (47)
PARALLEL/UNUSED:          kernel/ (1 importer) · a2a/ (0) · rust/ (0 at runtime)
```

### Architectural strengths

1. **Deterministic-first action routing.** Model output never becomes an action. `handle_local_action` is called only with *user* text (`cli/ask.py:739`, `cli/chat_cmd.py:1918`, `server/routes.py:295`, `server/api_routes.py:1829`). The README's claim here is accurate and it is a genuinely good design.
2. **Allowlist parsing + denylist defense-in-depth.** A paraphrase that dodges `_DANGEROUS_PATTERNS` lands in the allowlist parser and returns `no_match`, not an action.
3. **Default-deny risk classification.** `pc_control._classify_risk_impl` returns `BLOCKED` for any unrecognised action.
4. **Path-traversal handling is correct.** `_normalised_path_parts` calls `.resolve(strict=False)` *before* protection checks; `open_folder` requires `is_dir()`.
5. **Genuine local-only telemetry.** No outbound network calls in `telemetry/`. Verified.
6. **Clean shared kernel.** `core.config`/`registry`/`types`/`events` are cohesive and heavily reused.
7. **Lazy CLI imports.** Keeps startup fast across 51 commands.
8. **Registry isolation + autouse cleanup** in tests (`conftest.py:_clean_registries`).
9. **Ruff-clean** across 200k LOC.

### Architectural weaknesses

1. **No dispatcher** — four divergent routing chains (the dominant structural problem).
2. **Three parallel domain models** — `core/types.py`, `kernel/models.py`, `planner/models.py` each define overlapping types.
3. **Duplicate type names** — 24+ classes defined 2–3×:
   `AgentExecutor` (`agent/executor.py:18`, `agents/executor.py:27`), `AgentContext`, `AgentResult`, `MemoryStore` (`memory/store.py:21`, `memory_context.py:115`), `ToolResult`, `ToolRegistry`, `ExecutionPlan`, `PlanStep`, `RiskLevel`, `SecurityContext`, `WorkflowResult` (×3), `ScanResult`, `StepVerifier`, `SessionStore`, `SchedulerStore`, …
4. **Two intent routers** — `jarvis/intent_router.py` and `router/intent_router.py` (+ `router/legacy_adapter.py`).
5. **Five voice routing paths** — `voice/assistant.py`, `voice/operator.py`, `voice/session.py`, `voice/cli_session.py`, `voice/loop.py`.
6. **`kernel/` is aspirational** — docstring says "Canonical request execution contracts for Grandpa"; exactly **one** consumer (`files/kernel_adapter.py`).
7. **Two observability systems** — event bus + telemetry/traces cover the *platform* layer; `local_actions.py` and `pc_control.py` publish **zero** events and use their own audit path.
8. **God modules at top level** — `local_actions.py` (2,203), `chat_cmd.py` (2,156), `pc_control.py` (1,438), `memory_context.py` (~1,500) sit as flat modules, not packages.
9. **28 separate SQLite databases** under `~/.grandpa/`, 7 of them orphaned (no code references them).
10. **`memory.db` has two owners** — `memory/store.py` (table `memories`) and `tools/storage/sqlite.py` (table `documents`) both default to `~/.grandpa/memory.db`.

---

## 7. Module-by-Module Analysis

| Module | LOC | Role | Assessment |
|---|---|---|---|
| `cli/` | 18,722 | 51 commands | Works well; `chat_cmd.py` is a god-module holding routing + slash commands + presentation |
| `tools/` | 9,791 | 47 tools + storage backends | Cohesive; capability/taint/timeout hooks present |
| `voice/` | 7,322 | STT, TTS, VAD, wake-word, operator | Functional but **5 overlapping routing paths**; 9 of 13 test failures live here |
| `agents/` | 6,758 | Agent registry framework | Sound design; collides with `agent/` |
| `agent/` | 5,846 | "Agent Runtime V1" (plan/step/verify) | Duplicate concept + duplicate type names vs `agents/` |
| `server/` | 4,993 | 230 endpoints | **Unauthenticated by default**; `api_routes.py` (2,256 LOC) untyped payloads |
| `planner/` | 4,178 | Executive planner | Third planning system alongside `agent/` and `workflow/` |
| `kernel/` | 3,272 | "Canonical contracts" | **Effectively dead** — 1 consumer |
| `skills/` | 3,221 | Skill runtime + registry | Reasonable; signature verification via `security/signing.py` |
| `desktop/` | 3,012 | Typed Windows services | Good structure (applications/windows/files/power/clipboard/monitors) |
| `automation/` | 2,859 | Locator + keyboard/mouse pipeline | Confirmation-aware |
| `memory/` | 2,502 | Memory System V1 | Competes with `memory_context.py` |
| `security/` | 2,391 | Scanners, guardrails, audit, RBAC | **4 of 18 modules dead**: `injection_scanner`, `rate_limiter`, `severity_policy`, `subprocess_sandbox` |
| `connectors/` | 2,332 | RAG store/retriever/embeddings | Undocumented |
| `browser_intelligence/` | 2,247 | Page understanding | No redaction applied |
| `vision/` | 1,614 | UI element graph | Redaction applied ✓ |
| `screen/` | 1,541 | Capture + OCR + redaction | Well-scoped, best-factored subsystem |
| `system/` | (small) | `SystemBuilder`/`GrandpaSystem` | Real integration point for the SDK |
| `a2a/` | 460 | Google A2A protocol | **Zero consumers outside itself** — dead |
| `engine/` | 342 | Compat shim over `runtime/` | Should be collapsed |
| `runtime/` | 1,364 | **The actual model runtime** | **UNTRACKED — not in git** |
| `rust/` | 27,035 | 17 crates, PyO3 bindings | Not built, not installed, clippy red in CI |

---

## 8. Data Flow

**Text request (`grandpa chat`)** — `cli/chat_cmd.py`:

```
stdin
 → slash-command handlers (memory, reminders, files, browser, gmail,
   calendar, notes, downloads, search, apps, module, help)
 → natural-intent handlers (assistant, memory, reminder)
 → core_ai_brain analysis  (brain_analysis)
 → handler chain, in order, each `if not X.should_fallback: continue`:
      web_search → projects → executive_goal → gmail → calendar → notes
      → downloads → browser_awareness → browser → desktop → local_action
      → file_assistant → scheduler → datetime
 → (all declined) → agent + ToolRegistry + memory context
 → engine.stream_full() → runtime.OllamaBackendAdapter → httpx → :11434
 → response_cleanup.clean_assistant_response()
 → render + history.append + remember_conversation + record_assistant_outcome
```

The final four side-effect calls are **repeated verbatim at 15 sites** in `chat_cmd.py` (`record_assistant_outcome` appears 17×). This is the single largest duplication hotspot.

**Entry-point capability divergence** (audit item: control flow):

| Handler | chat | ask | REST | voice-operator |
|---|:--:|:--:|:--:|:--:|
| `handle_local_action` | ✅ | ✅ | ✅ | via `assistant.py` |
| `handle_file_command` | ✅ | ✅ | ✅ | `handle_file_automation` |
| `handle_scheduler_command` | ✅ | ✅ | ✅ | ❌ |
| `handle_datetime_intent` | ✅ | ✅ | ❌ | ❌ |
| `handle_memory_command` | *(local variant)* | ✅ | ✅ | `MemoryService.parse_and_route_intent` |
| `handle_desktop_command` | ✅ | ❌ | ❌ | ❌ |
| `handle_browser_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_browser_awareness_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_gmail_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_calendar_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_notes_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_downloads_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_web_search_command` | ✅ | ❌ | ❌ | ✅ |
| `handle_project_command` | ✅ | ❌ | ❌ | ❌ |
| `handle_executive_goal` | ✅ | ❌ | ❌ | ✅ |

A user who says "check my email" gets it in `chat` and `voice-operator`, but not in `ask` or through the API.

---

## 9. LLM / Model Runtime Architecture

```
caller
  → grandpa.engine.get_engine(config, key)          [engine/_discovery.py]
      → EngineRegistry lookup, else lazy-register from grandpa.runtime
  → OllamaEngine(OllamaBackendAdapter, InferenceEngine)   [engine/ollama.py]
      → BackendAdapter → ModelRuntime (ABC)          [runtime/adapter.py, interface.py]
  → generate() / stream() / stream_full() / list_models() / health()
      → httpx → http://127.0.0.1:11434
  → prompt/identity.ensure_grandpa_identity()  (system-prompt injection)
  → response_cleanup.clean_assistant_response()
```

Wrappers applied in `serve`: `GuardrailsEngine` → `InstrumentedEngine` → base engine.

**Observations**

- The abstraction is well-designed: `ModelRuntime` is a clean ABC with `generate`/`stream`/`stream_full`/`list_models`/`health`/`close`/`prepare`, and `StreamChunk` carries `tool_calls`, `content_blocks`, `tool_results`.
- `grandpa.engine` adds essentially nothing over `grandpa.runtime` except exception aliases and one duplicated helper. It is migration residue.
- Generation is capped at `_MAX_NUM_PREDICT = 2048` regardless of caller intent (`ollama_adapter.py:_generation_options`) — a silent ceiling.
- Live measurement: a one-line prompt consumed **740 prompt tokens** and took **11 s** end-to-end on `grandpa-mini` (Qwen2.5-0.5B-Q4). The system prompt is heavy.
- `intelligence.default_model = "grandpa-mini:latest"` but README instructs `ollama pull qwen2.5:3b` — mismatched.
- `models/` ships 6 Modelfiles; the machine has 10 `grandpa-*` models. `grandpa-classic`, `grandpa-general`, `grandpa-heavy`, `grandpa-light` have no Modelfile in the repo.
- OpenAI-*compatible client* support exists only in Rust (`rust/crates/grandpa-engine/src/openai_compat.rs`), which is not built. On the Python side, "OpenAI-compatible" means Grandpa **serves** that API, not that it consumes one.

---

## 10. Memory Architecture

There are **five** memory systems with overlapping responsibilities:

| # | System | Location | Storage |
|---|---|---|---|
| 1 | Personal memory (facts, activity, conversation) | `memory_context.py` (45 importers) | `~/.grandpa/personal_memory.db` |
| 2 | Memory System V1 (structured items, categories, promotion) | `memory/` | `~/.grandpa/memory.db` → table `memories` |
| 3 | RAG document store | `tools/storage/sqlite.py` | `~/.grandpa/memory.db` → table `documents` |
| 4 | Memory files | `MemoryFilesConfig` | `~/.grandpa/MEMORY.md` |
| 5 | Sessions / project memory | `sessions/`, `memory/project_memory.py` | `sessions.db`, `projects.json` |

Systems 2 and 3 **write different schemas into the same default file path**. They coexist (SQLite permits it) but no single owner exists.

**Retrieval quality.** `memory_context._embed_text` produces a 128-dim vector from FNV-1a hashes of tokens plus character trigrams, L2-normalised, compared by cosine. This is a respectable lexical technique — but the constant `SEMANTIC_MODEL = "grandpa-local-semantic-v1"` and the `personal_memory/search` endpoint name imply learned semantics that are not present. True dense retrieval requires the `memory-faiss` or `memory-colbert` extras.

**Privacy.** `SENSITIVE_PATTERN` in `memory_context.py` blocks storing passwords/tokens/OTPs/card numbers/seed phrases as facts. Good.

---

## 11. Voice Architecture

```
microphone (sounddevice)
  → voice/microphone.py + device_manager.py (WASAPI selection, persisted in config)
  → voice/vad.py (energy/silence VAD)
  → voice/wake_word.py  ("hey grandpa", "grandpa")
  → speech/faster_whisper.py (STT)
  → ONE OF FIVE ROUTERS:
       voice/assistant.py     VoiceCommandProcessor → handle_local_action
       voice/session.py       _route_voice_request  → handle_local_action
       voice/operator.py      9 handlers + MemoryService.parse_and_route_intent
       voice/cli_session.py   → VoiceCommandProcessor
       voice/loop.py          continuous loop
  → same safety layer as CLI
  → TTS: speech_output.py → pyttsx3 (SAPI) | Kokoro | grandpa_voice (F5)
       └ F5 path: HTTP → voice_runtime service on :8765 (separate venv, torch)
  → voice_service/post_processing.py (LUFS normalise, true-peak limit, EQ, pitch)
```

**Strengths:** the out-of-process F5 runtime is a genuinely good decision — it keeps `torch` out of the main venv (`implementation_plan.md` §3). Echo rejection, cooldowns, and device recovery are implemented. 74 `GRANDPA_VOICE_*` environment variables give fine control.

**Weaknesses:**
- Five routing paths mean a fix in one voice mode does not reach the others.
- `voice/operator.py` is 1,613 LOC.
- The voice subsystem accounts for **9 of 13** test failures and **both** hangs.
- `synthesis_timeout_seconds = 600.0` in the live config — a single synthesis can block for ten minutes.
- No `[voice]` section exists in `GrandpaConfig`, yet the live `~/.grandpa/config.toml` contains one (mic preferences). It is read via env/`voice/config.py`, not the main config schema — an inconsistency.

---

## 12. Windows Automation Architecture

```
user text ─► local_actions._normalise()          (fillers, synonyms, articles)
          ─► _is_dangerous()  37 regex patterns  ──► BLOCKED + audit
          ─► allowlist parsers (app / folder / url / window / screen /
                                browser / pc_control / automation / skill)
          ─► classify_permission()  allowed | requires_confirmation | blocked
          ─► LocalActionApprovalStore (pending, TTL, audit)
          ─► _execute() ─► desktop.control.* services ─► pyautogui / pywin32 / os.startfile

structured API ─► pc_control.run_local_action(payload)
              ─► desktop.kernel.risk.classify()   LOW | MEDIUM | HIGH | BLOCKED
              ─► requires_approval = request.require_approval OR risk == HIGH
              ─► _preflight_guard()  protected paths; protected active window
              ─► _execute()
```

**Risk tiers as shipped** (`pc_control.py:50–125`):

- **LOW (36 actions, no approval):** `open_app`, `open_folder`, `clipboard_read`, `clipboard_write`, `clipboard_history`, `file_create`, `list_processes`, `browser_open`, `system_lock`, …
- **MEDIUM (23 actions, no approval):** `keyboard_type`, `keyboard_hotkey`, `mouse_click`, `mouse_drag`, `mouse_scroll`, `file_move`, `file_rename`, `file_copy`, `close_app`, `browser_form_fill`, `browser_download`, …
- **HIGH (5, approval required):** `file_delete`, `system_sleep`, `system_restart`, `system_shutdown`, `empty_recycle_bin`
- **BLOCKED (6):** `file_permanent_delete`, `script_run`, `shell_run`, `browser_submit_form`, `browser_extract_password`, `browser_purchase`

**Protected paths:** `C:\Windows`, `C:\Program Files(*)`, `$Recycle.Bin`, `System Volume Information`, `.ssh`, and browser `User Data` profile directories.

**The natural-language path is well guarded.** `_parse_pc_control_action` maps only 17 exact read-only phrases; there is no NL route to `keyboard_type`. The exposure is entirely on the **structured API** — see §16.

---

## 13. API Architecture

- **Factory:** `server/app.py:create_app()` — CORS (default `allow_origins=[]`), security headers, optional `AuthMiddleware`, trace store, PC-control store init, routine scheduler daemon.
- **Routers:** `routes.py` (61 endpoints), `api_routes.py` (~165), `upload_router.py`, `approval_routes.py`, `ws_bridge.py`. **≈230 endpoints total.**
- **Middleware order:** routers added first, then security headers, then auth → auth is outermost. Correct.
- **Auth:** `AuthMiddleware` protects `/v1/*` and `/api/*` when a key exists; key comes from `Grandpa_API_KEY` env or `[server.auth] api_key`. **Neither is documented in `.env.example` or the README.**
- **Bind safety:** `check_bind_safety()` refuses non-loopback binds without a key unless `--allow-insecure-bind`. Good.
- **Schema discipline:** `POST /api/local-action` takes a bare `dict[str, Any]` — no Pydantic model, no validation.
- **Response shape:** `/v1/chat/completions` returns standard OpenAI fields plus non-standard `complexity` and `local_action` keys.

**Live verification (server on 127.0.0.1:8777, default config, no auth header):**

| Request | Result |
|---|---|
| `GET /health` | `200 {"status":"ok"}` |
| `GET /v1/models` | `200` — full model list |
| `GET /v1/info` | `200` |
| `GET /v1/personal-memory` | `200` |
| `GET /api/local-action/pending` | `200 {"actions":[]}` |
| `POST /v1/chat/completions` | `200` — correct completion in 11 s |
| `POST /api/local-action {"action_type":"keyboard_type","dry_run":true}` | `200 {"risk_level":"MEDIUM","approval_required":false,"evidence":{"would_execute":true}}` |
| `POST /api/local-action {"action_type":"shell_run","dry_run":true}` | `200 {"status":"blocked","risk_level":"BLOCKED"}` |

---

## 14. CLI Architecture

`cli/__init__.py` defines a Click group with 51 lazily-imported subcommands (`LazyCommand.invoke` imports on first use and maps `ModuleNotFoundError` for known optional modules to a friendly install hint). Global flags: `--verbose`, `--quiet`, `--fullscreen/--no-fullscreen`. A first-run guard routes bare `grandpa` to chat or init.

**Strengths:** lazy imports keep `--help` fast; consistent optional-dependency messaging; `safe_output.py`, `theme.py`, `hints.py` centralise presentation.

**Weaknesses:**
- `chat_cmd.py` (2,156 LOC) mixes routing, slash-command parsing, memory formatting, and rendering.
- A network call to PyPI fires on nearly every invocation (`_version_check.check_for_updates`), suppressed only by `--quiet`, `GRANDPA_NO_UPDATE_CHECK=1`, or `CI=true`.
- `grandpa models` and `grandpa model` are two separate commands with confusingly similar names.
- Live check: `grandpa screen active` returned `Error: The active window could not be detected.` in a headless-ish shell context — the failure mode is a bare error, with no guidance.

---

## 15. Configuration Architecture

**Precedence:** CLI flags → environment variables → `~/.grandpa/config.toml` → dataclass defaults.
**Schema:** `core/config.py`, 1,302 LOC, `GrandpaConfig` with 26 nested sections, `validate_config_key()` walking `dataclasses.fields()`, back-compat property shims (`cfg.memory` → `cfg.tools.storage`), legacy `[memory]` section remapping, `GRANDPA_HOME` override.

This is the **best-engineered part of the codebase**.

**Problems:**

1. **9 security keys are inert** (§5 DOCUMENTED ONLY) — `rate_limit_enabled`, `rate_limit_rpm`, `enforce_tool_confirmation`, `merkle_audit`, `ssrf_protection`, `local_engine_bypass`, `local_tool_bypass`, `signing_key_path`, `vault_key_path`. Setting `rate_limit_enabled = true` does nothing.
2. **`.env` is never loaded** — the documented workflow is a no-op.
3. **74 environment variables** are read across `src/`; `.env.example` documents ~15.
4. **`Grandpa_API_KEY`** breaks the `GRANDPA_*` convention (case-sensitive on POSIX).
5. **Config-file sprawl** — `~/.grandpa/` holds 8 `config.toml.*.bak` files including one named `.corrupt-20260813-085924`, evidence of past parse failures.
6. **`[voice]` section** in the live config is not part of `GrandpaConfig`.

---

## 16. Security Audit

### CRITICAL

**C-1 — Unauthenticated desktop control via `POST /api/local-action`, with `keyboard_type`/`keyboard_hotkey` unapproved.**
`server/routes.py:1161` exposes `run_local_action` with no auth by default. `pc_control.py:88` classifies `keyboard_type`, `keyboard_hotkey`, `mouse_click`, `mouse_drag` as MEDIUM; `desktop/kernel/risk.py:requires_approval` only forces approval for HIGH or when the *caller* sets `require_approval`. `desktop/control/automation.py:31–55` passes text and keys to `pyautogui.write` / `pyautogui.hotkey` with **no allowlist**.
Consequence: any local process can drive the keyboard — e.g. `hotkey(win,r)` → `write("powershell …")` → `hotkey(enter)` — obtaining arbitrary code execution, which the `shell_run`/`script_run` BLOCKED classification is explicitly designed to prevent. Verified live via `dry_run` (no side effects executed).
Mitigations present: `_preflight_guard` blocks input when the active window is "protected"; `pyautogui.FAILSAFE = True`. Neither stops the Run-dialog path.

**C-2 — Remote approval of pending confirmations.**
`POST /api/local-action/{action_id}/approve` and `POST /v1/local-actions/{action_id}/approve` require only the action id — no user token, no out-of-band channel, no auth. The same unauthenticated channel that stages a confirmation-required action can approve it, collapsing the human-in-the-loop model. (`routes.py:1244`, `routes.py:1268`.)

### HIGH

**H-1 — Local API unauthenticated by default.** All 230 endpoints, including `/v1/personal-memory`, `/api/local-action/*`, `/v1/security/scan`, and file/automation routes, respond `200` with no credentials. Verified live. There is no first-run key generation and no documentation of `Grandpa_API_KEY`.

**H-2 — Security config that does nothing.** `rate_limit_enabled = True` and `enforce_tool_confirmation = True` ship as defaults but are never read. `security/rate_limiter.py` and `security/subprocess_sandbox.py` have zero consumers. Operators reading the config will believe protections are active that are not.

**H-3 — Prompt-injection scanning is dead code.** `security/injection_scanner.py` (167 LOC) is referenced only by a JSON converter in `_rust_bridge.py`. Grandpa ingests untrusted content — screen OCR, browser page text, web-search results, file contents — and none of it is scanned. (The blast radius is limited by the deterministic-action design, but the control exists and is unwired.)

**H-4 — `self-update` installs the wrong package.** `_install_detect.py:51,59,81,86` emit `pip install --upgrade grandpa` / `uv tool upgrade grandpa`. PyPI `grandpa` is owned by "Bizerba AI Team" (v0.6.3, MIT, Azure DevOps homepage) — an unrelated project. A pip-installed user running `grandpa self-update` replaces their install with foreign code.

**H-5 — Capability RBAC fails open.** `CapabilitiesConfig.enabled = False` by default; `setup_security()` constructs `CapabilityPolicy()` with `default_deny=False`; and `_check_python` returns `not self._default_deny` when a policy exists but no grant matches. A partially-specified policy grants everything.

**H-6 — `shell_exec` Rust path bypasses every guard.** `tools/shell_exec.py:120–140` tries `_rust.ShellExecTool().execute(command, working_dir)` **first**, discarding the sanitised environment and the timeout, and hardcodes `returncode: 0, success: True`. Only the `ImportError` fallback applies the Python guards. (Currently inert because `grandpa_rust` is not built — which is why this is HIGH, not CRITICAL.)

### MEDIUM

**M-1 — Redaction gap in browser paths.** `redact_screen_text` is applied in `screen/`, `vision/`, `automation/locator.py`, but **not** in `browser/`, `browser_intelligence/`, or `browser_awareness/`. Page text reaches logs and prompts unredacted.

**M-2 — Persistence-capable file writes without approval.** `file_create` is LOW risk. Protected paths do not include the Startup folder, `%APPDATA%\Roaming` generally, `~/.aws`, `~/.gnupg`, or `~/.grandpa` itself (which holds `.vault_key` and OAuth tokens).

**M-3 — Clipboard read/history at LOW risk.** `clipboard_read` and `clipboard_history` require no approval and can surface passwords copied from a password manager.

**M-4 — Untyped API payloads.** `POST /api/local-action` accepts `dict[str, Any]`; no schema validation on a security-relevant endpoint.

**M-5 — `RUST_AVAILABLE` is a hardcoded lie.** `_rust_bridge.py:35` sets `RUST_AVAILABLE: bool = True` unconditionally, and the module docstring says "The Rust backend is mandatory." Neither is true — `grandpa_rust` is not installed and all 16 consumers fall back. The constant is exported but unused; any future code trusting it will misbehave.

**M-6 — CORS + credentials.** `allow_credentials=True` is fixed; if a user sets `cors_origins = ["*"]`, browser credentials are permitted from any origin.

**M-7 — Outbound PyPI call on nearly every CLI run.** `_version_check.py:185` `urllib.request.urlopen("https://pypi.org/pypi/Grandpa/json")`. Undisclosed in the README's privacy framing, and it queries a third party's package.

**M-8 — `run_sandboxed` uses `shell=True`.** `security/subprocess_sandbox.py:111`. Currently unreachable (no consumers), but it is the module named "sandbox".

### LOW

- `L-1` `os.startfile` on user-supplied folder paths — correctly gated by `is_dir()` and protected-path checks, but any non-protected directory on any drive can be opened.
- `L-2` Only the `grandpa` logger gets the credential-stripping formatter; uvicorn/FastAPI logs are unsanitised.
- `L-3` Hardcoded CSP allows `'unsafe-inline' 'unsafe-eval'` (`server/middleware.py`).
- `L-4` `generate_api_key()` returns an `oj_sk_` prefix — a leftover from the OpenJarvis era.
- `L-5` `_DANGEROUS_PATTERNS` includes bare `\bpassword\b`, `\bterminal\b`, `\bpay\b` — over-broad; "open my password manager" is refused.
- `L-6` LGPL ffmpeg binaries vendored into an Apache-2.0 repository (LICENSE.txt is included, which helps, but redistribution obligations should be reviewed).

### INFO

- **No hardcoded secrets found** in the working tree (regex sweep for key/token/password literals, `sk-`, `ghp_`, `AKIA`, `AIza` shapes). The only `AKIA…` string is a documentation example in `docs/user-guide/security.md:112`.
- No `.env` file is present or tracked.
- Git history contains `src/openjarvis/channels/whatsapp_baileys_bridge/node_modules/**` — committed `node_modules` from a removed feature. Worth a history review for credentials, though none surfaced in filename scanning.
- Telemetry and traces make **no** network calls — the local-only claim holds.

---

## 17. Code Quality Audit

**Good**

- Ruff clean across `src` and `tests` (E, F, I, W).
- Consistent `from __future__ import annotations`, dataclasses with `slots=True`, `__all__` exports, numpy-style docstrings.
- Pervasive type hints.
- Pre-commit configured (ruff + ruff-format).
- Zero `TODO`/`FIXME`/`HACK`/`XXX` in 607 source files.

**Problems**

| Issue | Measure |
|---|---|
| Exception swallowing | **758** `except Exception` sites across **226** files; ~**100** followed immediately by bare `pass` |
| Logging coverage | only **89** of 607 files call `logging.getLogger` |
| Duplicated boilerplate | `record_assistant_outcome` + history + render repeated **17×** in `chat_cmd.py` |
| Duplicate class names | **24+** names defined 2–3× (§6) |
| Exact code duplication | `local_port_is_open` byte-identical in `engine/_network.py` and `runtime/utils.py` |
| God modules | 4 files >1,400 LOC at package top level |
| No issue tracking in code | 0 TODO markers means known gaps live nowhere |
| Silent behaviour differences | Rust path in `shell_exec` returns different semantics than the Python path |

The zero-TODO figure is a double-edged result: the code reads clean, but there is no in-tree record of known limitations, so gaps like the nine inert config keys are invisible to a reader.

---

## 18. Testing Audit

### What exists

349 test files · 69,587 LOC · **4,234 test functions** · 10,369 assertions · 170 files use mocks. Organised into 30 sub-directories mirroring `src/`. `conftest.py` clears all 12 registries and resets the event bus between tests (good).

### Actual results (this machine, full run)

```
13 failed, 4424 passed, 69 skipped, 247 warnings in 1908.87s (0:31:48)
```

**…but that run excluded `tests/cli/test_voice_operator_cmd.py`, which hangs.** With it included, `pytest` never terminates.

**Hangs (verified, `timeout 60` → exit 124):**
- `tests/cli/test_voice_operator_cmd.py::test_voice_operator_command_typed_quit`
- `tests/cli/test_voice_operator_cmd.py::test_voice_operator_command_typed_fallback_action`

Both invoke the real `voice-operator` command without patching `run_voice_operator_loop`, so `SpeechOutputEngine(enabled=True)` and microphone detection run against real hardware. The other 7 tests in that file pass in 0.5 s. `conftest.py` marks both as `@pytest.mark.core` — "core deterministic unit/smoke test".

**Process crash at exit:**
```
Fatal Python error: _enter_buffered_busy: could not acquire lock for
<_io.BufferedWriter name='<stderr>'> at interpreter shutdown,
possibly due to daemon threads
```
Exit code **127**, not 1. Leaked daemon threads (voice/TTS/scheduler) prevent clean shutdown, which also makes CI exit codes unreliable.

**The 13 failures — almost all are stale tests, not broken product code:**

| Test | Cause |
|---|---|
| `cli/test_chat_cmd.py::test_model_preview_handles_ollama_failure` | expects `'Install with: ollama pull qwen2.5:3b'`; code now emits `'Install with: grandpa models pull <model>'` |
| `cli/test_doctor_daily_readiness.py::test_dashboard_uses_expected_grouped_sections` | section renamed `Integration` → `Integrations` |
| `cli/test_model_pull.py::test_pull_cli_only_accepts_ollama` | expects a `--engine` option that no longer exists |
| `speech/test_faster_whisper.py::test_faster_whisper_transcribe` | asserts `is None` but receives `'Grandpa, Notepad, Chrome, Calculator, VS Code, Explorer, Settings, Terminal.'` — **state leaked from another test** |
| `speech/test_faster_whisper.py::test_canonical_transcription_options_are_explicit` | transcription-option dict drift |
| `speech/test_grandpa_voice.py::test_synthesize_service_failure` | `RuntimeError: connection refused` (expects a live F5 service) |
| `test_voice_operator_mode.py` ×3 | `assert False` — real TTS raised `Audio hardware unavailable`; logging then hit `ValueError: I/O operation on closed file` |
| `test_voice_routing_fixes.py::test_background_listening_after_app_launch` | `fake_capture() got an unexpected keyword argument 'on_speech_start'` — fake not updated when the real API gained a parameter |
| `test_voice_runtime.py` ×2 | asserts `'trailing_silence'`; code emits `'silence_timeout'` — field renamed, tests not updated |
| `tools/test_text_to_speech.py::test_tts_tool_registered` | registration assertion |

### Coverage and classification gaps

- **`pyproject.toml` declares 12 markers** (`amd`, `apple`, `browser`, `core`, `environment`, `integration`, `live`, `microphone`, `nvidia`, `optional`, `release`, `slow`). Only `live` is ever used as a decorator (2×). Everything else is applied programmatically to a hardcoded list in `conftest.py`; **everything unlisted defaults to `core`.** The `microphone` marker is defined and never applied — which is exactly why the hangs happen.
- **CI runs 18 of 349 test files** and gates at `--cov-fail-under=20`.
- **CI runs on `ubuntu-latest` only.** Windows automation, pywin32, SAPI TTS, UIA, and window control — the product's core — are never exercised in CI.
- **No end-to-end tests** for chat → handler chain → action.
- **No API auth/authorization tests** beyond `tests/server/test_auth_middleware.py` (which does verify bearer-token behaviour).
- **Test isolation is imperfect** — a Whisper test receiving another test's app-list string is proof of shared mutable state.
- Tests leak real Rich UI output (ASCII banners, "System Error" panels) into captured stdout.

---

## 19. Dependency Audit

**Runtime (core, 12):** `click`, `ddgs`, `httpx`, `pillow`, `pyautogui`, `prompt-toolkit`, `pyttsx3` (win32), `pytesseract`, `rich`, `tomli` (<3.11), `tomlkit`, `psutil`. All are actually imported.

**21 optional extras:** `dev`, `tools-search`, `memory-faiss`, `memory-colbert`, `memory-pdf`, `memory-bm25`, `server`, `gmail`, `calendar`, `browser`, `pdf`, `scheduler`, `security-signing`, `tray`, `windows-notifications`, `speech`, `native`, `screen`, `voice`, `docs`.

**Findings**

1. **Desktop libraries in core.** `pyautogui` and `pytesseract` are unconditional dependencies; `mss` and `pywin32` are in the `screen` extra. Inconsistent grouping, and API-only installs pull GUI automation.
2. **Triple-declared packages.** `ddgs` (core + `tools-search`), `pyttsx3` (core + `voice`), `pillow` (core + `tray`), `faster-whisper` (`speech` + `voice`), `pdfplumber` (`memory-pdf` + `pdf`).
3. **`pytest-timeout` is not a dependency** — there is no way to bound a hanging test, which is precisely the current failure mode.
4. **Rust toolchain undeclared.** README's dev section says `cargo test --manifest-path rust/Cargo.toml` but never mentions that MSVC Build Tools are required on Windows. On this machine, `cargo clippy` fails with `error: linker 'link.exe' not found`.
5. **`uv.lock` (1.0 MB) is tracked**, with an explanatory comment in `.gitignore`. Correct call, well documented.
6. **Rust workspace pins** `rig-core 0.31`, `pyo3 0.23`, `rusqlite 0.32` (bundled SQLite), `ed25519-dalek 2`. Not exercised.
7. **`pip list --outdated` returned nothing** — installed packages are current.
8. **Vendored binary dependency:** ffmpeg 7.1 LGPL shared build (`.exe` + `.dll`, plus the original 62 MB zip) committed to git — see §20.

---

## 20. Git / Repository Integrity Audit

### The `runtime/` issue — confirmed

```
$ git check-ignore -v src/grandpa/runtime/interface.py
.gitignore:120:runtime/    src/grandpa/runtime/interface.py

$ git ls-files src/grandpa/runtime
(empty)
```

`.gitignore` line 120 is `runtime/` with no leading slash, so Git matches **any directory named `runtime` at any depth**. Confirmed matches: `src/grandpa/runtime/`, `rust/runtime/`, `runtime/` at root. (`voice_runtime/` is safe — no match.)

**Which files are affected:** all 8 in `D:\Grandpa\src\grandpa\runtime\` — `__init__.py`, `interface.py`, `adapter.py`, `manager.py`, `native_adapter.py` (12 KB), `ollama_adapter.py` (23 KB), `exceptions.py`, `utils.py` — **1,364 LOC**.

**Are important source files missing from tracking?** Yes. This is the entire model-runtime layer: the `ModelRuntime` ABC, `BackendAdapter`, the Ollama adapter (all real inference code), the llama.cpp adapter, runtime exceptions, and message-serialisation utilities.

**Does the GitHub repo differ from the local tree?** `HEAD == origin/main == a031346a`, and the audit worktree contains only tracked files. So the worktree **is** what is on GitHub — and in it:

```
$ python -m grandpa.cli doctor
ModuleNotFoundError: No module named 'grandpa.runtime'
  (via cli/log_config → security/__init__ → security/guardrails
       → engine/__init__ → engine/ollama → engine/_stubs:14)

$ python -m pytest --co
3284 tests collected, 56 errors in 18.24s
  100% of errors: ModuleNotFoundError: No module named 'grandpa.runtime'
```

`grandpa --help` still works (lazy imports), which is why this went unnoticed.

**Does it affect architecture/deployment?** Yes, fatally. A clean clone cannot import `grandpa.security`, `grandpa.engine`, or anything that transitively touches them. Any wheel built in CI from a fresh checkout would ship without `grandpa/runtime/` and be non-functional.

**Root cause:** `tests/conftest.py:29` writes its test home to `Path.cwd() / "runtime" / "test-home"`, and git history shows `runtime/reports/*.json|md` were previously committed. The `runtime/` ignore was added to keep those local artifacts out — and it collided with the source package that was later created at `src/grandpa/runtime/`.

**Recommended fix — evidence-based, minimal:** anchor the ignore to the repository root and keep the specific sub-patterns.

```gitignore
# Local runtime data (repo-root only — must not match src/grandpa/runtime/)
/runtime/
```

Then `git add -f src/grandpa/runtime/` and verify with `git check-ignore -v src/grandpa/runtime/interface.py` (should print nothing). *Per the audit constraints I have made no change to `.gitignore`; this is a recommendation only.*

### Other repository-integrity findings

**Orphaned submodule (P1).**
```
$ git ls-files -s voice_runtime/rvc/source
160000 81eed5e8f68b6bed1789f682fe78cdd324495afc 0    voice_runtime/rvc/source

$ git submodule status
fatal: no submodule mapping found in .gitmodules for path 'voice_runtime/rvc/source'
```
A gitlink is recorded with **no `.gitmodules`** and no registered URL. Clean clones get an empty directory; `git submodule update --init` cannot work. The local main tree has 6.2 MB of untracked content there.

**Repository bloat (P2).**
```
size-pack: 221.38 MiB      tracked content: 226.6 MB
ffmpeg vendored:           207.6 MB  (91.6% of the repo)
```
`voice_runtime/tools/ffmpeg-7.1-lgpl-shared/` (extracted DLLs/EXEs/docs) **and** the original `ffmpeg-7.1-lgpl-shared.zip` (62 MB) are both committed. Largest single blob: `avcodec-61.dll`, 66 MB. Additionally, `grandpa_project_structure.txt` (7.2 MB) and `grandpa_tree.txt` (3.5 MB) are generated tree dumps committed at the repo root — while `.gitignore` explicitly ignores the equivalent `TREE_STRUCTURE.md`.

**CI is entirely red (P0).** GitHub Actions API for the two most recent `main` pushes:

| Workflow | Conclusion |
|---|---|
| CI | **failure** (`lint` ✅, `test` ❌ "Run tests", `rust` ❌ "Clippy") |
| Deploy Documentation | **failure** |
| Auto-tag on main push | **failure** |
| Publish to PyPI | **failure** |

The `test` job cannot pass regardless of code quality: it names three files that do not exist —
`tests/test_grandpa_feature_audit.py`, `tests/test_integration_foundations.py`, `tests/server/test_pwa_serving.py` — so pytest exits 4 before running. (`test_pwa_serving.py` is a fossil of a removed web dashboard.)

**CODEOWNERS points at strangers (P1).**
```
* @jonsaadfalcon @ANarayan @robbym-dev
```
None of these is the repository owner (`trhariharasudhan`). Combined with `"Adapted from IPW's src/ipw/core/registry.py"` in `core/registry.py` and `engine/_stubs.py`, this is inherited from an upstream project. If the "Require review from Code Owners" ruleset described in the file's own comments is enabled, the actual owner cannot satisfy it.

**Release automation is misaimed (P1).** `autotag.yml` pushes a `v<next-patch>.dev<commit-count>` tag on every `main` push, which triggers `pypi-publish.yml`. The target name `grandpa` is **already owned on PyPI by an unrelated party** (Bizerba AI Team, v0.6.3), so publishing can never succeed — and `grandpa self-update` points users at that same foreign package.

**Rename archaeology.** Evidence of `OpenJarvis → Odin → Grandpa`:
`Grandpa_API_KEY` (mixed case), `oj_sk_` key prefix, `src/openjarvis/**` in history, `~/.grandpa/config.toml.odin-migration-backup`, and `models/Modelfile.mini`'s "Odin is only the internal model-family codename."

**Branch hygiene.** 18 remote branches; 15 are fully merged into `main` (0 commits ahead) and should be pruned. Three carry unmerged work: `wip/floating-bubble-final` (2), `feature/voice-e2e-qa-healthcheck` (1), `feature/screenshot-capture-foundation` (1).

**Docs config points at the wrong repo.** `mkdocs.yml`: `site_url: https://grandpa.github.io/grandpa/`, `repo_url: https://github.com/grandpa/grandpa` — neither exists. 29 of 51 doc pages are orphaned from `nav:`, and the 607 auto-generated API-reference pages are generated but never linked.

---

## 21. Bugs and Broken Components

| ID | Bug | Location | Impact |
|---|---|---|---|
| B-1 | `runtime/` ignored → package unimportable from a clean clone | `.gitignore:120` | **Fatal** |
| B-2 | CI `test` job names 3 non-existent files | `.github/workflows/ci.yml:66–86` | CI can never pass |
| B-3 | Two tests hang forever | `tests/cli/test_voice_operator_cmd.py:7,16` | `pytest` never terminates |
| B-4 | Suite crashes at shutdown, exit 127 | leaked daemon threads | unreliable CI exit codes |
| B-5 | `.env` never loaded | no `dotenv` dependency | documented setup step is a no-op |
| B-6 | `self-update` targets the wrong PyPI package | `cli/_install_detect.py:51,59,81,86` | replaces user install with foreign code |
| B-7 | Version check polls a third party's package | `cli/_version_check.py:18` | wrong data + undisclosed egress |
| B-8 | Orphaned submodule gitlink | `voice_runtime/rvc/source` | clone/submodule commands fail |
| B-9 | `shell_exec` Rust path ignores timeout + env, hardcodes `returncode 0` | `tools/shell_exec.py:120–140` | silent behaviour divergence |
| B-10 | `RUST_AVAILABLE = True` hardcoded and false | `_rust_bridge.py:35` | misleading; module docstring also wrong |
| B-11 | `local_port_is_open` duplicated verbatim | `engine/_network.py` / `runtime/utils.py` | drift risk |
| B-12 | Two schemas share `~/.grandpa/memory.db` | `memory/store.py:17`, `tools/storage/sqlite.py:50` | no clear owner |
| B-13 | `grandpa auth generate-key` referenced but absent | `server/auth_middleware.py:94` | dead-end guidance |
| B-14 | 9 security config keys never read | `core/config.py:537–559` | false sense of protection |
| B-15 | Cross-test state leakage | `speech/test_faster_whisper.py` receives another test's output | flaky suite |
| B-16 | 13 stale test failures | §18 | red suite masks real regressions |
| B-17 | mkdocs `site_url`/`repo_url` point at non-existent repos | `mkdocs.yml:2,5` | broken published docs |
| B-18 | CHANGELOG 1.0.1 describes 5+ absent features | `CHANGELOG.md:15–74` | misleading release notes |

---

## 22. Technical Debt

**Tier 1 — structural**
1. Four divergent entry-point routing chains; no dispatcher.
2. `agent/` vs `agents/` — duplicate frameworks with colliding type names.
3. `core/types.py` vs `kernel/models.py` vs `planner/models.py` — three domain models.
4. `engine/` as a vestigial shim over `runtime/`.
5. Five voice routing paths.
6. Two intent routers plus a "legacy adapter".

**Tier 2 — dead / unused code**
7. `rust/` — 27,035 LOC, 17 crates, never built, clippy red, zero runtime consumers.
8. `a2a/` — 460 LOC, zero external consumers.
9. `kernel/` — 3,272 LOC, one consumer.
10. `security/{injection_scanner,rate_limiter,severity_policy,subprocess_sandbox}.py` — implemented, unwired.
11. `.dockerignore` with no Dockerfile.
12. 7 orphaned SQLite databases in `~/.grandpa/`.

**Tier 3 — hygiene**
13. 207.6 MB of vendored ffmpeg + 10.7 MB of generated tree dumps in git.
14. 758 `except Exception`, ~100 silently `pass`.
15. 4 god-modules >1,400 LOC.
16. 15 stale merged branches.
17. 8 config backup files including a `.corrupt-` one.
18. 29 orphaned doc pages + 607 unlinked generated API pages.
19. Marker taxonomy declared but effectively unused.

---

## 23. Missing Components

| Component | Why it matters |
|---|---|
| Windows CI runner | The product is Windows-only; CI validates only the Linux-portable subset |
| Working `.env` loading | Documented and expected; currently inert |
| Default-on API authentication | 230 endpoints including desktop control are open by default |
| Approval binding to a user channel | Approval requires only an id, on the same open channel |
| Keyboard/hotkey allowlist | Unrestricted `pyautogui.hotkey` defeats `shell_run` blocking |
| Rate limiting (wired) | Module exists, never connected |
| Injection scanning at ingestion | Module exists, never connected |
| `pytest-timeout` | No bound on hanging tests |
| Shared dispatcher | Root cause of capability divergence |
| End-to-end integration tests | Handler chains are untested as chains |
| Dockerfile | `.dockerignore` implies one was intended |
| A correct, available PyPI name | Publishing and self-update are both broken by the collision |
| `.gitmodules` (or gitlink removal) | Clone integrity |

---

## 24. Architecture Risks

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| A new contributor clones and nothing works | **Certain** | Critical | Already true today |
| A real regression ships because CI has been red for weeks | High | Critical | 646 workflow runs, recent ones all failing |
| Local malware or a rogue local app drives the desktop via the open API | Medium | Critical | No auth; `keyboard_type` unapproved |
| A user runs `self-update` and installs a foreign package | Medium | High | Depends on install method |
| Feature added to `chat` silently missing from `ask`/API/voice | **Certain** | High | Already true across 10 handlers |
| Voice fix applied to one of five routing paths only | High | Medium | Already visible in the failure pattern |
| Memory data corruption from two schemas in one DB file | Low | Medium | Coexists today, but no owner |
| Rust layer diverges further from Python until unmaintainable | High | Medium | Already unbuilt and clippy-red |
| Repo becomes unclonable on slow links | Medium | Medium | 221 MB pack for a 130k-LOC project |
| Compliance question over vendored LGPL binaries | Low | Medium | LICENSE.txt is included |

---

## 25. Recommended Fixes

### P0 — Critical (do these first; all are small)

| ID | Fix | Effort |
|---|---|---|
| P0-1 | Change `.gitignore:120` from `runtime/` to `/runtime/`; `git add -f src/grandpa/runtime/`; verify with `git check-ignore` and a clean-clone `pytest --co` | ~15 min |
| P0-2 | Remove the 3 non-existent test files from `ci.yml`; make the `test` job run the deterministic suite rather than a hand-listed set | ~30 min |
| P0-3 | Move `keyboard_type`, `keyboard_hotkey`, `mouse_click`, `mouse_drag`, `browser_form_fill`, `browser_download` from MEDIUM to approval-required; add a hotkey denylist (`win+r`, `ctrl+shift+esc`, `win+x`, …) | ~2 h |
| P0-4 | Generate an API key on first run and require it by default; document `GRANDPA_API_KEY` (and keep `Grandpa_API_KEY` as a deprecated alias) | ~3 h |
| P0-5 | Require an out-of-band confirmation token for `/api/local-action/{id}/approve` — an id alone must not authorise | ~3 h |
| P0-6 | Add `pytest-timeout` to `dev`, set a default timeout, and mark the two hanging voice tests `@pytest.mark.microphone` + skip unless opted in | ~1 h |

### P1 — High

| ID | Fix |
|---|---|
| P1-1 | Fix `self-update` and `_version_check`: pick an available PyPI name (e.g. `grandpa-assistant`), or disable both paths until one is secured |
| P1-2 | Fix the daemon-thread leak so the suite exits 0/1 instead of 127 |
| P1-3 | Fix the 13 stale test failures (all are test-side drift, not product bugs) |
| P1-4 | Either add `.gitmodules` for `voice_runtime/rvc/source` or remove the gitlink |
| P1-5 | Either add `python-dotenv` and load `.env`, or delete `.env.example` and the README step |
| P1-6 | Wire `enforce_tool_confirmation` and `rate_limiter`, or delete the 9 inert config keys |
| P1-7 | Flip `CapabilityPolicy` to fail-closed when a policy exists but no grant matches |
| P1-8 | Remove the Rust-first path in `shell_exec` (or make it honour timeout + env + real return code) |
| P1-9 | Replace `CODEOWNERS` with the real owner |
| P1-10 | Fix `mkdocs.yml` `site_url`/`repo_url`; get the Docs workflow green |
| P1-11 | Add a `windows-latest` CI job for the Windows-specific suites |
| P1-12 | Apply redaction in `browser*/` page-text extraction |

### P2 — Medium

- Purge vendored ffmpeg from history (`git filter-repo`) and download it in `voice_runtime/scripts/setup.ps1` instead; drop `grandpa_tree.txt` / `grandpa_project_structure.txt`.
- Delete or archive `a2a/`; decide `kernel/`'s fate (adopt it or remove it).
- Decide the Rust question (see §26) — do not leave 27k LOC unbuilt and red.
- Give `memory.db` a single owner; separate the RAG document store.
- Rename `SEMANTIC_MODEL` / document that memory search is lexical, not learned.
- Delete the 4 unwired security modules or wire them.
- Reconcile `CHANGELOG.md` 1.0.1 with reality.
- Prune the 15 merged branches.
- Add `api-reference` to `nav:`; adopt or delete the 29 orphaned doc pages.
- Split `pyautogui`/`pytesseract` out of core dependencies into the `screen` extra.

### P3 — Low

- Collapse `engine/` into `runtime/`; delete `engine/_network.py`.
- Replace the 15 duplicated handler blocks in `chat_cmd.py` with one loop.
- Rename `oj_sk_` → `gp_sk_`.
- Narrow `_DANGEROUS_PATTERNS` (`\bpay\b`, `\bterminal\b`, bare `\bpassword\b`).
- Sanitise uvicorn/FastAPI logs with `CredentialStripper`.
- Tighten the CSP (drop `'unsafe-eval'`).
- Clean up `~/.grandpa/config.toml.*.bak` files.
- Reconcile README's `qwen2.5:3b` with `intelligence.default_model = grandpa-mini:latest`.

---

## 26. Recommended Target Architecture

### CURRENT ARCHITECTURE (as built, verified)

- 4 entry points, each with its own hand-written handler chain (14 / 5 / 4 / 9 handlers).
- 5 voice routing paths, 2 intent routers.
- 2 agent frameworks (`agent/`, `agents/`), 3 domain models (`core`, `kernel`, `planner`), 3 planning systems (`agent`, `planner`, `workflow`).
- Model access: `engine/` shim → `runtime/` adapters → Ollama.
- Safety: allowlist parse + denylist + permission classification + approval store + audit, applied on the natural-language path; a separate risk-tier model on the structured API path, with no authentication.
- Observability: event bus + telemetry + traces for the platform layer; a separate audit trail for the Windows layer.
- 27k LOC of Rust that is never built and never loaded.
- 28 SQLite databases, 7 orphaned.

### PROPOSED TARGET ARCHITECTURE

*(Proposed only. Nothing below has been implemented, and none of it should be started before the P0 list is done.)*

```
        grandpa chat │ grandpa ask │ POST /v1/chat │ voice │ voice-operator │ SDK
                     └──────┬──────┴───────┬───────┴───┬────┴────────┬───────┘
                            ▼              ▼           ▼             ▼
                   ┌───────────────────────────────────────────────────────┐
                   │  IntentDispatcher   (ONE implementation)              │
                   │  • ordered registry of IntentHandler protocol         │
                   │  • every entry point gets the same handler set        │
                   │  • one place for history / memory / audit / events    │
                   └───────────────────────┬───────────────────────────────┘
                                           ▼
                   ┌───────────────────────────────────────────────────────┐
                   │  PolicyEngine   (ONE risk + approval model)           │
                   │  • merges local_actions.classify_permission and       │
                   │    pc_control risk tiers into one table               │
                   │  • approval requires an out-of-band token             │
                   │  • capability RBAC fail-closed                        │
                   │  • injection scanning on all untrusted ingress        │
                   │  • rate limiting                                      │
                   └───────────────────────┬───────────────────────────────┘
              ┌────────────────────────────┼────────────────────────────┐
              ▼                            ▼                            ▼
    ┌──────────────────┐        ┌────────────────────┐      ┌──────────────────┐
    │ ACTUATION        │        │ MODEL RUNTIME      │      │ MEMORY           │
    │ desktop/ screen/ │        │ grandpa.runtime    │      │ one façade over: │
    │ vision/ browser/ │        │ (engine/ removed)  │      │  facts │ items   │
    │ files/ automation│        │ Ollama │ native    │      │  docs  │ sessions│
    └────────┬─────────┘        └─────────┬──────────┘      └────────┬─────────┘
             └──────────────────┬─────────┴──────────────────────────┘
                                ▼
                   ┌───────────────────────────────────────────────────────┐
                   │  UNIFIED OBSERVABILITY — one event bus                │
                   │  telemetry · traces · audit  (all layers publish)     │
                   └───────────────────────────────────────────────────────┘
```

**Key decisions to make explicitly:**

1. **Dispatcher first.** One `IntentHandler` protocol + one ordered registry. Every entry point becomes ~10 lines. This removes the 15× duplication in `chat_cmd.py` and eliminates capability divergence by construction.
2. **One policy engine.** The NL path and the structured API path must share one risk table and one approval mechanism.
3. **Delete `engine/`.** Have callers import `grandpa.runtime` directly; keep exception aliases for one release.
4. **Pick one agent framework.** Keep `agents/` (registry-based, used by `serve`/`sdk`); fold the useful parts of `agent/` (plan/step/verify) into it or into `planner/`. Do not keep both.
5. **Decide on Rust.** Either (a) build it in CI, install it, and make it the fast path with tested Python fallbacks; or (b) delete the workspace and the `_rust_bridge` call sites. The current state — 27k LOC, unbuilt, clippy-red, silently bypassed — is the worst of both.
6. **Decide on `kernel/`.** Its docstring claims canonical contracts; adopt it as the domain model *or* delete it. One consumer is not a design.
7. **Keep the two-product framing but make it explicit.** Ship `grandpa` (Windows assistant) and `grandpa.sdk` (agent platform) as documented, separately-described surfaces rather than an undocumented overlap.

**Preserve unchanged:** `core/config.py`, `core/registry.py`, `core/types.py`, `core/events.py`, `screen/`, `vision/`, `desktop/control/`, `security/scanner.py`, `security/ssrf.py`, `security/file_policy.py`, `runtime/ollama_adapter.py`, the deterministic-first routing principle, and the out-of-process F5 voice runtime.

---

## 27. Recommended Implementation Order

**Phase 0 — Make the repository real (1 day)**
1. P0-1 fix `.gitignore` + commit `src/grandpa/runtime/` → *unblocks everything*
2. P0-2 fix the CI test job → *green CI is the gate for all later work*
3. P0-6 add `pytest-timeout`; mark/skip the two hanging tests
4. P1-4 resolve the orphaned submodule
5. Verify: fresh `git clone` → `uv sync` → `grandpa doctor` → `pytest` completes

**Phase 1 — Close the security holes (2–3 days)** *(depends on Phase 0 for a green gate)*
6. P0-3 re-tier keyboard/mouse/browser-form actions + hotkey denylist
7. P0-4 API key on by default + first-run generation + docs
8. P0-5 out-of-band approval tokens
9. P1-7 capability policy fail-closed
10. P1-8 remove the `shell_exec` Rust bypass
11. P1-12 redaction in browser paths
12. Add regression tests for each of the above

**Phase 2 — Make the suite trustworthy (2–3 days)**
13. P1-2 fix the daemon-thread leak (exit 127 → 0/1)
14. P1-3 fix the 13 stale failures
15. Fix cross-test state leakage in the speech tests
16. P1-11 add a `windows-latest` CI job
17. Apply the marker taxonomy for real (`microphone`, `environment`, `slow`)

**Phase 3 — Truth in documentation (1–2 days)** *(no code risk; can run parallel to Phase 2)*
18. P1-5 `.env` — implement or remove
19. P1-6 inert security config keys — wire or remove
20. P1-1 / P1-9 / P1-10 PyPI name, CODEOWNERS, mkdocs URLs
21. Reconcile CHANGELOG, README, `repo-structure.md`, `architecture/overview.md` with the code
22. Document MCP, the SDK, and the agent runtime

**Phase 4 — Structural consolidation (1–2 weeks)** *(requires Phases 0–2)*
23. Introduce `IntentDispatcher`; migrate `chat` first, then `ask`, API, voice
24. Merge the two risk models into one `PolicyEngine`
25. Collapse `engine/` into `runtime/`
26. Choose one agent framework; deprecate the other
27. Decide `kernel/`, `a2a/`, and Rust
28. Unify the event bus across the Windows layer

**Phase 5 — Hygiene (ongoing)**
29. History purge of vendored binaries
30. Split god-modules; audit the ~100 silent `except: pass` sites
31. Prune branches, orphaned DBs, backup configs

**Only after Phase 4 should new features begin.**

---

## 28. Feature Gap Analysis

| Capability | Current | Intended (README + roadmap) | Gap |
|---|:--:|:--:|---|
| 1. Reliable voice-command pipeline | Partial | Priority #1 | Works, but 5 routing paths, 9/13 test failures, 2 hangs |
| 2. Accurate intent parsing | Partial | Priority #2 | Regex allowlists per handler; 2 competing routers; no shared dispatcher |
| 3. Windows application control | **Yes** | Priority #3 | 10 allowlisted apps resolved; resolver works |
| 4. Screen understanding | **Yes** | Priority #4 | Capture + OCR + UIA + redaction all working |
| 5. Mouse and keyboard automation | **Yes** (unsafe) | Priority #5 | Works, but unapproved and unauthenticated over HTTP |
| 6. File and folder management | **Yes** | Priority #6 | Protected paths enforced |
| 7. Safe system operations | Partial | Priority #7 | HIGH tier gated; MEDIUM tier is not |
| 8. Context-aware multi-step automation | Partial | Priority #8 | 3 competing planners (`agent`, `planner`, `workflow`) |
| 9. Local AI performance | Partial | Priority #9 | 740-token system prompt; 11 s for a trivial reply; 2048-token hard cap; Rust accel unbuilt |
| 10. Voice feedback + error recovery | Partial | Priority #10 | Echo rejection and recovery exist; TTS failure paths are the failing tests |
| 11. Permission controls + audit logs | Partial | Priority #11 | Strong on the NL path; absent on the API path |
| 12. Comprehensive Windows regression testing | **No** | Priority #12 | CI is Linux-only; Windows suites never run in CI |

**Capabilities present but *not* in the intended scope** (undocumented surface that nonetheless exists): MCP client/server, A2A protocol, Python SDK, workflow engine, agent scheduler, skills runtime, knowledge/RAG connectors, browser intelligence, autonomous development workflow, sprint runner, project engineer mode.

---

## 29. Questions / Unknowns

1. **Is the two-product scope intentional?** Should the agent platform (MCP, SDK, A2A, workflow) be documented and supported, or extracted/removed? This decision drives roughly half the refactor.
2. **What is the Rust workspace for?** 27k LOC, never built, clippy-red. Was it abandoned, or is it a planned fast path?
3. **Why does `CODEOWNERS` list `@jonsaadfalcon @ANarayan @robbym-dev`?** Is this repo derived from an upstream project ("IPW" is referenced twice in source comments)? If so, attribution and licensing should be reviewed.
4. **Is PyPI publishing actually wanted?** The name is taken. If yes, a new name is needed; if no, remove `pypi-publish.yml`, `autotag.yml`, and the self-update path.
5. **Is `~/.grandpa/runtime` or `GRANDPA_RUNTIME_DIR` (in `.env.example`) meant to be the local-artifacts location?** That would make the root `runtime/` ignore unnecessary.
6. **Which memory system is canonical?** `memory_context.py` has 45 importers; `memory/` is called "Memory System V1". Both are active.
7. **Was `kernel/` meant to be adopted repo-wide?** Its docstring says "canonical"; it has one consumer.
8. **Are the 7 orphaned databases safe to delete** (`iot_smart_home`, `mobile_integration`, `future_features`, `real_world_tasks`, `sync_state`, `communication_integration`, `autonomous_workflows`), or is there data worth migrating?
9. **What is in `wip/floating-bubble-final`?** 2 unmerged commits suggest a UI experiment.
10. **Does the Rust workspace compile at all?** Not verifiable here — MSVC `link.exe` is absent on this machine.
11. **Does native llama.cpp inference work?** `llama-cpp-python` not installed, no GGUF models present.
12. **Is the vendored LGPL ffmpeg redistribution reviewed?** LICENSE.txt is included; obligations under Apache-2.0 packaging should be confirmed.

---

## 30. Final Recommendation

**Fix first — in this order, and nothing else until they are done:**
1. `.gitignore` `runtime/` → `/runtime/` and commit `src/grandpa/runtime/`. Everything downstream is blocked on this.
2. Remove the three phantom test files from `ci.yml` so CI can go green.
3. Re-tier `keyboard_type`/`keyboard_hotkey`/`mouse_*` and turn on API authentication by default.
4. Add `pytest-timeout` and quarantine the two hanging voice tests.

**Preserve — this code is good and should not be touched:**
`core/config.py` (the best-engineered module in the repo), `core/registry.py`, `core/types.py`, `core/events.py`, `screen/` (cleanest subsystem), `vision/`, `desktop/control/`, `runtime/ollama_adapter.py`, the `security/` scanners and SSRF/file-policy modules, the out-of-process F5 voice runtime, the lazy CLI command loader, and above all the **deterministic-first routing principle** — the fact that model output never becomes an action is the single best decision in this codebase and must survive any refactor.

**Refactor:**
The four entry-point handler chains into one `IntentDispatcher`. The two risk models into one `PolicyEngine`. `engine/` collapsed into `runtime/`. The five voice routing paths into one. `chat_cmd.py` split into routing / commands / presentation.

**Redesign:**
The memory layer — five systems, two sharing one database file, and a hash-based retriever presented as semantic. Pick one façade, one storage owner, and either adopt real embeddings or rename the constant and say plainly that search is lexical.

**Remove or commit to:**
`rust/` (27k LOC), `a2a/` (0 consumers), `kernel/` (1 consumer), the four unwired security modules, and 207 MB of vendored binaries. Each is either a real plan that needs finishing or dead weight that needs deleting; leaving them in limbo is the expensive option.

**Build next — but only after Phases 0–2:**
Nothing new. The most valuable next feature is a green CI on Windows, because until that exists, no feature can be shown to work.

---

### Appendix — Verification commands used

```bash
git check-ignore -v src/grandpa/runtime/interface.py     # → .gitignore:120:runtime/
git ls-files src/grandpa/runtime                          # → (empty)
git ls-files -s voice_runtime/rvc/source                  # → 160000 (gitlink, no .gitmodules)
git ls-tree -r -l HEAD | sort -k4 -rn | head              # → 207.6 MB ffmpeg
python -m pytest --co                                     # clean clone: 56 errors, all grandpa.runtime
python -m pytest -q                                       # main tree: 13 failed, 4424 passed, exit 127
python -m ruff check src tests                            # → All checks passed!
python -m grandpa.cli doctor                              # → 39 passed, 0 failures
curl -s http://127.0.0.1:8777/api/local-action/pending    # → 200, no auth
curl -X POST .../api/local-action -d '{"action_type":"keyboard_type","dry_run":true}'
                                                          # → MEDIUM, approval_required: false
curl https://api.github.com/repos/trhariharasudhan/Grandpa/actions/runs
                                                          # → CI/Docs/Autotag/PyPI all failure
curl https://pypi.org/pypi/Grandpa/json                   # → grandpa 0.6.3, Bizerba AI Team
```

**Environment limitations:** MSVC `link.exe` is not installed, so the Rust workspace could not be compiled and the CI clippy failure could not be reproduced locally. `mkdocs` is not installed, so the docs build failure could not be reproduced locally. Gmail/Calendar OAuth, web-search providers, and native llama.cpp inference were not configured and therefore not exercised.
