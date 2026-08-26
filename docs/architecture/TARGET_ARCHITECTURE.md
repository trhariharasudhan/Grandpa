# Grandpa — Target Architecture

**Status:** Proposed. Nothing here has been implemented.
**Date:** 2026-08-26
**Supersedes:** the 2026-08-26 discovery draft. Revised for AD-019 (licensing
resolved), AD-020 (`agent/development/` retained), AD-021 (orphaned DBs), and
**AD-022** — which changes what the architecture must *guarantee*.

Tag legend is in `CURRENT_ARCHITECTURE.md`.

---

## 1. Derivation

The target follows from four ratifiable decisions, each argued from repository
evidence in `ARCHITECTURE_DECISIONS.md`:

| | |
|---|---|
| **AD-001** | Grandpa is a **Windows-first local AI assistant on a retained internal substrate** — including an autonomous software-development mode. |
| **AD-002** | The Rust workspace is inherited dead infrastructure → **archive out of tree**. |
| **AD-019** | The repository is a **hard fork of Apache-2.0 upstream** with attribution removed → **restore it**. |
| **AD-022** | Model output **can** reach the structured actuation funnel via agent-invocable skills. Safety rests on the **policy layer**, not on path absence. |

AD-022 is the one that reshapes the design. In the discovery draft, the policy
engine was a tidying exercise — two vocabularies merged into one. It is now the
**sole enforcement boundary** between a model-chosen `action_type` and
execution, and the architecture must treat it as such.

---

## 2. Complete current-state routing map

Established by tracing every call site. This is the thing the target replaces.

### 2.1 Six dispatch chains

```
┌────────────────────────────────────────────────────────────────────────────┐
│ CHAIN 1 — grandpa chat        cli/chat_cmd.py                              │
│ 12 slash handlers → 3 natural-intent handlers → core_ai_brain analysis →   │
│ ordered probe chain:                                                       │
│   :849  handle_executive_goal      :1835 handle_gmail_command              │
│   :858  handle_browser_command     :1854 handle_browser_awareness_command  │
│   :871  handle_project_command     :1875 handle_browser_command            │
│   :1736 handle_notes_command       :1897 handle_desktop_command            │
│   :1755 handle_downloads_command   :1918 handle_local_action        ◄ FUNNEL A
│   :1776 handle_web_search_command  :1937 handle_file_command              │
│   :1795 handle_memory_command      :1956 handle_scheduler_command         │
│   :1814 handle_calendar_command    :1975 handle_datetime_intent           │
│ → all decline → agent + ToolRegistry + memory → engine → runtime → Ollama  │
│ → 4 side-effect calls (history/memory/outcome/render) — DUPLICATED ~15×    │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ CHAIN 2 — grandpa ask         cli/ask.py                                   │
│   :678 memory → :682 datetime → :739 local_action ◄ FUNNEL A               │
│   → :769 file → :799 scheduler → LLM fallback                              │
│ MISSING vs chat: browser, gmail, calendar, notes, downloads, web_search,   │
│                  desktop, project, executive_goal  (9 handlers)            │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ CHAIN 3 — POST /v1/chat/completions    server/routes.py                    │
│   :284 memory → :295 local_action ◄ FUNNEL A → :306 file → :317 scheduler  │
│   → :335 _handle_agent_stream | :340 _handle_agent | :343 _handle_direct   │
│ MISSING vs chat: 10 handlers, including datetime                           │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ CHAIN 4 — /api/voice/*        server/api_routes.py                         │
│   :1755 _handle_voice_reminder   ← EXISTS NOWHERE ELSE                     │
│   :1759 _handle_voice_local_action → :1829 handle_local_action ◄ FUNNEL A  │
│ 114 endpoints across 26 sub-routers in one 2,256-line file                 │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ CHAIN 5 — voice/assistant.py  (VoiceCommandProcessor)                      │
│   :120 handle_local_action(pending, execute=True)  ← approval resume       │
│   :154 datetime → :167 _handle_local_pipeline → :180 memory                │
│   pipeline :243 local_action ◄ FUNNEL A → :253 natural_assistant           │
│   → :267 calendar → :275 gmail → :283 notes → :291 downloads               │
│   → :301 web_search → :311 browser_awareness → :321 browser                │
│   → :329 file → :339 scheduler → :349 local_action (again)                 │
│ 15 handlers — the most complete chain after chat                           │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│ CHAIN 6 — voice/operator.py   (1,613 LOC)                                  │
│   :653 web_search → :674 downloads → :696 notes → :718 calendar            │
│   → :740 gmail → :762 browser_awareness → :781 browser                     │
│   → :800 handle_file_automation  ← DIFFERENT from handle_file_command      │
│   → :871 natural_memory → :1070 executive_goal                             │
│   :940 handle_user_input is the entry; :1271/:1367 two separate loops      │
│ MISSING: datetime, scheduler, desktop, project                             │
└────────────────────────────────────────────────────────────────────────────┘
```

