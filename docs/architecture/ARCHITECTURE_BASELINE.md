# Architecture Baseline

A checkpoint of the Grandpa repository after the P0 and P1 stabilization work,
taken before architecture analysis and target-architecture design begin.

**Purpose:** establish an agreed, verified description of what exists today, so
the next phase argues about direction rather than about facts.

## How to read this document

Every claim is tagged:

| Tag | Meaning |
|-----|---------|
| **[FACT]** | Verified by running a command against this commit. Reproducible. |
| **[RECOMMENDATION]** | An engineering opinion. Not yet agreed, not yet acted on. |
| **[OPEN]** | An assumption or unanswered question. Needs a human decision. |

Nothing tagged **[RECOMMENDATION]** has been implemented. This document changes
no code.

---

## 1. Repository state

**[FACT]** Exact state this baseline describes:

| Property | Value |
|----------|-------|
| HEAD | `1584e69b8a189ff74f39e44c6710774ca1165817` |
| HEAD (short) | `1584e69b` |
| Branch | `claude/grandpa-codebase-audit-bf609c` |
| Working tree | **Clean** at capture time. This document is the only addition since, and is untracked until committed. |
| Merge base | `a031346a` (`origin/main`) |
| Commits ahead of `origin/main` | **12** |
| Pushed to remote | **No** |

**[FACT]** Scale at this commit:

| Area | Files | Lines |
|------|-------|-------|
| `src/` Python | 616 | 132,013 |
| `tests/` Python | 381 | 70,145 |
| `rust/` Rust | 124 | 27,035 |
| Tracked files (all) | 1,561 | — |
| Documentation pages | 51 | — (52 including this baseline, untracked at HEAD) |
| CLI commands registered | 51 | — |

**[FACT]** Repository weight: pack is **221.5 MiB**; tracked content is
**226.8 MB**, of which **207.6 MB (91.5%)** is vendored ffmpeg binaries under
`voice_runtime/tools/`.

---

## 2. Commit history since the baseline

**[FACT]** Twelve commits, oldest first.

| # | SHA | Subject | Change |
|---|-----|---------|--------|
| 1 | `ce3afcb8` | `fix(repo): restore runtime package and repair CI infrastructure` | 14 files, +1419 −11 |
| 2 | `de7d8f70` | `fix(security): harden local API and desktop action approval` | 13 files, +525 −42 |
| 3 | `f5bd5d60` | `chore(repo): clean up voice runtime and finalize API key identity` | 4 files, +1181 −3 |
| 4 | `8555ec89` | `fix(update): prevent unsafe self-update target` | 8 files, +300 −574 |
| 5 | `fdaefa4a` | `fix(runtime): cleanly shut down background workers` | 4 files, +339 −86 |
| 6 | `5709c621` | `fix(voice): repair voice operator recovery` | 2 files, +55 |
| 7 | `142c3905` | `test: synchronize stale tests with current behavior` | 7 files, +127 −29 |
| 8 | `0ab55c9b` | `style: apply ruff-format to previously unformatted tests` | 7 files, +137 −38 |
| 9 | `ff99715f` | `fix(config): remove or implement inert configuration` | 11 files, +217 −104 |
| 10 | `567530ea` | `style: apply ruff-format to previously unformatted sources` | 8 files, +100 −50 |
| 11 | `fad917a0` | `test: update stale microphone capture fake` | 1 file, +5 −1 |
| 12 | `1584e69b` | `fix(runtime): measure tick duration with a monotonic clock` | 2 files, +10 −2 |

### What each commit actually fixed

**`ce3afcb8` — runtime package recovery.** `.gitignore` carried an unanchored
`runtime/` pattern, which Git matches at any depth. It silently excluded
`src/grandpa/runtime/` — the ModelRuntime layer — from version control. A clean
clone could not import `grandpa.engine` or `grandpa.security`, could not run
`grandpa doctor`, and any wheel built from a fresh checkout shipped without the
package. All six `runtime/` patterns anchored to the repo root; 8 modules
(1,364 LOC) committed. Also removed three test files from `ci.yml` that do not
exist (the test job failed at collection on every run), fixed one stale doctor
assertion, added `pytest-timeout` with a 300 s cap, and quarantined two tests
that drive real audio hardware behind a `microphone` marker.

