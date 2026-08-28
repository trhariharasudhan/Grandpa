# Grandpa — Architecture Gaps

**Status:** Analysis. No gap here has been closed.
**Date:** 2026-08-26

This document is the delta between `CURRENT_ARCHITECTURE.md` and
`TARGET_ARCHITECTURE.md`. Each gap states what exists, what should exist, what
it costs, and what it blocks.

Tag legend is in `CURRENT_ARCHITECTURE.md`.

**Severity scale**

| | |
|---|---|
| **G0** | Blocks correctness or safety. Fix before anything else. |
| **G1** | Structural — causes recurring, compounding defects. |
| **G2** | Coherence — misleads readers, wastes effort, no direct defect. |
| **G3** | Hygiene. |

---

## Gap index

| ID | Gap | Severity | Principle violated | Blocks |
|---|---|:--:|---|---|
| GAP-01 | Baseline is split across two branches; `main` does not import | **G0** | P9 | Everything |
| GAP-02 | No dispatcher — six divergent entry surfaces | **G1** | P2 | Feature parity |
| GAP-03 | Two disjoint policy models | **G1** | P3 | Consistent safety |
| GAP-04 | No redaction on any browser path | **G0** | P4 | — |
| GAP-05 | Injection scanning never runs | **G0** | P4 | — |
| GAP-06 | Capability RBAC fails open | **G0** | P3 | — |
| GAP-07 | No Windows CI — the product's core is unverified | **G0** | P10 | GAP-02, 03, 12, 13 |
| GAP-08 | Suite does not terminate; exits 127 | **G0** | P10 | GAP-07 |
| GAP-09 | Two observability planes that do not meet | **G1** | P7 | Incident analysis |
| GAP-10 | 23 package-level import cycles | **G1** | P5 | Safe refactoring |
| GAP-11 | 31 duplicate class names / 3 domain models | **G1** | P6 | GAP-02, 03 |
| GAP-12 | Five-to-seven memory systems; two schemas share one file | **G1** | P6 | — |
| GAP-13 | Five voice routing paths | **G1** | P6 | GAP-07 |
| GAP-14 | Four browser packages | **G1** | P6 | — |
| GAP-15 | Two agent frameworks, four planning systems | **G1** | P6 | — |
| GAP-16 | `engine/` is a shim with 11× the fan-in of `runtime/` | **G2** | P6 | GAP-01 |
| GAP-17 | ~31,600 LOC of inherited dead code in an undecided state | **G2** | P9 | AD-001, AD-002 |
| GAP-18 | Config schema describes the platform, not the product | **G2** | P8 | — |
| GAP-19 | Nine inert security config keys | **G2** | P8, P9 | — |
| GAP-20 | Dishonest contracts (`RUST_AVAILABLE`, `SEMANTIC_MODEL`, `kernel/`) | **G2** | P9 | — |
| GAP-21 | Six god-modules >1,200 LOC at package root | **G2** | P6 | — |
| GAP-22 | No end-to-end tests of any dispatch chain | **G1** | P10 | GAP-02 |
| GAP-23 | Marker taxonomy declared but unused | **G2** | P10 | GAP-08 |
| GAP-24 | Docs contradict code in at least 6 places | **G2** | P9 | — |
| GAP-25 | 758 `except Exception`, ~100 bare `pass` | **G3** | — | — |
| GAP-26 | Repository bloat: 207 MB vendored ffmpeg, 10.7 MB tree dumps | **G3** | — | — |

---

## G0 — Blocks correctness or safety

### GAP-01 — The baseline is split across two branches; `main` does not import

**Current.** `main` @ `a031346a` does not track `src/grandpa/runtime/` — 8
files, 1,364 LOC, the entire model-runtime layer. `.gitignore:120` is `runtime/`
with no leading slash, so git matches any directory named `runtime` at any
depth. A clean clone cannot import `grandpa.runtime`, `grandpa.security`, or
`grandpa.engine`; 56 of 349 test files fail to collect. The fix exists on
`claude/grandpa-codebase-audit-bf609c` (73 files, +4,400/−925) and is **unmerged**.

**Target.** One branch. `main` imports from a clean clone. `ARCHITECTURE_BASELINE.md`
exists or is written.

**Cost.** A merge, plus conflict resolution against 73 files.