Plus three surfaces that bypass dispatch entirely and reach actuation directly:
`voice/session.py`, `task_scheduler.py`, and `cli/jarvis_cmd.py`.

### 2.2 The two actuation funnels — and how model output reaches one of them

```
                    ┌──────────────────────────────────────┐
                    │ FUNNEL A — handle_local_action()     │
                    │ 12 call sites, ALL user-originated   │
                    │ text. AD-022: claim holds here.      │
                    └──────────────────────────────────────┘
   cli/ask.py · cli/chat_cmd.py · server/routes.py · server/api_routes.py
   voice/assistant.py ×3 · voice/session.py · task_scheduler.py
   burnin.py ×2 · cli/doctor_cmd.py
                                   │
              _normalise → _is_dangerous (37 regex) → allowlist parse
              → classify_permission {allowed|confirm|blocked}
              → LocalActionApprovalStore → local_action_approvals.db
                                   │
                                   ▼
                    ┌──────────────────────────────────────┐
                    │        desktop/control/*             │
                    │        pyautogui · pywin32 · UIA     │
                    └──────────────────────────────────────┘
                                   ▲
                                   │
                    ┌──────────────────────────────────────┐
                    │ FUNNEL B — run_local_action(payload) │
                    │ 12 call sites. NOT all user-derived. │
                    └──────────────────────────────────────┘
   server/routes.py:1166 (HTTP)          automation/executor.py:145
   desktop/automation.py:381             browser/executor.py:146
   desktop/operator.py:370               projects/service.py:80
   local_actions.py:1846                 cli/jarvis_cmd.py:88
   agents/context.py:90        ── hardcoded literal, dry_run=True ✅ SAFE
   agents/goal_mode.py:381     ── hardcoded literal, dry_run=True ✅ SAFE
   skills/registry/defaults.py:28,354  ──┐
                                          │
   ┌──────────────────────────────────────┘
   │ ⚠️  THE LIVE MODEL-OUTPUT PATH  (AD-022)
   │
   │   LLM  →  agent  →  ToolRegistry  →  SkillTool  →  SkillExecutor
   │        →  _pc_action(params)  →  payload["action_type"] = params[...]
   │        →  run_local_action(payload)
   │
   │   Wired at system/builder.py:150 when config.skills.enabled
   │   skills/tool_adapter.py:1 — "wraps a skill as a tool agents can invoke"
   └──────────────────────────────────────────────────────────────────────
                                   │
              desktop/kernel/risk.classify {LOW|MED|HIGH|BLOCKED}
              + APPROVAL_REQUIRED_ACTIONS (post-remediation, orthogonal)
              → _preflight_guard (protected paths, protected active window)
              → pc_control_approvals.db          ← SEPARATE STORE from Funnel A
```

**The two funnels share no code, no vocabulary, and no approval store.** Funnel
B is the only one reachable by model output, and it is guarded by the risk table
alone.

### 2.3 What the map shows