**`de7d8f70` — security hardening.** Three defects. (a) The API was
unauthenticated by default; loopback is not an isolation boundary, so any local
process could read personal memory and drive the desktop. (b) Synthetic input
(`keyboard_type`, `keyboard_hotkey`, `mouse_click`, `mouse_drag`,
`browser_form_fill`, `browser_download`) was MEDIUM risk and ran unattended —
`keyboard_hotkey` opens a launcher and `keyboard_type` fills it in, reaching
exactly the capability `script_run`/`shell_run` are BLOCKED to prevent.
(c) Approval accepted an `action_id` alone, so the caller that staged an action
could approve its own request.

**`f5bd5d60` — repository cleanup.** `voice_runtime/rvc/source` was a gitlink
(mode 160000) with no `.gitmodules`, so `git submodule status` failed on every
clone. The repository never held content for it (`git cat-file` cannot resolve
the recorded commit), so removal dropped a dangling pointer, not source. Also
renamed the generated API key prefix `oj_sk_` → `gp_sk_` and added `AUDIT.md`.

**`8555ec89` — self-update.** `grandpa self-update` could install an unrelated
project: PyPI `grandpa` belongs to "Bizerba AI Team" (v0.6.3, an
image-recognition library), and install detection emitted
`pip install --upgrade grandpa` for pypi installs, `uv tool upgrade grandpa` for
uv-tool installs, and the pip command again as the fallback for every
unidentified case. `_version_check` polled that project's release feed on nearly
every CLI run. Editable-git checkouts remain the only shape that runs anything.

**`fdaefa4a` — background worker shutdown.** The suite aborted with
`Fatal Python error: _enter_buffered_busy … <_io.BufferedWriter name='<stderr>'>`.
The two CLI animations write to a Console from a daemon thread, and
`VoicePresenter` builds its Console with `stderr=True`. `start_listening()`
assigned a new animation object over a running one, orphaning its stop event.
Both classes now share one lifecycle in `cli/_animation.py`: idempotent
`start()`, an `atexit` hook, and a `sys.is_finalizing()` write guard.

**`5709c621` — voice operator recovery.** A genuine product bug, not stale
tests. `build_voice_session` constructed `VoicePresenter` without `output`, so
the presenter chose its rendering mode against the default `print` and sent
everything to stderr; `VoiceSession.__post_init__` assigned `presenter.output`
afterwards, too late. Any embedder passing `output=` — and any screen-reader
user, same branch — silently lost every message including unrecoverable
microphone and TTS errors. All 67 voice-operator tests passed unchanged.

**`142c3905`, `fad917a0` — stale tests.** Eight failures investigated
individually; product verified correct in every case. VAD reason label, removed
`--engine` option, changed model hint, retuned Whisper decoding policy, a
checkout-directory-name assumption, an `importlib.reload` that broke exception
class identity, a registry-clear ordering dependency, and a fake whose signature
had drifted from the real one.

**`ff99715f` — configuration.** Ten `SecurityConfig` keys were accepted by the
loader and read by nothing. Two were actively misleading: `ssrf_protection`
implied an off switch for a control that is unconditional, and
`enforce_tool_confirmation` defaulted true and suggested a global guarantee that
does not exist. Removed, with `REMOVED_CONFIG_KEYS` warning on load. `.env`
resolved by removing `.env.example` and the README step, since nothing reads
`.env`.

**`1584e69b` — monotonic clock.** `AgentExecutor` measured ticks with
`time.time()`. Wall clock is the wrong primitive for a duration: it can step
backwards on clock adjustment, and its Windows granularity is ~15.6 ms, so every
agent tick faster than that was persisted to the trace store with **zero
latency** — a data-quality bug the analyzer averages over.

**`0ab55c9b`, `567530ea` — formatting only.** Fifteen files that predate current
formatter settings. Separated from substantive commits deliberately.

---

## 3. Test and lint status

**[FACT]** Measured at HEAD `1584e69b`:

| Gate | Result |
|------|--------|
| **Full `pytest`** | **4455 passed, 0 failed, 0 errors, 71 skipped — exit 0** (17 m 30 s) |
| `Fatal Python error` occurrences | **0** |
| Hangs | **None** — suite terminates unattended |
| CI-equivalent selection | 248 passed, exit 0 |
| `tests/security/` | 254 passed, 14 skipped |
| `tests/server/` | 127 passed, 1 skipped |
| Approval (`pc_control`, `pc_control_api`, `local_actions`) | 101 passed |
| Voice group (8 files + `tests/speech/`) | 301 passed |
| `ruff check src/ tests/` | All checks passed |
| `ruff format --check src/ tests/` | 986 files already formatted |

**[FACT]** This is a genuine green baseline: zero failures, zero errors, clean
exit code. Before this work the suite never finished — it hung indefinitely on
`test_voice_operator_cmd.py`; when that file was excluded it reported 13 failures
and exit 127.

**[FACT]** The 71 skips are deliberate: optional dependencies, hardware-gated
tests (`microphone`, opt in with `GRANDPA_RUN_MICROPHONE_TESTS=1`), and live
service tests.

**[OPEN]** Coverage is not measured outside CI's `--cov-fail-under=20` gate. The
real figure is unknown, and 4455 passing tests over 132 k lines says nothing
about which paths are exercised.

---

## 4. Confirmed architecture problems

**[FACT]** These are measured, not inferred.

### 4.1 Divergent routing chains

Five entry points each maintain their own hand-written chain of natural-language
handlers. Handler counts:

| Entry point | Handlers wired |
|-------------|----------------|
| `cli/chat_cmd.py` | 14 |
| `voice/assistant.py` | 11 |
| `voice/operator.py` | 9 |
| `cli/ask.py` | 5 |
| `server/routes.py` | 4 |

A natural-language command that works in `grandpa chat` may silently not work in
`grandpa ask`, over the API, or in voice. There is no shared dispatcher; each
chain is a linear sequence of `if not result.should_fallback:` probes with
duplicated bookkeeping (history append, memory write, outcome record, render).

### 4.2 Duplicate domain models

29 class names are defined two or more times in `src/`:

`WorkflowResult` (×3), and ×2 each: `WindowInfo`, `VerificationResult`,
`ValidationResult`, `ToolResult`, `ToolRegistry`, `ToolExecutor`, `StepVerifier`,
`StepStatus`, `SkillResult`, `SessionStore`, `SecurityContext`,
`SecurityBlockError`, `SchedulerStore`, `ScanResult`, `RiskLevel`,
`RecoveryAttempt`, `PlanStep`, `OllamaEmbedder`, `OcrResult`, `MonitorInfo`,
`MemoryStore`, `KnowledgeStore`, `ExecutionPlan`, `ConfirmationRequest`,
`AutomationResult`, `AgentRuntime`, `AgentResult`, `AgentGoal`.

The most consequential: `ToolResult` and `ToolRegistry` exist in both
`core/` and `kernel/`; `AgentResult`/`AgentContext`/`AgentExecutor` exist in both
`agent/` (singular) and `agents/` (plural); `MemoryStore` exists in both
`memory/store.py` and `memory_context.py`.

### 4.3 An aspirational canonical layer that nothing uses

`grandpa/kernel/` (3,272 LOC) describes itself as "Canonical request execution
contracts for Grandpa". It has **one** consumer outside itself:
`src/grandpa/files/kernel_adapter.py`.

### 4.4 Dead subsystems

| Module | Consumers outside itself |
|--------|--------------------------|
| `grandpa/a2a/` (460 LOC, Google A2A protocol) | **0** |
| `security/injection_scanner.py` | **0** |
| `security/rate_limiter.py` | **0** |
| `security/subprocess_sandbox.py` | **0** |
| `security/severity_policy.py` | **0** |

`injection_scanner` is notable: the system ingests untrusted content (screen OCR,
browser page text, web search results, file contents), and a prompt-injection
scanner exists and is never invoked.

### 4.5 Error handling and observability

- **761** `except Exception` sites in `src/`
- **98** of them swallow silently with a bare `pass`
- **92 of 616** source files acquire a logger

**[FACT]** The event bus does not cover the primary product path.
`local_actions.py` and `pc_control.py` publish no events; telemetry and traces
observe the agent/tool platform layer only. The Windows action layer has its own
separate audit (`LocalActionApprovalStore`, plus a JSONL attempt log).