**Blocks.** Everything. GAP-16 is meaningless while `runtime/` is untracked; any
CI work is meaningless while the package does not install.

**[RECOMMENDATION]** Merge first. Re-cut the architecture branch from the merge
commit. Verify with a fresh `git clone` → `uv sync` → `grandpa doctor` →
`pytest --co`.

---

### GAP-04 — No redaction on any browser path

**Current.** `redact_screen_text` (7 pattern classes: passwords, tokens, OTPs,
card numbers, private keys, authorization headers, and one more) is applied in
`screen/`, `vision/graph.py:63`, and `automation/locator.py`. It is applied in
**none** of `browser/`, `browser_intelligence/`, `browser_awareness/`, or
`browser_control.py`.

**Why this is G0.** Browser page text is the **largest volume of untrusted
content the assistant ingests**. It reaches logs and reaches LLM prompts. A
password field rendered as text, an API key in a dashboard, a session token in a
URL — all pass through unredacted. The README explicitly promises redaction of
"likely passwords, tokens, OTPs, payment-card numbers, private keys, and
authorization data".

**Target.** Redaction at every extraction boundary in `browser/read`.

**Cost.** Low — the function exists and the call pattern is established in three
other packages. This is a handful of call sites.

**[RECOMMENDATION]** Land this **independently of and before** the browser
consolidation (GAP-14). It is a security fix, not a refactor, and coupling it to
a four-package merge delays it for no reason.

---

### GAP-05 — Injection scanning has never run on anything

**Current.** `security/injection_scanner.py` (167 LOC) has exactly one
reference: a JSON converter in `_rust_bridge.py`. It is not called at any
ingestion point.

**Why this is G0.** The assistant ingests screen OCR, browser page text,
web-search results, file contents, clipboard contents, and MCP tool results —
none of it scanned. The blast radius is genuinely limited by P1 (model output
never becomes an action), which is why this is not catastrophic. But the control
was written, and it does nothing.

**Target.** Scanning at every untrusted-ingress boundary, in `policy/`.

**Cost.** Medium — wiring it changes runtime behaviour (**Q-6**: what happens
when something is flagged?).

---

### GAP-06 — Capability RBAC fails open

**Current.** `CapabilitiesConfig.enabled = False` by default. `setup_security()`
constructs `CapabilityPolicy()` with `default_deny=False`. And
`capabilities.py:_check_python` returns `not self._default_deny` when a policy
exists but no grant matches — so **a partially-specified policy grants
everything**.

**Why this is G0.** This is the failure mode where an operator writes a policy,
believes it is enforcing, and it is enforcing the opposite. It is worse than
having no policy system.

**Target.** Fail closed. A policy that exists and does not grant, denies.

**Cost.** Low to change; **medium to land** — it may break existing partial
policies, which is exactly the point.

---

### GAP-07 — No Windows CI; the product's core is entirely unverified

**Current.** CI runs `ubuntu-latest` only. pywin32, UIA, SAPI TTS, pyautogui,
window control, and the entire `desktop/` + `automation/` + `voice/` stack are
**never** exercised in CI. CI selects 18 of 349 test files and gates at
`--cov-fail-under=20`. On `main` the `test` job additionally references three
files that do not exist, so pytest exits 4 before running anything.

**Why this is G0.** The product is Windows-only. Everything CI validates is the
Linux-portable subset — i.e. the inherited platform, not the product.

**Target.** A `windows-latest` job running the assistant suites, green.

**Cost.** Medium — a new job, plus fixing whatever it surfaces on first run.

**Blocks.** GAP-02, GAP-03, GAP-12, GAP-13. **Refactoring the Windows layer
without a Windows runner is unverifiable by construction.** This is the single
most important sequencing constraint in the migration plan.

---

### GAP-08 — The test suite does not terminate, and exits 127 when it does

**Current.** Two tests hang forever:
`tests/cli/test_voice_operator_cmd.py::test_voice_operator_command_typed_quit`
and `::test_voice_operator_command_typed_fallback_action`. Both invoke the real
`voice-operator` command without patching `run_voice_operator_loop`, so
`SpeechOutputEngine(enabled=True)` and microphone detection run against real
hardware. `conftest.py` marks both `@pytest.mark.core`. With them included,
`pytest` never returns. Without them, the suite crashes at interpreter shutdown:
`Fatal Python error: _enter_buffered_busy ... possibly due to daemon threads`,
**exit 127**.