| Finding | Evidence |
|---|---|
| **Six dispatch chains**, not four | Chains 4 and 5 were missed by `AUDIT.md` |
| **Three surfaces bypass dispatch** and call actuation directly | `voice/session.py`, `task_scheduler.py`, `cli/jarvis_cmd.py` |
| **Capability depends on the door** | `handle_project_command` → chat only; `_handle_voice_reminder` → `/api` only; `handle_desktop_command` → chat only |
| **Handler names diverge for the same job** | `handle_file_command` (chains 1,2,3,5) vs `handle_file_automation` (chain 6) |
| **Two actuation funnels, two approval stores** | `local_action_approvals.db` vs `pc_control_approvals.db` |
| **One live model-output → actuation path** | `SkillTool` → `_pc_action` → `run_local_action` |
| **~15× duplicated side effects** | `record_assistant_outcome` appears 17× in `chat_cmd.py` |

---

## 3. Architecture principles

Ordered. When two conflict, the lower number wins.

### P1 — No action executes without policy classification and, where required, human approval

**Revised per AD-022.** The old formulation — "model output never becomes an
action" — is true only of Funnel A. The enforceable, architecture-wide
invariant is:

> **Every action, regardless of whether its parameters came from a human, a
> skill, an agent, an API client, or the scheduler, passes through exactly one
> `PolicyEngine` that classifies risk and enforces approval before execution.**

Two corollaries the target must satisfy:

- **P1a — Provenance is carried, not inferred.** Every `ActionRequest` carries
  `origin ∈ {user, skill, agent, api, scheduler, test}`. The policy table may
  key on it. The audit record must contain it.
- **P1b — Deterministic-first is preserved on the NL path.** The property that
  makes Funnel A strong — user text is parsed by an allowlist, never by the
  model — stays exactly as it is.

### P2 — One dispatcher. Capability is a property of the system, not of the door.

Every entry surface resolves user text through one ordered `IntentHandler`
registry. Adding a handler makes it available everywhere, by construction. A
surface may *filter* the registry declaratively; it may not wire handlers by
hand.

### P3 — One policy engine, one risk vocabulary, one approval store.

Funnel A and Funnel B evaluate the same table and stage approvals in the same
store. Approval requires an out-of-band confirmation code: the channel that
stages an action cannot approve it.

### P4 — Untrusted ingress is redacted and scanned at the boundary, once.

Screen OCR, browser page text, file reads, web-search results, MCP tool results,
and clipboard content pass through redaction and injection scanning at the
ingress module, not at each consumer.

### P5 — Layers depend downward only.

```
entry surfaces → dispatch → policy → capability packages → core
```

No capability package imports an entry surface. Forbids the `pc_control ↔
desktop` (27/16), `cli ↔ voice` (18/7), and `memory_context ↔ memory` (10/1)
cycles.

### P6 — Every subsystem has exactly one canonical owner.

Alternatives are deleted or reduced to shims with a stated removal release.
There is no third state where two live implementations coexist.

### P7 — One observability plane, carrying provenance.

The Windows actuation layer publishes to the same `EventBus` as the platform.
Audit is a **subscriber**, not a parallel path. Per P1a, every action event
carries its origin — so "which actions did the model choose?" is answerable.

### P8 — Configuration describes the product.

A section for every subsystem with runtime behaviour, including desktop, screen,
automation, vision, and voice. Every declared key is read by something.
`config.skills.enabled` is documented as security-relevant (AD-022).

### P9 — Honest contracts and honest provenance.

Docstrings, constants, and behaviour agree. **Extended by AD-019:** the
repository's own origin is stated honestly — `LICENSE` retains upstream
copyright, a `NOTICE` file names OpenJarvis and IPW, and the README credits the
lineage. A project that misrepresents its provenance cannot credibly claim
honest internal contracts.

### P10 — CI validates the product on the product's platform.

A Windows runner exercises the Windows subsystems. **No Windows-layer refactor
begins before it is green.**