### 4.6 Systemic wall-clock duration measurement

**[FACT]** `time.time()` is used to measure elapsed durations in
`telemetry/instrumented_engine.py` (×2), `telemetry/wrapper.py`,
`tools/_stubs.py`, and `agent/execution/command_catalog.py` (×3). On Windows this
quantizes every measurement to ~15.6 ms, so any operation faster than that
records as exactly `0.0`. Fixed in `agents/executor.py` only (commit
`1584e69b`); the rest remain.

---

## 5. Duplicate subsystems and models

**[FACT]** Parallel implementations of the same concern:

| Concern | Implementations |
|---------|-----------------|
| Agent framework | `agents/` (registry-based, used by serve/sdk) **and** `agent/` ("Agent Runtime V1") |
| Domain contracts | `core/types.py` **and** `kernel/models.py` |
| Tool registry | `core/registry.py` **and** `kernel/interfaces.py` |
| Intent routing | `router/intent_router.py` **and** `jarvis/intent_router.py` |
| Memory store | `memory/store.py` **and** `memory_context.py` |
| Model runtime | `runtime/` (ModelRuntime/BackendAdapter) **and** `engine/` (InferenceEngine) |
| Planning/execution | `planner/`, `agent/execution/`, `workflow/`, `skills/` |
| Network probe | `engine/_network.py` **and** `runtime/utils.py` (`local_port_is_open`, byte-identical) |

**[FACT]** `engine/` is now a thin compatibility shim over `runtime/`: 342 lines
across 6 files, mostly re-exports and aliases, wrapping the 8-module `runtime/`
package that does the actual work.

---

## 6. Routing and orchestration paths

**[FACT]** The shape of the primary chat path, in order:

```
user text
  → _normalise()                       (filler stripping, verb mapping)
  → _is_dangerous()                    (regex denylist, fail-safe)
  → handler chain (14 probes)          (each may claim the turn)
      desktop → local_actions → file → scheduler → browser → …
  → intent router (optional)
  → LLM fallback                       (agent + tools, or direct engine stream)
```

**[FACT]** Safety ordering is sound: the danger check runs *before* routing, and
`_parse_safe_action` is an allowlist parser, so the denylist is defence in depth
over an allowlist rather than the only barrier.

**[FACT]** Model output is never fed to `handle_local_action`. Every call site
passes user input (`effective_user_input`, `effective_user_text`,
`command_text`). The README's "Grandpa never treats model output as permission"
holds for this path.

**[RECOMMENDATION]** The five chains should collapse to one dispatcher with a
registry of handlers, so capability is uniform across entry points and the
duplicated bookkeeping disappears. This is the single highest-value structural
change available, and it is explicitly **not** done here.

---

## 7. AI / LLM architecture

**[FACT]** Layering, bottom-up:

```
grandpa.runtime          ModelRuntime (ABC) → BackendAdapter
                         ├── OllamaBackendAdapter   (23 KB, the real path)
                         └── NativeBackendAdapter   (llama-cpp, optional)
grandpa.engine           InferenceEngine(ModelRuntime) — compatibility shim
                         + discovery, exception aliases
grandpa.security         GuardrailsEngine wraps the engine (scanners)
grandpa.telemetry        InstrumentedEngine wraps that (metrics)
consumers                cli/serve, cli/chat, cli/ask, sdk, agents
```

**[FACT]** Ollama is the only engine registered by default. `native` registers
lazily on request. There is no OpenAI-compatible *client*; the OpenAI
compatibility is server-side (Grandpa exposes `/v1/chat/completions`).

**[FACT]** Verified working end to end during the audit: a live
`/v1/chat/completions` call against `grandpa-mini:latest` returned in ~11 s with
`prompt_tokens: 740` for a one-line user message — the system prompt is ~740
tokens on every call.

**[OPEN]** Is the `native` (llama-cpp) backend a supported product path or an
experiment? It has zero direct test coverage and `llama-cpp-python` is not
installed in the reference environment.

---

## 8. Memory architecture

**[FACT]** Four independent persistence mechanisms:

| System | Location | Owner |
|--------|----------|-------|
| Personal facts + activity | `~/.grandpa/personal_memory.db` | `memory_context.py` |
| Structured Memory V1 | `~/.grandpa/memory.db` (`memories` table) | `memory/store.py` |
| Tool storage backend | `~/.grandpa/memory.db` (`documents` table) | `tools/storage/sqlite.py` |
| File-based memory | `~/.grandpa/MEMORY.md` | `MemoryFilesConfig` |

**[FACT]** Two different schemas share the file `memory.db` — a `memories` table
and a `documents` table, written by different owners. SQLite tolerates this, so
it is a design smell rather than a live fault.

**[FACT]** `memory_context.py` semantic search is **not** learned embeddings. It
is a hashed bag-of-words plus character-trigram vector (FNV-1a, 128 dims) with
cosine similarity. The constant `SEMANTIC_MODEL = "grandpa-local-semantic-v1"`
overstates this. Real vector search requires the optional `memory-faiss` extra.

**[RECOMMENDATION]** Pick one owner per concern and give each store its own file.
Rename the pseudo-embedding constant so it does not imply a model.

---

## 9. Voice architecture

**[FACT]** Components:

```
microphone.py  → vad.py → speech/faster_whisper.py (STT)
                              ↓
              routing (5 separate paths, §4.1)
                              ↓
speech_output.py → grandpa_voice_tts (F5, out-of-process) → kokoro → pyttsx3
presenter.py     → terminal UI + animations
```

**[FACT]** TTS is a cascade with fallback: F5 cloned voice via a local HTTP
service on `127.0.0.1:8765`, falling back to Kokoro, falling back to Windows
SAPI (`pyttsx3`). The heavy ML stack lives in a separate `voice_runtime/`
interpreter, deliberately kept out of the main environment.

**[FACT]** The Whisper decoding policy is deliberately tuned for this product:
greedy decoding (`beam_size=1`), a domain vocabulary `initial_prompt` biasing
recognition toward the application names Grandpa controls, and slightly
permissive speech gating.

**[FACT]** Voice has five routing paths — `voice/assistant.py`,
`voice/operator.py`, `voice/session.py`, `voice/cli_session.py`, `voice/loop.py`
— the densest duplication in the codebase.

---

## 10. Desktop-control architecture

**[FACT]** Two layers with different trust models.

**Natural language** (`local_actions.py`, 2,203 LOC): regex allowlist parser,
`_DANGEROUS_PATTERNS` denylist checked first, permission classification per
action kind, approval store with audit.

**Structured API** (`pc_control.py`, 1,542 LOC): risk-tiered action catalogue.

**[FACT]** Current risk tiers:

| Tier | Count | Behaviour |
|------|-------|-----------|
| LOW | 36 | Executes immediately |
| MEDIUM | 23 | Executes immediately *unless* in the approval set |
| HIGH | 5 | Requires approval |
| BLOCKED | 6 | Refused outright |
| **APPROVAL_REQUIRED** (overlay) | **6** | Forces approval regardless of tier |

**[FACT]** Unknown actions classify as BLOCKED — the catalogue is default-deny.

**[FACT]** Defence in depth verified: protected-path checks resolve `..` before
comparison; a protected-window guard blocks synthetic input when the foreground
window looks sensitive; command-surface hotkeys (`Win+R`, `Win+X`,
`Ctrl+Shift+Esc`, `Ctrl+Alt+Del`) are blocked at staging *and* re-checked at
actuation, where `pyautogui.hotkey` is never reached.

**[FACT]** Protected paths are a narrow denylist: `C:\Windows`,
`C:\Program Files(*)`, `$Recycle.Bin`, `System Volume Information`, `.ssh`, and
browser profile directories. Not covered: `%APPDATA%\Roaming` generally, `.aws`,
`.gnupg`, the Windows Startup folder, `ProgramData`, and `~/.grandpa` itself.

**[RECOMMENDATION]** Add the Startup folder and `~/.grandpa` to protected paths.
`file_create` is LOW risk and unattended, so writing to Startup is a persistence
primitive.

---

## 11. API / server architecture

**[FACT]** FastAPI app assembled in `server/app.py` from `routes.py`,
`api_routes.py`, and `upload_router.py`.