**Why this is G0.** The documented `pytest` command cannot complete, and exit
127 makes CI exit codes unreliable — a green build could be masking a crash.

**Target.** Suite terminates; exit 0 or 1.

**Cost.** Low for the immediate fix (`pytest-timeout` + apply the declared-but-
unused `microphone` marker); medium to fix the daemon-thread leak properly.

---

## G1 — Structural

### GAP-02 — No dispatcher; six divergent entry surfaces

**Current.** Six independently maintained handler chains: `chat` (28 handlers),
`ask` (5), `routes.py` (9), `api_routes.py` (3), `voice/assistant.py` (15),
`voice/operator.py` (11). The capability matrix in `CURRENT_ARCHITECTURE.md` §5
shows 10+ handlers present in some surfaces and absent from others. The four
post-response side-effect calls are duplicated ~15× in `chat_cmd.py`;
`record_assistant_outcome` appears 17 times.

**Consequence.** "Check my email" works in `chat`, `voice/assistant`, and
`voice-operator`; it does not work in `ask` or over HTTP. Every new handler
requires six correct edits, and there is no mechanism that notices when one is
missed. `docs/architecture/overview.md` claims "Voice and CLI input share one
intent-routing and safety path" — they do not.

**Target.** One `IntentDispatcher` (`TARGET_ARCHITECTURE.md` §4.1). Surfaces
become transport plus presentation.

**Cost.** **The largest refactor in the plan.** `chat_cmd.py` alone has 43 test
files behind it. Three of six surfaces are untestable in current CI.

**Gate.** GAP-07 for the voice and desktop surfaces. `ask` and HTTP can go
earlier.

---

### GAP-03 — Two disjoint policy models

**Current.**

| | NL path | Structured API path |
|---|---|---|
| Entry | `local_actions.py` | `pc_control.py` → `desktop/kernel/risk.py` |
| Vocabulary | `{allowed, requires_confirmation, blocked}` | `{LOW, MEDIUM, HIGH, BLOCKED}` |
| Pre-filter | `_is_dangerous()`, 37 regex | — |
| Parse | allowlist parsers per domain | typed payload |
| Approval store | `local_action_approvals.db` | `pc_control_approvals.db` |
| Extra guard | — | `_preflight_guard()` (protected paths, protected active window) |

They share no code. A rule added to one does not exist in the other.

**Target.** One `PolicyEngine`, one vocabulary, one approval store
(`TARGET_ARCHITECTURE.md` §4.2).

**[RECOMMENDATION]** Adopt the post-remediation design rather than inventing
one. The stabilization branch already introduces `APPROVAL_REQUIRED_ACTIONS` as
an axis **orthogonal** to the risk tier, with the right rationale stated in the
source: synthetic input is recoverable (so MEDIUM is the correct blast-radius
tier) but reaches arbitrary code execution (so approval is required regardless
of tier). Generalise that; do not re-derive it.

**Cost.** High. Highest-consequence area of the product. **Gate: GAP-07.**

---

### GAP-09 — Two observability planes that do not meet

**Current.** The platform publishes to `core.events.EventBus` (30+ `EventType`
members) and feeds `telemetry/` and `traces/`. The Windows layer has an entirely
separate audit trail (`pc_control` sqlite + jsonl, `local_action_approvals.db`,
`security/audit.py`, `desktop/kernel/audits.py`) and publishes **zero** events.
`EventType` has no desktop, window, screen, or voice member.

**Consequence.** No single ordered timeline exists for "user said X → policy
allowed → keyboard typed → window changed → audited". Incident analysis requires
correlating two systems by timestamp.

**Target.** One bus; audit becomes a subscriber.

**Cost.** **Low — purely additive.** This is the best structural-value-per-risk
item in the plan and should be scheduled early.

---

### GAP-10 — 23 package-level import cycles

**Current.** The structurally significant ones:

| Cycle | Weight |
|---|---|
| `pc_control` ↔ `desktop` | 27 / 16 |
| `cli` ↔ `voice` | 18 / 7 |
| `memory_context` ↔ `memory` | 10 / 1 |
| `files` ↔ `kernel` | 2 / 16 |
| `core` ↔ `tools` / `security` / `engine` / `agents` | 1 each |