### P11 — Local-first, no egress. *(Preserve — already true.)*

Zero network calls in `telemetry/` and `traces/`, verified. Inference is Ollama
on loopback. Only user-invoked outbound calls (web search, Gmail, Calendar), each
opt-in and documented.

### P12 — Heavy or hazardous runtimes live out of process.

The F5 voice runtime already runs in a separate venv behind HTTP on `:8765`,
keeping `torch` out of the main environment. This is the pattern for future heavy
dependencies.

---

## 4. Target layer diagram

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ INTERFACE LAYER — transport + presentation ONLY (~10 lines of dispatch each) ║
║                                                                              ║
║  grandpa chat    grandpa ask    grandpa voice    grandpa voice-operator      ║
║  grandpa project|roadmap|sprint  (autonomous dev mode — AD-020)             ║
║  POST /v1/chat   POST /api/*     grandpa.sdk.Grandpa   MCP server (opt-in)  ║
║                                                                              ║
║  Each surface: read input → dispatcher.dispatch(text, ctx) → render          ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                    │  ctx carries origin (P1a)
                                    ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║ DISPATCH — grandpa.dispatch                                        [P2]      ║
║                                                                              ║
║  IntentDispatcher                                                            ║
║   • one ordered registry of IntentHandler (Protocol)                         ║
║   • every surface receives the identical handler set                         ║
║   • single home for: history · memory write-back · outcome recording ·       ║
║     event publication · error envelope     ← replaces ~15× duplication       ║
║   • surfaces differ only by a declarative allowed-handler filter             ║
╚══════════════════════════════════════════════════════════════════════════════╝
              │ a handler claimed it              │ nothing claimed it
              ▼                                   ▼
╔══════════════════════════════════════╗  ╔═══════════════════════════════════╗
║ POLICY — grandpa.policy   [P1,P3,P4] ║  ║ CONVERSATION / AGENT PATH         ║
║  ★ THE SOLE ENFORCEMENT BOUNDARY ★   ║  ║  agents/  (one framework)         ║
║                                      ║  ║  tools/   (one tool registry)     ║
║  PolicyEngine                        ║  ║  + MCP client tools               ║
║   • ONE risk table — Funnel A + B    ║  ║  + SkillTool  ──────────┐         ║
║   • ONE vocabulary                   ║  ║  + memory facade context│         ║
║   • origin-aware  {user|skill|agent| ║  ║  GuardrailsEngine       │         ║
║      api|scheduler}          [P1a]   ║  ╚═════════════════════════│═════════╝
║   • ONE approval store, out-of-band  ║                            │
║     confirmation code required       ║   ⚠ AD-022: skills carry   │
║   • capability RBAC, FAIL-CLOSED     ║   model-chosen params ──────┘
║   • rate limiting (wired)            ║   ALL of it lands here ─────┐
║   • injection scanning at ingress    ║                             │
║   • protected paths / windows        ║ ◄───────────────────────────┘
║   • emergency stop                   ║
╚══════════════════════════════════════╝
              │                                   │
              ▼                                   ▼
╔══════════════════════════════════════╗  ╔═══════════════════════════════════╗
║ INGRESS GUARD                 [P4]   ║  ║ MODEL RUNTIME — grandpa.runtime   ║
║ redaction · injection scan · taint   ║  ║  (engine/ collapsed into it)      ║
║ applied by: screen · vision ·        ║  ║  ModelRuntime ABC                 ║
║ browser · files · web_search · mcp   ║  ║   → OllamaBackendAdapter          ║
╚══════════════════════════════════════╝  ║   → NativeAdapter (optional)      ║
              │                            ╚═══════════════════════════════════╝
              ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║ CAPABILITY LAYER — one owner each                                  [P6]      ║
║                                                                              ║
║  desktop/    apps · windows · files · power · clipboard · monitors           ║
║  automation/ keyboard · mouse · locator · pipeline · confirmation            ║
║  screen/     capture · OCR · redaction        ← unchanged, already clean     ║
║  vision/     UI element graph over screen/                                   ║
║  browser/    control · read · awareness       ← 4 packages merged to 1       ║
║  voice/      ONE VoiceSession state machine   ← 5 paths merged to 1          ║
║  memory/     ONE MemoryFacade over 4 stores   ← 5-7 systems merged           ║
║  planner/    ONE multi-step assistant planner ← 3 planners merged            ║
║  agent/development/  autonomous dev mode      ← RETAINED (AD-020)            ║
║  skills/ workflow/ scheduler/ sessions/ knowledge/ files/ apps/              ║
║  gmail/ calendar/ notes/ downloads/ projects/ web_search/                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║ CORE — grandpa.core                                                [P5]      ║
║  config (extended, P8) · registry (12 typed) · types · events (extended, P7) ║
║  credentials · runtime_context      Depends on NOTHING inside grandpa.       ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                    │
                                    ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║ OBSERVABILITY — one plane, provenance-carrying                     [P7]      ║
║  core.events.EventBus ← every layer publishes, including desktop/voice       ║
║       ├─ telemetry/  (local only, zero egress)                              ║
║       ├─ traces/     (local only)                                            ║
║       └─ audit/      (SUBSCRIBER — records action origin per P1a)           ║
╚══════════════════════════════════════════════════════════════════════════════╝

OUT OF TREE (archived, history + attribution preserved — AD-019 first):
  rust/ (27,035) · a2a/ (460) · kernel/ (3,272) · templates/ · daemon/
  security/{subprocess_sandbox, severity_policy}   [deleted, 0 consumers]
```

---

## 5. The eight canonical models

The brief asks for these explicitly. Each names its single owner, what it
replaces, and its contract.

### 5.1 Canonical dispatcher — `grandpa.dispatch.IntentDispatcher`

```python
class IntentHandler(Protocol):
    name: str
    def claims(self, text: str, ctx: RequestContext) -> bool: ...
    def handle(self, text: str, ctx: RequestContext) -> HandlerResult: ...

class IntentDispatcher:
    def register(self, handler: IntentHandler, *, order: int) -> None: ...
    def dispatch(self, text: str, ctx: RequestContext) -> DispatchResult: ...
```

**Replaces:** all six chains in §2.1, plus the three bypass surfaces.
**Owns:** history append, memory write-back, outcome recording, event
publication, error envelope — the block duplicated ~15× today.

### 5.2 Canonical intent model — `grandpa.intent`

```python
@dataclass(slots=True, frozen=True)
class Intent:
    name: str                      # "open_app", "read_screen", ...
    confidence: float
    slots: Mapping[str, str]       # parsed, allowlisted values only
    origin: Origin                 # P1a
    raw_text: str
```

**Replaces:** `router/intent_router.py`, `router/legacy_adapter.py`,
`router/route_models.py`, `jarvis/intent_router.py`,
`jarvis/context_resolver.py`, and the allowlist-parser half of
`local_actions.py`.
**Invariant (P1b):** slots are produced by deterministic allowlist parsers over
user text, never by the model.

### 5.3 Canonical execution-plan model — `grandpa.planner.models`

```python
@dataclass(slots=True)
class PlanStep:
    id: str
    action: ActionRequest
    depends_on: tuple[str, ...]
    verifier: StepVerifier | None
    status: StepStatus

@dataclass(slots=True)
class ExecutionPlan:
    id: str
    steps: tuple[PlanStep, ...]
    origin: Origin
```

**Replaces four competing definitions:** `kernel/models.ExecutionPlan`,
`planner/models.ExecutionPlan`, `agent/execution/models.*`,
`advanced_ai.PlanStep`, plus `StepStatus` ×2, `StepVerifier` ×2,
`ValidationResult` ×2, `WorkflowResult` ×3.

### 5.4 Canonical `ToolResult` — `grandpa.core.types.ToolResult`

```python
@dataclass(slots=True)
class ToolResult:
    tool_name: str
    content: str
    success: bool
    metadata: Mapping[str, Any]
    error: str | None = None
```

**Replaces:** `kernel/models.ToolResult`. Also consolidates `ToolRegistry`
(`core/registry.py` vs `kernel/interfaces.py`) and `ToolExecutor`
(`tools/_stubs.py` vs `kernel/interfaces.py`) onto the `core`/`tools` pair.
`kernel/` is archived (AD-012), which removes the duplicates by construction.

### 5.5 Canonical memory interface — `grandpa.memory.MemoryFacade`

```python
class MemoryFacade(Protocol):
    facts:     FactStore       # personal_memory.db
    items:     ItemStore       # memory.db       (sole owner)
    documents: DocumentStore   # documents.db    (MOVED out of memory.db)
    sessions:  SessionStore    # sessions.db, projects.json
```

**Replaces:** `memory_context.py` (45 importers, second `MemoryStore`), the
dual-ownership of `memory.db` by `memory/store.py` (table `memories`) and
`tools/storage/sqlite.py` (table `documents`), plus `SessionStore` ×2 and
`KnowledgeStore` ×2.
**Requires a data migration** — AD-010, approval item A-3.

### 5.6 Canonical policy / approval layer — `grandpa.policy.PolicyEngine`

```python
@dataclass(slots=True, frozen=True)
class ActionRequest:
    action_type: str
    target: str
    args: Mapping[str, Any]
    origin: Origin                 # P1a — user | skill | agent | api | scheduler
    dry_run: bool = False

class PolicyEngine:
    def classify(self, req: ActionRequest) -> PolicyDecision: ...
    def stage_approval(self, d: PolicyDecision) -> PendingApproval: ...
    def confirm(self, action_id: str, code: str) -> ApprovalResult: ...
```

`PolicyDecision` carries an orthogonal pair:
`risk ∈ {LOW, MEDIUM, HIGH, BLOCKED}` **and** `requires_approval: bool`.

**[RECOMMENDATION]** Adopt, do not re-derive. The post-remediation branch already
models this correctly with `APPROVAL_REQUIRED_ACTIONS` as an axis independent of
the tier, and states the reasoning in the source: synthetic input is recoverable
(so MEDIUM is the right blast-radius tier) but reaches arbitrary code execution
(so approval is required regardless). Generalise that design; add `origin` to it.

**Replaces:** `local_actions.classify_permission()` (Funnel A) and
`desktop/kernel/risk.classify()` (Funnel B), and merges
`local_action_approvals.db` with `pc_control_approvals.db`.
**This is the P1 enforcement boundary.** Per AD-022 it is the only thing between
a model-chosen `action_type` and execution.

### 5.7 Canonical observability / audit plane — `grandpa.core.events` + `telemetry/` + `traces/` + `audit/`

`EventType` extends with desktop, window, screen, voice, and **policy** members
(`POLICY_CLASSIFIED`, `APPROVAL_STAGED`, `APPROVAL_GRANTED`, `ACTION_EXECUTED`,
`ACTION_BLOCKED`). Every event carries `origin`.

**Replaces:** the parallel Windows audit path — `pc_control` sqlite+jsonl,
`local_action_approvals.db`, `security/audit.py`, `desktop/kernel/audits.py` —
which becomes a **subscriber**.
**Enables** the question that cannot be answered today: *"which actions in the
last hour were chosen by the model rather than typed by me?"*

### 5.8 Canonical layer boundaries

| Layer | Contents | May import | Public? |
|---|---|---|---|
| **Product — interface** | `cli/`, `server/routers/`, voice surfaces, `agent/development/` CLI | dispatch, policy, capability, core | User-facing |
| **Product — capability** | `desktop/`, `automation/`, `screen/`, `vision/`, `browser/`, `voice/`, `files/`, `apps/`, `gmail/`, `calendar/`, `notes/`, `downloads/`, `projects/`, `web_search/` | policy, core | Internal |
| **Platform substrate** | `agents/`, `tools/`, `planner/`, `skills/`, `workflow/`, `scheduler/`, `sessions/`, `memory/`, `knowledge/`, `runtime/`, `security/`, `telemetry/`, `traces/`, `mcp/` (client) | core | Internal |
| **SDK** | `sdk.py`, `system/` | substrate, core | **Public** (Q-1) |
| **Core** | `core/` | *nothing inside grandpa* | Internal |
| **Infrastructure** | CI, packaging, docs, `voice_runtime/` (out-of-process) | — | — |
| **Archived** | `rust/`, `a2a/`, `kernel/`, `templates/`, `daemon/` | — | Out of tree |

---

## 6. Explicit treatment of Python vs Rust

> **[DECISION AD-002 + AD-019]** **Grandpa is a pure-Python product. There is no
> Rust in the target architecture.**

| Aspect | Target |
|---|---|
| `rust/` (17 crates, 27,035 LOC) | **Archived** to a branch or separate repository, full history preserved, carrying `LICENSE` + `NOTICE` per AD-019 |
| `_rust_bridge.py` | Contract corrected first (docstring, `RUST_AVAILABLE`), retained as an honest shim for one release, then removed with its 16 call sites |
| `tools/shell_exec.py` Rust-first path | **Removed immediately** — it discards the sanitised environment and timeout and hardcodes `returncode: 0, success: True`. Inert today only because the extension is never built. |
| `rust` CI job + `maturin develop` step | **Removed** — they gate the Python product on a subsystem it does not use, and the clippy job is currently red |
| `maturin` in `dev` extra and `[dependency-groups]` | **Removed** |
| Build backend | Stays `hatchling`. No per-platform wheels, no cdylib. |
| Native acceleration in future | If ever needed: PyO3 + maturin, **built in CI, shipped in the wheel, with parity tests against a Python reference** — none of which is true today |

**Why not keep it as optional acceleration:** because that is exactly the current
state, and the current state is the worst option. It blocks CI, it declares
itself mandatory while being absent, it contradicts the architecture docs, and
it has received 18 lines of change in three months while the Python side gained
tens of thousands.

**Rust is not rejected as a technology.** It is rejected as *this* workspace, in
*this* state, for *this* product — a workspace with no crate for any Windows
capability, mirroring the platform layer of an upstream project whose direction
was abandoned at the rebrand.

---

## 7. Windows-first runtime boundary

**[DECISION]** Grandpa targets **Windows 10/11 as its only supported runtime**.
The target architecture makes that boundary explicit rather than incidental.

| Concern | Target |
|---|---|
| **Supported platform** | Windows 10/11. Stated in README and `pyproject.toml` classifiers. |
| **CI** | `windows-latest` runs the assistant suites (**gating, AD-016**); `ubuntu-latest` retained for the platform-substrate suites and lint |
| **Platform-specific code** | Confined to `desktop/`, `automation/`, `screen/`, `vision/`, `voice/`. Everything below the capability layer stays portable. |
| **Dependencies** | `pyautogui` and `pytesseract` move **out of core** into the `screen` extra — an API-only install should not pull GUI automation |
| **Degradation** | Non-Windows imports succeed; capability calls return a typed `PlatformUnsupported` result. No silent `except Exception: pass`. |
| **Out-of-process boundary** | `voice_runtime/` on `:8765` keeps `torch` out of the main venv (P12) |
| **Protected surfaces** | Secure desktop, UAC prompts, and protected windows are never bypassed. `_preflight_guard` stays. |

**Why state it:** the product is Windows-only, and CI has only ever validated the
Linux-portable subset — i.e. the inherited platform, not the product. Every
Windows-layer refactor in the migration plan is gated on closing that gap.

---

## 8. What the target explicitly does not change

The authoritative list is `MIGRATION_PLAN.md` §6. Summary:

- **P1 / P1b** — the policy boundary and deterministic-first NL parsing
- **`core/config.py`** — precedence model, generic field-walking validator,
  back-compat shims, `GRANDPA_HOME`. **Extended per P8, never restructured.**
- **`core/registry.py`** and the 12 typed registries
- **`screen/`** — the cleanest subsystem in the tree
- **`desktop/control/*`** — the typed service layer; only its callers change
- **`runtime/ollama_adapter.py`** — including reasoning-tag stripping
- **`security/scanner.py`, `ssrf.py`, `file_policy.py`, `taint.py`**
- **`agent/development/`** — retained per AD-020
- **The `voice_runtime/` out-of-process boundary**
- **Lazy CLI loading**; `safe_output.py` / `theme.py` / `hints.py`
- **Local-only telemetry, zero egress**
- **`conftest.py` registry isolation and event-bus reset**

---

## 9. How the target changes if decisions are rejected

### If AD-001 is rejected for "composable platform"

`sdk.py` and `SystemBuilder` become the primary contract with semantic
versioning; the MCP server becomes a supported surface with an auth model;
`a2a/` is revived; the Windows assistant becomes one adapter among several, and
the flat god-modules must be repackaged first. **AD-002 must be reopened** — the
Rust workspace targets exactly this direction. Note this also reverses commit
`c40b58ab`, in which the owner already chose the opposite.

### If AD-001 is rejected for "pure Windows assistant"

The substrate must be absorbed or removed — but `core/config.py`,
`core/registry.py`, `tools/`, `agents/`, and `runtime/` all sit under it. That is
a foundation rewrite, adding ~25,000 LOC of live Python to the removal work.
**[RECOMMENDATION] Do not choose this.** The cost is a rewrite; the benefit is
conceptual tidiness.

### If AD-002 is rejected for "active production subsystem"

The workspace must be revived first: MSVC Build Tools documented as a Windows dev
prerequisite, clippy made green, the build backend switched `hatchling` →
`maturin`, per-platform wheels produced. `_rust_bridge`'s "mandatory" contract
becomes true and the 16 fallbacks become dual implementations needing parity
tests. `tools/shell_exec.py`'s Rust path becomes **live** — a latent security
defect becoming an active one. **This is the largest single piece of work implied
by any answer here, and it delivers no assistant capability.**

### If AD-020 is rejected (archive `agent/development/`)

Three CLI groups are removed, 6 test files retired, 4 doc pages deleted, and
`agent/runtime.py` loses 8 call sites. **[RECOMMENDATION] Do not.** The evidence
is one-directional: newest code in the repo, owner-authored, top-level imports in
three CLI modules, in `test_final_acceptance.py`, and with state modified today.

### If AD-022 is rejected

There is nothing to reject — it is a factual correction, not a proposal. The
`SkillTool` → `_pc_action` → `run_local_action` path exists in the code today.
The only choice is whether to *acknowledge* it in the design or leave the
architecture claiming a guarantee it does not provide.

---

## 10. Target architecture in one paragraph

Grandpa becomes a Windows-first local AI assistant — including its autonomous
software-development mode — with one dispatcher, one policy engine, and one
provenance-carrying observability plane, running on a retained platform
substrate whose inherited-but-unused parts are archived out of tree with their
upstream attribution restored. Every entry surface (CLI chat, one-shot ask,
HTTP, both voice modes, the project/roadmap/sprint commands, and the SDK)
becomes about ten lines of transport that hands text to `IntentDispatcher` and
renders what comes back, so capability is a property of the system rather than of
the door. Every action — whether typed by the user, selected by a skill, or
chosen by a model — carries its origin and passes through one `PolicyEngine`
against one risk table into one approval store requiring an out-of-band code.
Untrusted content is redacted and scanned once, at ingress. `core/` depends on
nothing, no capability package imports an entry surface, and CI enforces both on
Windows and Linux. The safety property that makes the current system defensible
is preserved and made explicit: not that model output cannot reach the actuation
layer — it can, through skills, by design — but that nothing reaches it without
being classified and, where required, approved by a human.