| Property | Value |
|----------|-------|
| Total routes | **179** |
| Authenticated | **173** |
| Unauthenticated | **6** — `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` |
| Default bind | `127.0.0.1` |
| Default CORS origins | `[]` (browsers blocked) |
| Auth | Bearer token, generated on first run, stored at `[server.auth] api_key` |

**[FACT]** Auth enforcement verified live against a running server: every `/v1/`
and `/api/` route returns 401 without a key and 200 with it. No bypass via case,
double-slash, dot-segment, traversal, or percent-encoding variants. The key does
not appear in 401 bodies, `/openapi.json`, response bodies, or the server log
during normal operation.

**[FACT]** Approval requires an out-of-band code printed to the operator console,
never returned in the HTTP response. Codes are unique per action; a code from one
action cannot approve another; replay after execution returns
`already_completed`; a wrong code does not consume the pending action.

**[FACT]** `/metrics` exposes aggregate counters only (request count, token
count, average latency) — no prompts, content, or keys.

---

## 12. Rust subsystem status

**[FACT]** 17 crates, 124 files, 27,035 lines under `rust/`.

**[FACT]** `grandpa_rust` is **not installed** in the reference environment and
is not built by default. `grandpa doctor` reports "Rust extension is not required
by the active runtime."

**[FACT]** 16 Python modules reference `_rust_bridge`, each wrapping the call in
`try/except ImportError` with a Python fallback. The bridge's docstring claims
"The Rust backend is mandatory — if it cannot be imported, a hard ImportError is
raised", and `RUST_AVAILABLE: bool = True` is a hardcoded constant. Both are
false; `RUST_AVAILABLE` has no consumers.

**[FACT]** The `rust` CI job fails on Clippy. **Not reproducible locally** — this
machine has no MSVC linker (`link.exe not found`), so the Rust workspace cannot
be built here at all.

**[OPEN]** Is the Rust workspace an active acceleration path, a migration target,
or abandoned? 27 k lines that nothing loads is the largest single unresolved
question in the repository. **This needs a decision before target-architecture
work.**

---

## 13. Security status

### Closed in this work

**[FACT]** API unauthenticated by default → authenticated by default, key
generated on first run. Synthetic desktop input executing unattended → approval
required, with command-surface hotkeys blocked at two layers. Approval by
`action_id` alone → out-of-band code required. Self-update installing an
unrelated PyPI package → refused. Ten inert security config keys → removed with
load-time warnings.

### Genuinely sound

**[FACT]** No hardcoded secrets in the working tree or in staged content. SSRF
checks are unconditional in `http_request`, `browser`, and `web_search`. Screen
redaction (passwords, tokens, OTPs, card numbers, private keys) is wired into
`screen/service.py`, `vision/`, and `automation/locator.py`. Telemetry has no
network egress — it is genuinely local-only. Logging installs a
credential-stripping formatter. `check_bind_safety` refuses non-loopback binds
without a key, including under `--no-auth`.

### Remaining

**[FACT]**

| Issue | Severity | Note |
|-------|----------|------|
| 4 FastAPI docs routes unauthenticated | Low | Lets an unauthenticated local process enumerate the full API surface. Pre-existing FastAPI default. |
| Approval codes retained in DB after completion | Low | Not exploitable — the row is no longer `pending`. Unnecessary retention. |
| Approval codes reach `~/.grandpa/cli.log` under `--verbose` | Low | The log *is* the intended out-of-band channel; console-only otherwise. |
| `CredentialStripper` has no `gp_sk_` pattern | Low | `Authorization: Bearer <key>` *is* redacted — the realistic vector. |
| Browser page text not redacted | Medium | `screen`/`vision` redact; `browser_intelligence` does not. |
| `injection_scanner` never invoked | Medium | Untrusted content is ingested; the scanner exists unused. |
| Capability RBAC open by default | Medium | `CapabilitiesConfig.enabled = False`; `_check_python` fails open when no grant matches. |
| `config.toml` holds the API key in plaintext | Info | Consistent with `~/.grandpa` already holding OAuth tokens and `.vault_key`. |

---

## 14. CI/CD status

**[FACT]**