Plus 14 lighter ones. `docs/architecture/domain-architecture.md` states the
intended layering ("Interfaces call routers; routers create typed requests;
safety evaluates those requests; executors call narrow adapters") and the first
half of that rule does not hold.

**Target.** Zero, CI-enforced (rules D1–D8).

**Cost.** The four `core` back-edges are single edges — cheap and worth doing
immediately. `pc_control` ↔ `desktop` is the expensive one and is entangled with
GAP-03.

---

### GAP-11 — 31 duplicate class names; three competing domain models

**Current.** 31 of 895 class names are defined more than once. Grouped:

- **Three domain models:** `core/types.py` · `kernel/models.py` ·
  `planner/models.py` share `ToolResult`, `ToolRegistry`, `ToolExecutor`,
  `RiskLevel`, `ExecutionPlan`, `ConfirmationRequest`, `VerificationResult`.
- **Two agent frameworks:** `AgentExecutor`, `AgentContext`, `AgentResult`,
  `AgentGoal`, `AgentRuntime`.
- **Three planners:** `StepStatus`, `StepVerifier`, `ValidationResult`,
  `PlanStep`, `WorkflowResult` (×3).
- **Flat vs package** (the rebrand fault line): `MemoryStore`, `SchedulerStore`,
  `WindowInfo`, `MonitorInfo`, `OcrResult`, `AutomationResult`.
- **Storage owners:** `KnowledgeStore`, `OllamaEmbedder`, `SessionStore`.
- **Security:** `ScanResult`, `SecurityContext`, and `SecurityBlockError` —
  duplicated *inside a single package*.

Plus two unrelated packages both named "kernel" (`kernel/` and `desktop/kernel/`).

**Consequence.** `from grandpa... import ToolResult` has two possible meanings.
This is the mechanism by which GAP-02 and GAP-03 stay unfixable: you cannot
unify two dispatch paths that speak different types.

**Target.** Zero duplicated domain type names.

**Cost.** Medium, and it is a prerequisite for GAP-02 and GAP-03 rather than a
parallel task.

---

### GAP-12 — Five-to-seven memory systems; two schemas share one file

**Current.**

| System | Location | Storage |
|---|---|---|
| Personal memory | `memory_context.py` (45 importers) | `personal_memory.db` |
| Memory System V1 | `memory/` | `memory.db` → table `memories` |
| RAG documents | `tools/storage/sqlite.py` | **`memory.db` → table `documents`** |
| Memory files | `MemoryFilesConfig` | `~/.grandpa/MEMORY.md` |
| Sessions / project | `sessions/`, `memory/project_memory.py` | `sessions.db`, `projects.json` |
| Knowledge | `knowledge/storage.py` | `knowledge.db` |
| Connectors RAG | `connectors/store.py` | (duplicate `KnowledgeStore`) |

Systems 2 and 3 write different schemas into **the same default file path** with
no owner. `memory_context` ↔ `memory` is a cycle. 29 distinct `.db` filenames
exist across the tree; per `AUDIT.md`, 7 are orphaned.

**Target.** One `MemoryFacade` over four named stores; `documents` moves to
`documents.db` (`TARGET_ARCHITECTURE.md` §4.3).

**Cost.** **Highest risk in the repository** — 45 importers plus live user data.
**Requires explicit approval** and a backup-first, idempotent, dry-runnable,
revertible migration.

**Blocked on** Q-5 (the 7 orphaned databases).

---

### GAP-13 — Five voice routing paths

**Current.** `voice/assistant.py` (15 handlers), `voice/operator.py` (1,613 LOC,
11 handlers), `voice/session.py`, `voice/cli_session.py`, `voice/loop.py`, plus
`jarvis/voice_input.py` as a sixth input path.

**Consequence.** A fix in one path does not reach the other four. Per
`AUDIT.md`, voice accounts for **9 of 13 test failures and both suite hangs**.
That failure distribution is the direct signature of this gap.

**Target.** One `VoiceSession`; five modes as configuration.

**Cost.** High. Hardware-dependent. **Gate: GAP-07.**

---

### GAP-14 — Four browser packages with duplicated module names

**Current.** `browser_control.py` (1,264 LOC flat, 10 importers), `browser/` (7
modules), `browser_intelligence/` (12 modules, 2,247 LOC), `browser_awareness/`
(6 modules). `safety.py`, `parser.py`, and `automation.py` each appear in two of
them.

**Target.** One `browser/` package: `control` · `read` · `awareness`.

**Cost.** Medium. **Note:** GAP-04 (redaction) should land first and separately.

---

### GAP-15 — Two agent frameworks, four planning systems

**Current.** `agents/` (6,758 LOC) and `agent/` (5,846 LOC) with five colliding
type names. Four planning/execution systems: `kernel/` (3,272), `planner/`
(4,178), `agent/execution/`, `workflow/` (788), sharing `ExecutionPlan`,
`PlanStep`, `StepVerifier`, `ValidationResult`.

**Target.** `agents/` is the framework; `planner/` is the planner.

**Cost.** High — `agent/` backs 6 shipped CLI commands. Blocked partly on **Q-4**
(is `agent/development/` in scope?).

---

### GAP-22 — No end-to-end tests of any dispatch chain

**Current.** 4,234 test functions and **zero** that exercise
chat → handler chain → policy → action end-to-end. Handler chains are tested as
individual handlers, never as chains. This is precisely why GAP-02's capability
divergence was invisible until measured.

**Target.** At least one end-to-end test per surface, asserting the same
capability set.

**Cost.** Medium. **This should be built alongside `IntentDispatcher`, not
after** — the end-to-end test is what proves the dispatcher preserved behaviour.

---

## G2 — Coherence

### GAP-16 — `engine/` is a shim carrying 11× the fan-in of `runtime/`

**Current.** `engine/` is 342 LOC — `ollama.py` is 23 lines, `_network.py` is a
byte-identical copy of `runtime/utils.py::local_port_is_open`. It adds only
exception aliases. Yet `engine/` has 44 import edges across 11 packages while
`runtime/` has 7, almost all from `engine/`.

**Target.** Collapse into `runtime/`; `grandpa.engine` becomes a shim for one
release.

**Cost.** Low-medium, mechanical, test-covered. **Blocked on GAP-01.** Good
early work with a visible payoff.

---

### GAP-17 — ~31,600 LOC of inherited code in an undecided state

**Current.**

| Component | LOC | Status |
|---|---:|---|
| `rust/` | 27,035 | 0 runtime consumers; 18 lines changed in 3 months; CI-gating; absent from the wheel |
| `kernel/` | 3,272 | 1 consumer; docstring claims canonicity |
| `a2a/` | 460 | 0 consumers; live config section |
| 5 security modules | ~760 | 0 consumers; 2 have config keys shipping `True` |
| `templates/`, `daemon/` | 149 | 0 consumers |

**Why this is G2 and not G3.** It is not merely unused — it is *actively
misleading*. `_rust_bridge.py` says the Rust backend is mandatory. `kernel/`
says it holds canonical contracts. `rate_limit_enabled = True` says rate
limiting is on. A reader forms a false model of the system.

**Target.** Archived, with the decision recorded.

**Cost.** Low. **Blocked on** AD-001, AD-002, and **Q-3** (licensing).

---

### GAP-18 — The config schema describes the platform, not the product

**Current.** `GrandpaConfig`'s 26 sections cover engine, intelligence, learning,
tools, agent, server, telemetry, traces, security, scheduler, workflow,
sessions, **a2a**, operators, speech, tts, grandpa_voice, agent_manager,
memory_files, system_prompt, compression, skills, user, hardware. There is
**no** section for desktop, screen, automation, vision, or voice — the five
subsystems that constitute the product. Meanwhile a live `[voice]` section
exists in `~/.grandpa/config.toml` that the schema does not know about, read via
env and `voice/config.py`, alongside 74 `GRANDPA_VOICE_*` environment variables.

**Target.** A section per subsystem with runtime behaviour. `A2AConfig` removed.

**Cost.** **Low** — the validator already walks `dataclasses.fields()`
generically, so additions are cheap.

**KEEP unchanged:** the precedence model, the generic validator, the back-compat
shims, `GRANDPA_HOME`. Per `AUDIT.md` this is the best-engineered module in the
repository. **Extend, never restructure.**

---

### GAP-19 — Nine security config keys that nothing reads

**Current.** `rate_limit_enabled`, `rate_limit_rpm`, `enforce_tool_confirmation`,
`merkle_audit`, `ssrf_protection`, `local_engine_bypass`, `local_tool_bypass`,
`signing_key_path`, `vault_key_path` — all declared in `SecurityConfig` and read
nowhere outside `core/config.py`. `rate_limit_enabled` and
`enforce_tool_confirmation` ship as `True`.

**Why this matters more than it looks.** An operator reading the config concludes
protections are active that are not. That is worse than an absent key.

**Target.** Every key wired or deleted. **No third state.**

**Blocked on** Q-6 for `rate_limit_*` (wiring changes runtime behaviour).

---

### GAP-20 — Contracts that are not true

| Contract | Claim | Reality |
|---|---|---|
| `_rust_bridge.py` docstring | "The Rust backend is mandatory — no Python fallback" | Every one of 16 consumers falls back |
| `_rust_bridge.RUST_AVAILABLE` | `True`, hardcoded | `grandpa_rust` is not installed anywhere |
| `docs/architecture/domain-architecture.md` | "optional ... Python fallbacks remain the default" | Directly contradicts the above — both are in-repo |
| `memory_context.SEMANTIC_MODEL` | `"grandpa-local-semantic-v1"` | FNV-1a hashed bag-of-words + trigrams; no learned embedding |
| `kernel/__init__.py` docstring | "Canonical request execution contracts for Grandpa" | 1 consumer |
| `docs/architecture/overview.md` | "Voice and CLI input share one intent-routing and safety path" | Six divergent chains |
| `README.md:9` | "no ... third-party plugin runtime" | `mcp/` implements a full MCP server |
| `pyproject.toml` description | "personal AI assistant backend with composable intelligence primitives" | Describes the inherited platform, not the product |

**Target.** P9 — docstrings, constants, and behaviour agree.

**Cost.** Very low. **Highest signal-to-effort ratio of any gap in this
document.** These are text edits that stop actively misleading every future
reader, including future automated analysis.

---

### GAP-21 — Six god-modules over 1,200 LOC at package root

| Module | LOC | Concerns mixed |
|---|---:|---|
| `local_actions.py` | 2,203 | normalise + denylist + parse + classify + approve + execute |
| `cli/chat_cmd.py` | 2,156 | dispatch + slash commands + memory formatting + Rich rendering |
| `server/api_routes.py` | 2,256 | 26 sub-routers in one file |
| `voice/operator.py` | 1,613 | capture + route + 11 handlers + TTS |
| `pc_control.py` | 1,438 | risk tiers + approvals + preflight + execute |
| `windows_window_control.py` | 1,362 | window enumeration + control + info types |
| `memory_context.py` | 1,302 | facts + activity + conversation + embedding + retrieval |
| `browser_control.py` | 1,264 | drive + extract + parse |

**[FACT]** All except `api_routes.py` are **flat top-level modules**, not
packages — the direct signature of the rebrand: assistant code written alongside
the inherited packages rather than inside them.

**Target.** Each decomposes along the boundaries the target architecture already
defines. `api_routes.py` splits by its 26 existing sub-routers — the seams are
already there.

**Cost.** Medium-high individually; each is gated on the corresponding
structural gap.

---

### GAP-23 — Marker taxonomy declared but effectively unused

**Current.** `pyproject.toml` declares 12 markers: `amd`, `apple`, `browser`,
`core`, `environment`, `integration`, `live`, `microphone`, `nvidia`, `optional`,
`release`, `slow`. Only `live` is used as a decorator (twice). Everything else is
applied programmatically in `conftest.py` against hardcoded path lists, and
**anything unlisted defaults to `core`**.

**The `microphone` marker is declared and never applied.** That is exactly why
two microphone-dependent tests are classified `core` and hang forever (GAP-08).

**Target.** Decorator-driven markers. `pytest-timeout` with a default bound.

**Cost.** Low. Directly unblocks GAP-08.

---

### GAP-24 — Documentation contradicts code

Beyond GAP-20's contract table:

| Claim | Reality |
|---|---|
| README: `copy .env.example .env` | Nothing reads `.env`; `python-dotenv` is not a dependency |
| README: `ollama pull qwen2.5:3b` | `intelligence.default_model = "grandpa-mini:latest"` |
| `docs/development/repo-structure.md`: "`safety` ... own policy and audit" | No `src/grandpa/safety/` package exists |
| `CHANGELOG.md` 1.0.1: ACE optimizer, DSPy/GEPA policies, analytics module, `docs/learning/ace.md`, `install.sh` | None exist |
| `mkdocs.yml`: `site_url`/`repo_url` → `github.com/grandpa/grandpa` | Does not exist |
| 29 of 51 doc pages orphaned from `nav:`; 607 generated API pages never linked | Unreachable |
| `.dockerignore` | No Dockerfile anywhere |
| MCP, the SDK, and the agent runtime | Implemented, zero doc pages |

**Cost.** Low. Zero code risk. Can run fully in parallel with structural work.

---

## G3 — Hygiene

### GAP-25 — 758 `except Exception`, ~100 followed by bare `pass`

Across 226 files. Only 89 of 607 source files call `logging.getLogger`. Combined
with **zero** TODO/FIXME/HACK markers in the entire tree, this means known
limitations are recorded nowhere in the code — which is why the nine inert config
keys (GAP-19) were invisible to readers.

**[RECOMMENDATION]** Audit the ~100 silent `pass` sites in the packages on the
action path (`desktop/`, `automation/`, `pc_control`, `local_actions`) first. A
silently swallowed exception in a policy check is a security issue; elsewhere it
is style.

### GAP-26 — Repository bloat

`voice_runtime/tools/ffmpeg-7.1-lgpl-shared/` (extracted) **and** the original
62 MB zip, together 207.6 MB — **91.6% of the 221 MB pack**, for a 130k-LOC
project. Plus `grandpa_project_structure.txt` (7.2 MB) and `grandpa_tree.txt`
(3.5 MB), generated tree dumps committed at the repository root while
`.gitignore` explicitly ignores the equivalent `TREE_STRUCTURE.md`. Also: an
orphaned submodule gitlink at `voice_runtime/rvc/source` with no `.gitmodules`
(fixed on the stabilization branch), and 15 fully-merged stale branches.

**[RECOMMENDATION]** Delete the two tree dumps immediately — zero risk, 10.7 MB.
Treat the ffmpeg history purge as a separate decision with its own risk profile;
it is a history rewrite and is independent of the architecture.

---

## Gap dependency graph

```
GAP-01 (split baseline)
   │
   ├──► GAP-16 (collapse engine/)
   │
   └──► GAP-08 (suite terminates) ──► GAP-07 (Windows CI) ─┐
                    ▲                                       │
                 GAP-23 (markers)                           │
                                                            │
GAP-20 (honest contracts) ──► GAP-17 (archive dead code)    │
GAP-24 (docs vs code)      ─┘                               │
                                                            │
GAP-04 (browser redaction)  ─┐                              │
GAP-05 (injection scanning)  ├──► independent, land early   │
GAP-06 (RBAC fail-closed)   ─┘                              │
                                                            │
GAP-09 (one event bus) ──► independent, land early          │
                                                            │
GAP-11 (duplicate types) ──┐                                │
                           ├──► GAP-02 (dispatcher) ◄───────┤
GAP-22 (e2e tests) ────────┘         │                      │
                                     ├──► GAP-13 (voice) ◄──┤
GAP-10 (cycles) ──► GAP-03 (policy) ◄┘                  ◄───┘
                                     │
GAP-12 (memory) ── needs approval + Q-5
GAP-14 (browser consolidation) ── after GAP-04
GAP-15 (agents/planners) ── needs Q-4
GAP-21 (god modules) ── after the corresponding structural gap
```

**Reading of the graph:** three clusters can start immediately and in parallel —
the safety fixes (GAP-04/05/06), the honesty fixes (GAP-20/24), and the event
bus (GAP-09). Everything structural funnels through **GAP-07 (Windows CI)**,
which is itself gated on **GAP-01 (merge the baseline)**.

---

## Summary

| Severity | Count | Total effort shape |
|---|---:|---|
| **G0** | 6 | Small, mechanical, high-consequence. Days. |
| **G1** | 9 | Large, structural, mostly gated on Windows CI. Weeks. |
| **G2** | 9 | Mostly text and additive config. Days, parallelisable. |
| **G3** | 2 | Ongoing. |

**[RECOMMENDATION]** The two highest-value-per-hour items are **GAP-20**
(dishonest contracts — text edits that stop misleading every future reader) and
**GAP-09** (one event bus — purely additive, and it is what makes the Windows
layer debuggable at all). Neither is gated on anything. Both should be scheduled
before the structural work, not after it.