| Property | Value |
|----------|-------|
| Workflows | `ci.yml`, `docs.yml`, `autotag.yml`, `pypi-publish.yml`, `take-assign.yml` |
| CI jobs | `lint`, `test`, `rust` |
| Runners | **3 × `ubuntu-latest`, 0 × Windows** |
| Test selection | 18 hand-listed files (of 381) |
| Coverage gate | `--cov-fail-under=20` |
| Remote status on `main` | **CI: failure · Docs: failure · Auto-tag: failure** |

**[FACT]** Locally the `lint` job passes and the `test` job's selection passes
with exit 0. The `rust` job will still fail. Nothing is pushed, so remote status
still reflects the pre-fix tree.

**[FACT]** The product is a Windows desktop assistant and CI has no Windows
runner. Windows automation, `pywin32`, SAPI TTS, and window control are never
exercised in CI.

**[FACT]** `mkdocs.yml` points at the wrong repository: `site_url:
https://grandpa.github.io/grandpa/` and `repo_url: https://github.com/grandpa/grandpa`.
Neither exists. 29 of 51 doc pages are absent from `nav:`, and the generated
API-reference pages are produced but never linked.

**[RECOMMENDATION]** Add a Windows runner and broaden the test selection *after*
it exists — broadening on Linux alone would surface platform failures, not real
regressions.

---

## 15. Known technical debt

**[FACT]**

1. Five divergent routing chains (§4.1)
2. 29 duplicated class names (§4.2)
3. `kernel/` canonical layer with one consumer (§4.3)
4. Five dead subsystems including two security controls (§4.4)
5. 761 `except Exception`, 98 silent, 92/616 files logging (§4.5)
6. Wall-clock duration measurement in 4 remaining modules (§4.6)
7. 207.6 MB of vendored ffmpeg binaries — 91.5% of the repository
8. `grandpa_project_structure.txt` (7.2 MB) and `grandpa_tree.txt` (3.5 MB)
   generated dumps committed at the repo root
9. `.dockerignore` present with no Dockerfile
10. `CHANGELOG.md` for the current version (1.0.1) describes features that do not
    exist: ACE optimizer, DSPy, GEPA, an analytics module, `docs/learning/ace.md`,
    `docs/telemetry.md`, `install.sh`
11. Docs describe an intended architecture, not the actual one —
    `architecture/overview.md` claims "Voice and CLI input share one
    intent-routing and safety path", which §4.1 disproves
12. `repo-structure.md` lists a `safety` package that does not exist and omits
    `voice_runtime/`
13. Naming inconsistency: `Grandpa_CONFIG`, `Grandpa_API_KEY` (deprecated alias)
    against `GRANDPA_*` elsewhere — residue of the OpenJarvis → Odin → Grandpa
    renames
14. 18 stale remote branches fully merged into `main`

---

## 16. P2 / P3 remaining issues

**[FACT]** Nothing below is a correctness or security blocker.

**P2**

- Browser page text not redacted (§13)
- `injection_scanner` unwired (§13)
- Capability RBAC open by default (§13)
- Wall-clock durations in telemetry (§4.6)
- FastAPI docs routes unauthenticated (§13)
- No Windows CI runner (§14)
- `mkdocs.yml` wrong repo URLs; 29 orphaned doc pages (§14)
- `CHANGELOG.md` describes removed features (§15)

**P3**

- Repository weight — ffmpeg binaries and generated dumps (§15)
- Approval code retention and `--verbose` logging (§13)
- `CredentialStripper` missing `gp_sk_` pattern (§13)
- `RUST_AVAILABLE` hardcoded `True` with no consumers (§12)
- Stale branch pruning (§15)
- `.dockerignore` without a Dockerfile (§15)
- `SEMANTIC_MODEL` constant overstates the hashing embedding (§8)

---

## 17. Preserve

**[RECOMMENDATION]** These are working, well-shaped, and should survive any
restructuring. Do not replace them merely to fit a new architecture.

| Component | Why |
|-----------|-----|
| `pc_control.py` risk tiers + approval store | Default-deny, audited, migration-aware, now with out-of-band approval. The safety model is correct. |
| `local_actions.py` allowlist parser | Regex allowlist with a denylist in front of it. Right ordering, fail-safe. |
| `screen/redaction.py` | Real, tested, wired into three capture paths. |
| `core/config.py` | Typed dataclasses, backward-compat shims, corruption recovery with atomic write and backup. Genuinely good. |
| `core/registry.py`, `core/events.py` | Clean, isolated, typed. The shared kernel that actually works. |
| `runtime/` adapters | The real inference path. Reasoning-tag stripping, low-memory detection, structured errors. |
| `security/` scanners, `ssrf`, `file_policy`, `audit` | Used, tested, effective. |
| `speech/` cascade + `voice_runtime/` separation | Keeping the ML stack out-of-process is the right call. |
| `cli/_animation.py` | New, single correct lifecycle for both animations. |
| The test suite | 4,455 passing tests is a real asset. Refactor against it, not around it. |

---

## 18. Consolidation candidates

**[RECOMMENDATION]** Ordered by value-to-risk. None of this is agreed yet.

| Candidate | Action | Risk |
|-----------|--------|------|
| 5 routing chains → 1 dispatcher | Highest value. Registry of handlers; uniform capability across entry points. | High — touches every entry point |
| `agent/` + `agents/` | Pick one framework. Name collisions make both confusing. | High |
| `kernel/` | Either adopt as canonical (migrate `core/types` onto it) or delete. One consumer today. | Medium |
| `engine/` → `runtime/` | `engine/` is already a 342-line shim. Fold it in, delete `_network.py` (byte-identical duplicate). | **Low — good first move** |
| Voice's 5 paths | Collapse to one session model. | Medium |
| `memory_context.py` + `memory/` | One owner per concern; separate DB files. | Medium |
| `a2a/` | Delete or document as experimental. Zero consumers. | **Low** |
| Dead security modules | Wire `injection_scanner` in, or remove all four. | Low |
| `router/` + `jarvis/` intent routers | Merge. | Medium |
| ffmpeg binaries | Move to a download-on-setup step. Reclaims 91.5% of the repo. | Low |

---

## 19. Open questions

**[OPEN]** These need human decisions and block confident target-architecture
work.

1. **What is Grandpa?** The README describes a local Windows assistant.
   `pyproject.toml` describes "a personal AI assistant backend with composable
   intelligence primitives". The codebase contains both: a Windows automation
   product *and* an agent/tool/MCP/workflow platform SDK. Which is the product
   and which is scaffolding?
2. **Is the Rust workspace alive?** 27 k lines, not built, not loaded, CI red.
   Adopt, archive, or delete?
3. **Is `native` (llama-cpp) a supported path** or an experiment?
4. **Is `kernel/` the intended target architecture** that was never migrated to,
   or an abandoned direction?
5. **Should MCP and A2A be product features?** MCP is implemented and wired into
   `SystemBuilder` but has no documentation and no CLI command. A2A has no
   consumers at all. The README says there is no third-party plugin runtime.
6. **Distribution:** the PyPI name is taken. Rename, scope
   (`@trhariharasudhan/grandpa`), or stay git-only?
7. **Does `GRANDPA_RUNTIME_DIR` mean local artifacts should live under
   `~/.grandpa/runtime`?** If so the root `runtime/` ignore becomes unnecessary.
8. **Is `security.profile` meant to gate more than `mode` and bind host?** After
   removing the inert keys, profiles set very little.

---

## 20. Reproducing this baseline

**[FACT]** To verify every claim above:

```bash
git rev-parse HEAD          # 1584e69b8a189ff74f39e44c6710774ca1165817
git status --porcelain      # empty — clean tree
git log --oneline a031346a..HEAD   # 12 commits
```

```bash
uv sync --extra dev --extra server --extra voice --extra screen
uv run pytest                       # 4455 passed, 0 failed, exit 0
uv run ruff check src/ tests/       # All checks passed
uv run ruff format --check src/ tests/
```

**[FACT]** Reference environment for the measurements in this document: Windows
11, Python 3.11.14, uv 0.10.6, Ollama 0.32.15 (running, 14 local models),
cargo 1.96.0. No MSVC linker, so Rust could not be built or verified.

**[OPEN]** Timings and hardware-dependent results will differ elsewhere. The full
suite took 17 m 30 s here. Behaviour on Linux is unverified for the Windows
automation paths.

---

*Baseline captured at `1584e69b`, working tree clean, 12 commits ahead of
`origin/main`, nothing pushed.*
