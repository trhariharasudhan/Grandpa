# Grandpa — Current Architecture (As Built)

**Phase:** Architecture Discovery (analysis only — no source code was modified)
**Analysis date:** 2026-08-26
**Tree analysed:** worktree `grandpa-architecture-analysis-d9776e`, branch
`claude/grandpa-architecture-discovery-e46aa5` @ `a031346a` (identical to `main`
and `origin/main`), cross-referenced against the P0/P1 stabilization branch
`claude/grandpa-codebase-audit-bf609c` @ `1584e69b`.

---

## Tag legend

These four tags are used throughout all six architecture documents. They mean
exactly this and nothing else:

| Tag | Meaning |
|---|---|
| **[FACT]** | Verifiable from the repository at a named path, commit, or command. Nothing inferred. |
| **[DECISION]** | A decision this analysis proposes to **ratify**. It is binding only after your approval. Every decision names the evidence it rests on. |
| **[RECOMMENDATION]** | A proposed action, weaker than a decision. Can be deferred without invalidating the target architecture. |
| **[OPEN QUESTION]** | Cannot be resolved from repository evidence. Requires your answer before the dependent work can start. |

---

## 0. Baseline discrepancy — read this first

**[FACT]** Two of the four documents named in the task brief do not exist at the
given paths, on any branch:

| Requested path | Status |
|---|---|
| `docs/architecture/ARCHITECTURE_BASELINE.md` | **Does not exist.** `git log --all --diff-filter=A` finds no commit that ever added it, across 25 local branches and 18 remotes. |
| `AUDIT.md` | **Exists, but not here.** Added by commit `f5bd5d60` on branch `claude/grandpa-codebase-audit-bf609c` only. It is *not* on `main` and *not* in this worktree. Read via `git show`. |
| `README.md` | Present. Read. |
| `docs/architecture/` | Present — 5 files: `overview.md`, `domain-architecture.md`, `query-flow.md`, `memory.md`, `security.md`. Read. |

**[FACT]** The premise that "the P0/P1 stabilization work is complete and the
current architecture baseline is committed" is **half true**:

- The P0/P1 remediation is **real and verified** — it exists on
  `claude/grandpa-codebase-audit-bf609c`, which is 73 files / +4,400 / −925
  ahead of `main`. It fixes `.gitignore` (`runtime/` → `/runtime/`), tracks all
  8 files of `src/grandpa/runtime/`, removes 3 phantom test paths from
  `ci.yml`, re-tiers synthetic input to approval-required, turns API auth on by
  default, and adds out-of-band approval codes.
- It is **not merged into `main`**, and this discovery worktree is branched from
  the *pre-remediation* commit. Consequently `src/grandpa/runtime/` is absent
  from this checkout entirely (still gitignored at this commit); I read it via
  `git show claude/grandpa-codebase-audit-bf609c:src/grandpa/runtime/...`.

**[FACT]** The structural architecture is materially identical between the two
commits. The remediation diff touches security tiers, CI, auth, version-check,
and `runtime/` tracking — it changes **no** package boundary, dependency
direction, or dispatch path. Every architectural finding below therefore holds
for both commits. Where the remediation changed a fact that matters (risk
tiering, API auth), the post-remediation value is stated and marked.

**[RECOMMENDATION]** Merge `claude/grandpa-codebase-audit-bf609c` into `main`
before Phase 1 of the migration plan begins, and re-cut the architecture branch
from the merge commit. Until that happens "current baseline" is ambiguous and
two branches disagree about whether the package is even importable.

**[OPEN QUESTION] Q-0.** Was `ARCHITECTURE_BASELINE.md` written and lost, or
planned but never written? If it exists outside git it should be supplied — it
may contain intent that contradicts the inferences below.

---

## 1. Repository scale (verified in this tree)

| Measure | Value | How |
|---|---|---|
| Python source files | 607 | `find src -name '*.py' \| wc -l` |
| Python source LOC | 130,352 | `find src -name '*.py' -exec cat {} + \| wc -l` |
| Test files | 349 | `find tests -name 'test_*.py' \| wc -l` |
| Test LOC | 69,587 | |
| Rust files / LOC | 124 / 27,035 | `find rust -name '*.rs'` |
| Rust crates | 17 | `rust/Cargo.toml` members |
| Top-level packages under `src/grandpa/` | 53 | |
| Flat top-level modules under `src/grandpa/` | 32 | |
| Registered CLI commands | 51 | `cli.add_command(_lazy(...))` in `cli/__init__.py` |
| HTTP endpoints | 179 | `@*router.<verb>` across `server/*.py` |
| Distinct SQLite database filenames | 29 | string literals in `src/` |
| Classes defined | 895 | |
| Class names defined more than once | 31 | |
| `except Exception` sites | 758 | |
| Total commits | 839 (2026-03-12 → 2026-08-25) | |

Note: `AUDIT.md` cites "≈230 endpoints". Counting `@<name>_router.<verb>`
decorators in this tree yields **179** (60 in `routes.py`, 114 across 26 named
sub-routers in `api_routes.py`, 3 in `approval_routes.py`, 2 in
`upload_router.py`). The difference is a counting method, not a code change.
**179 is the figure used in these documents.**

---

## 2. Question A — What is Grandpa actually intended to be?

The brief correctly refuses to let the README settle this. The README and
`pyproject.toml` describe two different products, and both descriptions match
code that exists.

### 2.1 Evidence for "Windows-first local AI assistant"

| # | Evidence | Source |
|---|---|---|
| A1 | **[FACT]** "a privacy-focused local Windows AI assistant designed to control applications, windows, files, keyboard, mouse, screen interactions, and system operations". | `README.md:3` |
| A2 | **[FACT]** The README's "Focused Roadmap" is 12 items, **all** Windows-assistant capabilities (voice pipeline, intent parsing, app control, screen understanding, mouse/keyboard, files, system ops, multi-step automation, local AI perf, voice feedback, permissions/audit, Windows regression testing). **Zero** platform or SDK items. | `README.md` |
| A3 | **[FACT]** All post-rebrand development is assistant work. First-commit dates: `desktop/` 2026-06-06, `voice/` 2026-06-09, `vision/` 2026-06-24, `screen/` 2026-07-26, `kernel/` 2026-08-14 — all *after* the 2026-05-23 Grandpa rebrand. | `git log --diff-filter=A` |
| A4 | **[FACT]** The five most recent commits are all assistant work: "establish Grandpa local AI assistant foundation", "advance Grandpa core architecture, local voice system, automation, and diagnostics", "add F5 Grandpa voice backend", "fullscreen terminal UI", "restore voice TTS on Windows worker threads". | `git log --oneline -5` |
| A5 | **[FACT]** The largest and most-changed modules are assistant modules: `local_actions.py` 2,203 LOC, `cli/chat_cmd.py` 2,156, `voice/operator.py` 1,613, `pc_control.py` 1,438, `windows_window_control.py` 1,362, `memory_context.py` 1,302. | `wc -l` |
| A6 | **[FACT]** "Grandpa is a local-first Windows assistant." The architecture docs *written for Grandpa* describe only the assistant. | `docs/architecture/overview.md:3` |
| A7 | **[FACT]** 84 of 349 test files sit flat at `tests/` root and are almost entirely assistant tests (`test_pc_control`, `test_local_actions`, `test_windows_*`, `test_screen_*`, `test_voice_*`, `test_desktop_*`, `test_browser_*`). | `ls tests/test_*.py` |
| A8 | **[FACT]** All 6 shipped Ollama Modelfiles carry an assistant persona: "Your name is Grandpa. You are Grandpa, the user's local AI assistant." | `models/Modelfile.mini` |

### 2.2 Evidence for "composable intelligence / backend platform"

| # | Evidence | Source |
|---|---|---|
| B1 | **[FACT]** `description = "Grandpa - personal AI assistant backend with composable intelligence primitives"`. The *distribution metadata* describes the platform. | `pyproject.toml:8` |
| B2 | **[FACT]** Module docstring "modular AI assistant backend with composable intelligence primitives", and `__all__` exports **only** `Grandpa`, `GrandpaSystem`, `MemoryHandle`, `SystemBuilder`. **Nothing Windows-related is in the public API.** | `src/grandpa/__init__.py` |
| B3 | **[FACT]** `GrandpaConfig` has 26 nested sections: engine, intelligence, learning, tools, agent, server, telemetry, traces, security, scheduler, workflow, sessions, **a2a**, operators, speech, tts, grandpa_voice, agent_manager, memory_files, system_prompt, compression, skills, user, hardware. There is **no** `DesktopConfig`, `ScreenConfig`, `AutomationConfig`, `PcControlConfig`, `VisionConfig`, or `VoiceConfig`. The best-engineered module in the repo models the *platform*, not the product. | `src/grandpa/core/config.py` |
| B4 | **[FACT]** `EventType` has 30+ members — inference, tool call, memory, agent turn, telemetry, trace, channel, security, scheduler, batch, loop guard, capability, taint, workflow, skill. **Zero** desktop / window / screen / voice / keyboard event types. | `src/grandpa/core/events.py` |
| B5 | **[FACT]** Event-bus publishers by package: `a2a, agents, cli, connectors, core, kernel, scheduler, sdk, security, server, skills, system, telemetry, tools, traces, workflow`. `local_actions.py` and `pc_control.py` publish **zero** events. The observability plane covers only the platform. | grep `EventBus` / `.publish(` |
| B6 | **[FACT]** `tests/` sub-directories mirror the platform packages (`agents`, `tools`, `security`, `mcp`, `learning`, `kernel`, `traces`, `connectors`, `telemetry`, `engine`, `sessions`, `sdk`, `a2a`, `workflow`, `templates`). The assistant has no mirrored test package. | `ls tests/` |
| B7 | **[FACT]** A full MCP client **and** server with 4 transports, a Python SDK, an A2A protocol implementation, a workflow engine, an agent scheduler, a skills runtime, capability RBAC, and a taint tracker all exist and are wired into `SystemBuilder`. The README explicitly claims "no ... third-party plugin runtime". `mcp/` is one. | `src/grandpa/{mcp,sdk.py,a2a,workflow,scheduler,skills,system}` |
| B8 | **[FACT]** 12 typed registries: Model, Engine, Memory, Agent, Tool, RouterPolicy, Learning, Skill, Speech, Compression, TTS, Connector. This is a plugin-platform substrate. | `src/grandpa/core/registry.py` |

### 2.3 The decisive evidence — git archaeology

This is what resolves the contradiction. Neither product was "layered on" the
other in the ordinary sense; **the repository changed identity.**

**[FACT]** The commit history splits cleanly at 2026-05-23:

| Period | Identity | Evidence |
|---|---|---|
| 2026-03-12 → 2026-05-20 | **OpenJarvis**, itself derived from **IPW** (intelligence-per-watt.ai) | `8798e2ee init commit`; `8de28bdf fix: update project links from intelligence-per-watt.ai to OpenJarvis (#47)`; `301e9cd2 Implement OpenJarvis v1.0 — all five pillars, SDK, benchmarks, Docker`; `aa53681d refactor: rename "Five Pillars" to "Five Primitives"`; merges from `open-jarvis/...`; a Tauri desktop app, a web frontend, a leaderboard, an evals harness, Docker. |
| 2026-05-23 → present | **Grandpa** | `e45fbb1a Initial Grandpa AI framework setup`; `ad316476 rename project branding to Grandpa`. |

**[FACT]** Residual upstream fingerprints still in the source:

- `core/registry.py:3` — "Adapted from IPW's `src/ipw/core/registry.py`"
- `engine/_stubs.py:3` — "Adapted from IPW's `InferenceClient` at `src/ipw/clients/base.py`"
- `agents/_stubs.py:3` — "Adapted from IPW's `BaseAgent` at `src/agents/base.py`"
- `core/events.py:3` — "Extends IPW's `EventRecorder`"
- `server/auth_middleware.py:70` — API keys still carry the `oj_sk_` (OpenJarvis) prefix
- `.github/CODEOWNERS` — `* @jonsaadfalcon @ANarayan @robbym-dev`, none of whom is the repository owner (`trhariharasudhan`); these are upstream authors
- An "Odin" internal model-family codename throughout `prompt/identity.py`, `intelligence/grandpa_models.py`, `docs/development/model-names.md`, and (per `AUDIT.md` §20) a `config.toml.odin-migration-backup` in `~/.grandpa/`

**[FACT]** So the "composable intelligence platform" is **inherited upstream
code**, not a parallel product the current owner set out to build. The
platform's excellent structure — typed registries, event bus, config schema, the
`_stubs.py` ABC pattern — is upstream engineering. The Windows assistant is what
has been built *since* the rebrand, and it was built as **flat top-level modules
alongside** the inherited packages rather than inside them. That is precisely
why `local_actions.py` and `pc_control.py` are 2,203- and 1,438-line files at
package root while `tools/` and `agents/` are tidy sub-packages.

### 2.4 The third interpretation — layered combination

**[FACT]** The two products are not cleanly separable today. They meet at real,
load-bearing seams:

- Both use `core.config` (112 importers), `core.registry` (95), `core.types`
  (78), `core.events` (47).
- The assistant's LLM path terminates in the platform: after every deterministic
  handler declines, `chat`/`ask` fall through to `agents/` + `ToolRegistry` +
  `engine/` → `runtime/` → Ollama.
- `services/` (10 modules) is an assistant-facing façade over platform
  primitives (`desktop_service`, `vision_service`, `browser_service`,
  `planner_service`, `skill_service`, `workflow_service`).
- `system/SystemBuilder` composes agents + tools + memory + MCP + traces, and is
  used by `serve` and the SDK, both of which the assistant depends on.

So "pure Windows assistant" would require ripping out the substrate the
assistant runs on. That is not a viable reading.

### 2.5 [DECISION] A — Recommendation

> **[DECISION A]** Grandpa is a **Windows-first local AI assistant built on a
> retained, internal, composable-intelligence substrate.** It is a *layered
> combination*, but the two layers are **not peers**:
>
> - **The product is the Windows assistant.** It is the only thing the README,
>   the roadmap, the personas, the recent commit history, and the user-facing
>   docs describe. All feature work targets it.
> - **The platform is infrastructure, not a product.** `core/`, `tools/`,
>   `agents/`, `engine/`+`runtime/`, `security/`, `telemetry/`, `traces/`,
>   `skills/`, `workflow/`, `scheduler/`, `sessions/`, `system/` are retained
>   because the assistant genuinely runs on them.
> - **The SDK is a supported-but-secondary surface.** `grandpa.sdk` is the only
>   thing `grandpa/__init__.py` exports and `examples/` holds 5 SDK examples. It
>   should be documented as an *embedding API for this assistant*, not marketed
>   as a general agent framework.
> - **The externally-facing platform protocols are not part of the product.**
>   MCP server, A2A, and the multi-agent orchestration surface are inherited
>   capability with no product requirement behind them.

**Why not "composable platform":** no roadmap item, no persona, no doc page, no
post-rebrand commit, and no user-facing command targets it. Choosing it means
adopting three months of someone else's abandoned product direction.

**Why not "pure Windows assistant":** it would require deleting or rewriting the
substrate that the assistant's own LLM, tool, memory, config, and registry paths
depend on. That is a rewrite, not a refactor.

**Consequence if ratified:** `pyproject.toml`'s description, `__init__.py`'s
docstring, and the public `__all__` are **wrong** and should be corrected to
describe the assistant with the SDK as a secondary surface. This is the
highest-signal, lowest-risk change available in the entire repository.

**[OPEN QUESTION] Q-A1.** Do you intend to publish Grandpa as a library other
people embed (`import grandpa`), or only as an application people run
(`grandpa chat`)? Repository evidence cannot settle this, and it decides whether
`sdk.py` is a first-class contract or an internal seam.

**[OPEN QUESTION] Q-A2.** The MCP **server** lets third parties drive Grandpa's
tools. The README says Grandpa has no third-party plugin runtime. Which is true
going forward? This is a security-boundary question, not a naming one.

---

## 3. Question B — What is the intended status of the Rust workspace?

### 3.1 Evidence for "active production subsystem"

| # | Evidence |
|---|---|
| R1 | **[FACT]** CI builds it. `.github/workflows/ci.yml` `test` job runs `uv run maturin develop --manifest-path rust/crates/grandpa-python/Cargo.toml` **before** pytest. |
| R2 | **[FACT]** CI gates it. A dedicated `rust` job runs `cargo clippy --workspace --all-targets -- -D warnings` and `cargo test --workspace`. |
| R3 | **[FACT]** `rust/Cargo.lock` is committed. `maturin>=1.12.6` is in the `dev` extra **and** in `[dependency-groups].dev`. |
| R4 | **[FACT]** `_rust_bridge.py` docstring: "The Rust backend is **mandatory** — if it cannot be imported, a hard `ImportError` is raised", and `RUST_AVAILABLE: bool = True` is hardcoded. |
| R5 | **[FACT]** `rust/crates/grandpa-python/src/lib.rs:1` — "PyO3 bridge — exposes ~50 Rust classes to Python via `grandpa_rust`". A finished, wired binding layer, not a sketch. |
| R6 | **[FACT]** `README.md` Development section instructs `cargo test --manifest-path rust/Cargo.toml`. |
| R7 | **[FACT]** 16 Python modules call into it via `_rust_bridge`, including 6 in `security/` and 7 in `tools/`. |

### 3.2 Evidence for "obsolete / inherited / should be archived"

| # | Evidence |
|---|---|
| R8 | **[FACT] Decisive.** Since the Grandpa rebrand (2026-05-23) the entire 27,035-LOC Rust workspace has received **one** substantive change: commit `cde132da` (2026-07-26), **18 insertions / 7 deletions in a single file**, `grandpa-tools/src/builtin/http_tools.rs`. The only other post-rebrand commit touching `rust/` is `ad316476`, the branding rename. In the same window Python gained `desktop/`, `voice/`, `vision/`, `screen/`, `kernel/`, `planner/`, `agent/`, `browser*/` — tens of thousands of lines. |
| R9 | **[FACT] Decisive.** The 17 crates are `a2a, agents, core, engine, learning, mcp, python, recipes, scheduler, security, sessions, skills, telemetry, templates, tools, traces, workflow`. That is a **1:1 mirror of the OpenJarvis platform layer**. There is **no crate** for desktop, windows, voice, screen, vision, automation, or browser. The Rust workspace accelerates Product B and has literally zero surface area for Product A. |
| R10 | **[FACT]** The largest crate is `grandpa-learning` at 6,281 LOC. The corresponding Python package `learning/` is 905 LOC, mostly `_stubs.py` + `routing/`. The Rust side implements a subsystem the Python side abandoned. |
| R11 | **[FACT]** The shipped wheel cannot contain it. `[build-system] requires = ["hatchling"]`, `[tool.hatch.build.targets.wheel] packages = ["src/grandpa"]`. There is no maturin build backend and no cdylib in the wheel. **Every installed copy of Grandpa runs pure Python.** |
| R12 | **[FACT]** R4 is false in practice. Every consumer wraps the call in `try: ... except Exception:` or `except ImportError:` and falls back — `security/scanner.py:22-28`, `security/ssrf.py:79-85`, `tools/calculator.py:94-99`. The "mandatory, no fallback" docstring and `RUST_AVAILABLE = True` are both untrue. |
| R13 | **[FACT]** `docs/architecture/domain-architecture.md` (a Grandpa-era doc) states the opposite of `_rust_bridge.py`: "The **optional** Rust workspace is audited separately. **Python fallbacks remain the default** where native bindings are unavailable." The two authoritative statements in the repo contradict each other. |
| R14 | **[FACT]** Per `AUDIT.md` §5/§19: `grandpa_rust` is not installed on the development machine; `cargo clippy` fails in CI; MSVC `link.exe` is absent on the Windows dev box, so the workspace cannot even be built there. The product is Windows-only and its native layer does not build on the developer's Windows machine. |
| R15 | **[FACT]** The one place the Rust path is *preferred* rather than a fallback — `tools/shell_exec.py:126-140` — is a **security defect**: it discards the sanitised environment and the timeout and hardcodes `returncode: 0, success: True`. It is inert only because the extension is never built. |

### 3.3 [DECISION] B — Recommendation

> **[DECISION B]** The Rust workspace is **inherited, currently-dead, upstream
> infrastructure for a product direction that was abandoned at the 2026-05-23
> rebrand.** Its intended status should be set to: **archived out of the main
> tree, not deleted.**
>
> Concretely:
> 1. Move `rust/` to a separate repository or an `archive/` branch, preserving
>    full history. Do **not** `rm -rf` it — 27k LOC of working Rust with a
>    ~50-class PyO3 binding layer is a real asset if the platform direction is
>    ever revived.
> 2. Delete the `rust` CI job and the `maturin develop` step from the `test`
>    job. Both currently gate the Python product on a subsystem it does not use.
> 3. **Before** archiving, fix `_rust_bridge.py`: correct the docstring, remove
>    the hardcoded `RUST_AVAILABLE = True`, and remove the Rust-first path in
>    `tools/shell_exec.py`. These are correctness fixes that must land whether
>    or not the archive happens.
> 4. Keep `_rust_bridge.py` itself as a thin, honest, always-unavailable shim
>    for one release so the 16 consumers do not need simultaneous edits.

**Why not "active production subsystem":** 18 lines of change in three months,
absent from the shipped wheel, its "mandatory" contract false at every call
site, no crate for any assistant capability, and it does not build on the
product's own target platform.

**Why not "planned future subsystem":** there is no plan. No roadmap item, no
doc, no issue, and no TODO (the repo has zero TODO markers in 607 source files).
A subsystem is only "planned" if a plan exists.

**Why not "experimental":** experiments are not wired into CI as blocking gates
and are not declared mandatory in their own docstring. The current state is the
worst of all worlds — it blocks CI, misleads readers, and does nothing.

**Why not "delete":** the code is functional, it carries upstream security fixes
(SSRF IPv4-mapped-IPv6 handling, signature-verification hardening), and the
decision to abandon the platform direction has never been made explicitly.
Archiving is reversible; deletion is not.

**[OPEN QUESTION] Q-B1.** Was the Rust workspace ever built and used
successfully on any machine at any point *after* the rebrand? If yes, there is
performance data not visible here and this recommendation should be
re-examined.

**[OPEN QUESTION] Q-B2.** Is there a licensing or attribution obligation
attached to the inherited IPW/OpenJarvis code (Rust *and* Python) that
constrains what can be archived, relicensed, or republished? `CODEOWNERS`
naming three upstream authors suggests this was never resolved.

---

## 4. Layer map (as built)

```
╔═══════════════════════════════════════════════════════════════════════════╗
║ ENTRY SURFACES — 6 independent, hand-written dispatch chains              ║
║  grandpa chat (28 handlers)   grandpa ask (5)   routes.py (9)             ║
║  voice/assistant.py (15)      voice/operator.py (11)   api_routes.py (3)  ║
╚═══════════════════════════════════════════════════════════════════════════╝
                    │ each chain independently maintained
                    ▼
╔═══════════════════════════════════════════════════════════════════════════╗
║ INTENT / ROUTING — no single dispatcher                                   ║
║  router/intent_router.py · jarvis/intent_router.py · router/legacy_       ║
║  adapter.py · local_actions._normalise + allowlist parsers ·              ║
║  planner/routing.py · core_ai_brain.py                                    ║
╚═══════════════════════════════════════════════════════════════════════════╝
        ┌───────────────────────┴────────────────────────┐
        │ handled                                        │ declined → LLM
        ▼                                                ▼
╔══════════════════════════════╗          ╔══════════════════════════════════╗
║ POLICY — two disjoint models ║          ║ PLATFORM SUBSTRATE (inherited)   ║
║ NL path:                     ║          ║  agents/ (8 agents)              ║
║  _is_dangerous (37 regex)    ║          ║  tools/ (32 modules, ~47 tools)  ║
║  → allowlist parse           ║          ║  + MCP client tools              ║
║  → classify_permission       ║          ║  + memory context                ║
║    {allowed|confirm|blocked} ║          ║  security.GuardrailsEngine       ║
║  → LocalActionApprovalStore  ║          ╚══════════════════════════════════╝
║ API path:                    ║                          │
║  desktop/kernel/risk.classify║                          ▼
║   {LOW|MED|HIGH|BLOCKED}     ║          ╔══════════════════════════════════╗
║  + APPROVAL_REQUIRED_ACTIONS ║          ║ MODEL RUNTIME                    ║
║    (post-remediation)        ║          ║  engine/ (342 LOC shim)          ║
║  → pc_control approval store ║          ║   → runtime/ (1,364 LOC)         ║
╚══════════════════════════════╝          ║   → OllamaBackendAdapter → httpx ║
        │                                 ║   → Ollama :11434                ║
        ▼                                 ╚══════════════════════════════════╝
╔═══════════════════════════════════════════════════════════════════════════╗
║ ACTUATION — Windows                                                       ║
║  desktop/control/{applications,windows,files,power,clipboard,monitors,    ║
║   automation,registry,diagnostics} · automation/{keyboard,mouse,locator,  ║
║   pipeline} · screen/ · vision/ · browser*/ · apps/ · files/ ·            ║
║   windows_window_control.py · windows_app_resolver.py                     ║
╚═══════════════════════════════════════════════════════════════════════════╝
        │                                                  │
        ▼ (audit only — sqlite + jsonl)                     ▼ (event bus)
╔══════════════════════════════╗          ╔══════════════════════════════════╗
║ WINDOWS AUDIT TRAIL          ║   ✕ no   ║ PLATFORM OBSERVABILITY           ║
║ pc_control audit.db          ║  bridge  ║ core.events EventBus (30+ types, ║
║ local_action_approvals.db    ║ ◄──────► ║  none desktop-related)           ║
║ security/audit.py            ║          ║ telemetry/ · traces/             ║
║ desktop/kernel/audits.py     ║          ║                                  ║
╚══════════════════════════════╝          ╚══════════════════════════════════╝

DEAD OR NEAR-DEAD:  rust/ (0 runtime consumers) · a2a/ (0 src consumers)
                    kernel/ (1 src consumer)    · 5 security modules (0 consumers)
                    templates/, daemon/ (0)     · .dockerignore (no Dockerfile)
```

---

## 5. Request / routing paths — full divergence matrix

**[FACT]** There are **six** independent dispatch chains, not four. `AUDIT.md`
counted four; `voice/assistant.py` and `server/api_routes.py` are two more.

| Handler | `chat` | `ask` | `routes.py` | `api_routes.py` | `voice/assistant` | `voice/operator` |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `handle_local_action` | ✅ | ✅ | ✅ | ✅ | ✅ | via assistant |
| `handle_file_command` | ✅ | ✅ | ✅ | ❌ | ✅ | `handle_file_automation` |
| `handle_memory_command` | local variant | ✅ | ✅ | ❌ | ✅ | `parse_and_route_intent` |
| `handle_scheduler_command` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `handle_datetime_intent` | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `handle_desktop_command` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `handle_browser_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_browser_awareness_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_gmail_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_calendar_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_notes_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_downloads_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_web_search_command` | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `handle_executive_goal` | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `handle_project_command` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `handle_voice_reminder` | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| 12 `*_slash_command` handlers | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

**[FACT]** Capability is a function of *which door you knock on*. "Check my
email" works in `chat`, `voice/assistant`, and `voice-operator`; it does not work
in `ask` or over HTTP. `handle_project_command` works only in `chat`.
`handle_voice_reminder` works only over `/api/*`.

**[FACT]** The four side-effect calls that must follow every response —
`history.append`, `remember_conversation`, `record_assistant_outcome`, render —
are repeated verbatim at ~15 sites in `chat_cmd.py`; `record_assistant_outcome`
appears 17 times. This is the largest single duplication hotspot in the tree and
a direct consequence of having no dispatcher.

**[FACT]** The **deterministic-first invariant holds on every chain.**
`handle_local_action` is called only with *user* text, never model output
(`cli/ask.py:739`, `cli/chat_cmd.py:1918`, `server/routes.py:295`,
`server/api_routes.py:1829`). This is the strongest design property in the
codebase.

---

## 6. Dependency direction and cycles

**[FACT]** Fan-in by package (number of distinct packages depending on it):

| Package | In-degree | Verdict |
|---|---:|---|
| `core` | 56 | Correct — this is the kernel |
| `memory_context` (flat module) | 14 | **Wrong shape** — a 1,302-line flat module acting as a kernel |
| `tools` | 14 | Correct |
| `agents` | 11 | Correct |
| `engine` | 11 | **Wrong** — a 342-line shim should not have 11 dependents |
| `security` | 11 | Correct |
| `pc_control` (flat) | 10 | **Wrong shape** |
| `browser_control` (flat) | 10 | **Wrong shape** |
| `local_actions` (flat) | 7 | **Wrong shape** |
| `windows_window_control` (flat) | 7 | **Wrong shape** |
| `screen_awareness` (flat) | 7 | **Wrong shape** — duplicates `screen/` |

**[FACT] Zero in-degree (nothing in `src/` imports these):** `a2a`, `daemon`,
`templates`, `voice_service`. (`voice_service` is invoked out-of-process over
HTTP, so its zero in-degree is by design, not death. `a2a`, `daemon`,
`templates` are dead.)

**[FACT] Package-level import cycles — 23 found.** The structurally significant
ones:

| Cycle | Weight | Assessment |
|---|---|---|
| `pc_control` ↔ `desktop` | 27 / 16 | **Severe.** The heaviest cycle in the tree. `pc_control.py` is both the policy layer *above* `desktop/` and a dependency *of* it. |
| `cli` ↔ `voice` | 18 / 7 | Voice reaches back into CLI presentation. |
| `memory_context` ↔ `memory` | 10 / 1 | The two memory systems are entangled, not merely parallel. |
| `files` ↔ `kernel` | 2 / 16 | `kernel/` imports `files/` 16×; `files/kernel_adapter.py` imports back. |
| `core` ↔ `tools` | 1 / 75 | A single back-edge from the kernel into a leaf. Cheap to break. |
| `core` ↔ `security`; `core` ↔ `engine`; `agents` ↔ `core` | 1 each | Single back-edges — all cheap to break. |
| `_rust_bridge` ↔ `security`; `_rust_bridge` ↔ `tools` | 3/10; 1/11 | The bridge converts into `security.types`, so it depends on what depends on it. |
| `local_actions` ↔ `router`; `local_actions` ↔ `actions` | 1/3; 1/5 | Routing indirection loops. |
| `smart_automation` ↔ `skills`; `automation` ↔ `vision`; `connectors` ↔ `tools`; `mcp` ↔ `tools`; `planner` ↔ `skills`; `planner` ↔ `voice`; `jarvis` ↔ `voice`; `skills` ↔ `skill_builder`; `cli` ↔ `projects`; `cli` ↔ `server`; `tray` ↔ `cli` | low | Individually cheap; collectively they mean no layer boundary is enforced. |

**[FACT]** `docs/architecture/domain-architecture.md` states the intended rule:
"Interfaces call routers; routers create typed requests; safety evaluates those
requests; executors call narrow Windows or integration adapters. Executors must
not call back into chat or infer permission from model text."

The second half **holds** — no executor infers permission from model text. The
first half **does not** — `pc_control` ↔ `desktop` and `cli` ↔ `voice` are both
violations of the stated layering.

---

## 7. Duplicate models and classes

**[FACT]** 31 class names are defined more than once across 895 classes. Grouped
by the architectural fault each exposes:

**Three competing domain models** (`core/types.py` · `kernel/models.py` ·
`planner/models.py`): `ToolResult`, `ToolRegistry`, `ToolExecutor`, `RiskLevel`,
`ExecutionPlan`, `ConfirmationRequest`, `VerificationResult`.

**Two agent frameworks** (`agent/` · `agents/`): `AgentExecutor`, `AgentContext`,
`AgentResult`, `AgentGoal`, `AgentRuntime`.

**Three planning systems** (`agent/` · `planner/` · `workflow/`): `StepStatus`,
`StepVerifier`, `ValidationResult`, `PlanStep`, `WorkflowResult` (×3).

**Flat module vs. package** — the rebrand fault line. In every case the flat
module is the older assistant code and the package is the newer refactor, and
both are live:

| Class | Flat (older) | Package (newer) |
|---|---|---|
| `MemoryStore` | `memory_context.py:115` | `memory/store.py:21` |
| `SchedulerStore` | `task_scheduler.py:52` | `scheduler/store.py:52` |
| `WindowInfo` | `windows_window_control.py:163` | `screen/models.py:29` |
| `MonitorInfo` | `desktop_context.py:38` | `screen/models.py:11` |
| `OcrResult` | `screen_awareness.py:60` | `screen/models.py:84` |
| `AutomationResult` | `desktop_automation.py:79` | `automation/models.py:69` |
| `PlanStep` | `advanced_ai.py:57` | `planner/models.py:115` |
| `WorkflowResult` | `smart_automation.py:41` | `workflow/types.py:51` (+ `projects/models.py:120`) |

**Storage owner collisions:** `KnowledgeStore` (`connectors/store.py` vs
`knowledge/storage.py`), `OllamaEmbedder` (`connectors/embeddings.py` vs
`tools/storage/embeddings.py`), `SessionStore` (`server/session_store.py` vs
`sessions/session.py`).

**Security:** `ScanResult` (`cli/scan_cmd.py` vs `security/types.py`),
`SecurityContext` (`security/__init__.py` vs `system/bundles.py`),
`SecurityBlockError` (`security/boundary.py` vs `security/guardrails.py` — a
duplicate *inside a single package*).

**[FACT]** Additionally, `src/grandpa/kernel/` and `src/grandpa/desktop/kernel/`
are two unrelated packages both named "kernel". `desktop/kernel/` is live (risk,
approvals, execution, audits, emergency, requests); `kernel/` is the near-dead
"canonical contracts" package.

---

## 8. Subsystem matrix

Each entry: **canonical implementation candidate** → duplicates → consumers →
dependencies → problems → migration risk → target state. Risk is **L / M / H**
for the cost of moving to the target state.

### 8.1 Orchestration / kernel

| | |
|---|---|
| **Canonical candidate** | `desktop/kernel/` (risk, approvals, execution, audits, emergency, requests) — live, exercised, owns the structured-action path. |
| **Duplicates** | `kernel/` (3,272 LOC, docstring "Canonical request execution contracts for Grandpa", **1 consumer in `src/`**: `files/kernel_adapter.py`; 8 test files). `planner/` (4,178 LOC). `agent/execution/` (plan/step/verify). `workflow/` (graph engine). |
| **Consumers** | `desktop/kernel/` ← `pc_control.py`, `desktop/`, `server/routes.py`. `kernel/` ← `files/` only. |
| **Dependencies** | `desktop/kernel/` → `desktop/control/`, `core.config`. `kernel/` → `files/` (16 edges). |
| **Problems** | Name collision between two "kernel" packages. `kernel/` is aspirational and unadopted — its docstring claims a canonicity it never received. Four planning/execution systems (`kernel`, `planner`, `agent/execution`, `workflow`) with overlapping `ExecutionPlan` / `PlanStep` / `StepVerifier` / `ValidationResult`. |
| **Migration risk** | **M** — `kernel/` has 8 test files to retire; `desktop/kernel/` is on the hot path for every structured action. |
| **Target state** | Rename `desktop/kernel/` → `desktop/execution/` to kill the collision. Retire `kernel/` after folding `files/kernel_adapter.py` back into `files/`. Choose **one** planner (see 8.4). |

### 8.2 AI / LLM / model runtime

| | |
|---|---|
| **Canonical candidate** | `runtime/` — `ModelRuntime` ABC, `BackendAdapter`, `OllamaBackendAdapter`, `NativeAdapter`, exceptions, utils (1,364 LOC, 8 files). |
| **Duplicates** | `engine/` (342 LOC): `_stubs.py` (`InferenceEngine(ModelRuntime, ABC)`), `_discovery.py`, `ollama.py` (23 LOC), `_base.py`, and **`_network.py::local_port_is_open`, byte-identical to `runtime/utils.py::local_port_is_open`**. |
| **Consumers** | `engine/` has **11 dependent packages / 44 import edges** (cli ×19, agents ×6, core, ...). `runtime/` has 7 — almost all from `engine/`. |
| **Dependencies** | `engine/` → `runtime/` (6 edges) → `httpx` → Ollama `:11434`. |
| **Problems** | `engine/` is migration residue adding nothing but exception aliases and one duplicated helper, yet carries 11× the fan-in of the thing it wraps. `_MAX_NUM_PREDICT = 2048` silently caps every generation. `intelligence.default_model = "grandpa-mini:latest"` contradicts README's `ollama pull qwen2.5:3b`. `native_adapter.py` (363 LOC) has never been exercised. **On `main` this entire layer is untracked and the package does not import.** |
| **Migration risk** | **M** — 44 import sites, but the change is mechanical (`grandpa.engine` → `grandpa.runtime`) and test-covered. |
| **Target state** | Collapse `engine/` into `runtime/`. Keep `InferenceEngine` and the `EngineRegistry` binding (they are the registry contract) but move them under `runtime/`. Delete `engine/_network.py`. Keep exception aliases for one release. |

### 8.3 Memory

| | |
|---|---|
| **Canonical candidate** | **Split by concern, not one winner.** `memory/` (2,502 LOC, 12 modules: store, short_term, long_term, preferences, project_memory, retrieval, intelligence, service, intent, context, conversation, models) is the structurally correct home. |
| **Duplicates** | `memory_context.py` (1,302 LOC flat, **45 importers**, `~/.grandpa/personal_memory.db`, defines a second `MemoryStore`). `tools/storage/sqlite.py` writes table `documents` into **the same default file** `~/.grandpa/memory.db` that `memory/store.py` uses for table `memories`. Plus `sessions/`, `server/session_store.py`, `MemoryFilesConfig` (`~/.grandpa/MEMORY.md`), `connectors/store.py` + `knowledge/storage.py` (duplicate `KnowledgeStore`). **Five to seven memory systems depending how you count.** |
| **Consumers** | `memory_context` ← 45 modules including `cli/`, `server/`, `skills/`, `voice/`. `memory/` ← 8 packages. |
| **Dependencies** | `memory_context` ↔ `memory` is a **cycle** (10 / 1). |
| **Problems** | Two schemas, one file, no owner (`memory.db`). `memory_context._embed_text` is FNV-1a hashed bag-of-words + character trigrams, but the constant is `SEMANTIC_MODEL = "grandpa-local-semantic-v1"` and the endpoint is `personal_memory/search` — the naming claims learned semantics that do not exist. 29 distinct `.db` filenames across the tree. |
| **Migration risk** | **H** — 45 importers, live user data in `~/.grandpa/`, and a schema collision that must be resolved without data loss. **The highest-risk subsystem in the repository.** |
| **Target state** | One `MemoryFacade` over four explicitly-named stores: facts/activity, structured items, RAG documents, sessions. `memory.db` gets exactly one owner; the RAG store moves to `documents.db`. Rename `SEMANTIC_MODEL` to state plainly that retrieval is lexical unless an embedding extra is installed. **Requires an explicit data-migration step and approval.** |

### 8.4 Agent / planning

| | |
|---|---|
| **Canonical candidate** | `agents/` (6,758 LOC, 21 modules) — registry-based, wired into `SystemBuilder`, used by `serve`, `ask`, the `chat` fallback, and the SDK. The one with real consumers. |
| **Duplicates** | `agent/` (5,846 LOC, 29 modules, "Agent Runtime V1", with `agent/development/` + `agent/execution/`) with colliding `AgentExecutor`, `AgentContext`, `AgentResult`, `AgentGoal`, `AgentRuntime`. `planner/` (4,178 LOC, "Executive planner"). `workflow/` (788 LOC, graph engine). `advanced_ai.py` defines a third `PlanStep`. |
| **Consumers** | `agent/` ← `cli` (24 edges) — the `grandpa agent` / `sprint` / `roadmap` / `project` command group. `agents/` ← `server`, `system`, `cli`, `sdk`. `planner/` ← `agents`, `services/planner_service.py`, `voice`. |
| **Dependencies** | All three → `core.types`, `tools/`, `engine/`. |
| **Problems** | Two frameworks, three planners, four `ExecutionPlan`-shaped types. `agent/development/` (sprint, roadmap, checkpoint, tracker) is an autonomous-software-development feature with no roadmap item behind it. |
| **Migration risk** | **M** for `planner`/`workflow` consolidation; **H** for `agent/` vs `agents/` because `agent/` backs 6 shipped CLI commands. |
| **Target state** | `agents/` is the agent framework. `planner/` is the multi-step *assistant* planner (the one the voice/chat path uses). Fold `agent/execution/`'s verify/recover logic into `planner/`. **`agent/development/` is a candidate for archival** — see [OPEN QUESTION] Q-4 in `ARCHITECTURE_DECISIONS.md`. |

### 8.5 Tools

| | |
|---|---|
| **Canonical candidate** | `tools/` — `_stubs.py` (`BaseTool` ABC + `ToolExecutor`, 402 LOC, **53 importers**), 32 modules, ~47 registered tools, `tools/storage/` backends. |
| **Duplicates** | `ToolResult` in `core/types.py` **and** `kernel/models.py`; `ToolRegistry` in `core/registry.py` **and** `kernel/interfaces.py`; `ToolExecutor` in `tools/_stubs.py` **and** `kernel/interfaces.py`. `skills/tool_adapter.py` is a third adaptation path. |
| **Consumers** | 14 packages. `mcp/` → `tools/` (11 edges) is the plugin-ingress path. |
| **Dependencies** | → `core.types`, `core.events`, `security/` (11 edges), `_rust_bridge` (11 edges). |
| **Problems** | `tools/shell_exec.py:126-140` prefers the Rust path, discarding the sanitised env and the timeout and hardcoding `returncode: 0, success: True` — a real security defect, currently inert. `core` ↔ `tools` back-edge. |
| **Migration risk** | **L** — cohesive, well-tested (35 test files), capability/taint/timeout hooks already present. |
| **Target state** | Keep as-is. Remove the Rust-first path in `shell_exec`. Retire `kernel/interfaces.py`'s duplicate contracts. |

### 8.6 Desktop automation

| | |
|---|---|
| **Canonical candidate** | `desktop/control/` (9 typed services: applications, windows, files, power, clipboard, monitors, automation, registry, diagnostics) + `desktop/kernel/` (risk, approvals, execution, audits, emergency, requests) + `automation/` (locator, keyboard, mouse, pipeline, confirmation). |
| **Duplicates** | `local_actions.py` (2,203 LOC — NL parse + policy + execute in one flat module), `pc_control.py` (1,438 — structured API + risk tiers + approvals), `windows_window_control.py` (1,362), `desktop_automation.py`, `smart_automation.py`, `desktop_context.py`, `windows_app_resolver.py` (vs `apps/resolver.py`), `apps/` (9 modules). `AutomationResult` twice; `WindowInfo`/`MonitorInfo` in three places. |
| **Consumers** | `pc_control` ← 10 packages; `local_actions` ← 7; `windows_window_control` ← 7; `desktop` ← 9. |
| **Dependencies** | **`pc_control` ↔ `desktop` cycle, weight 27/16 — the heaviest in the tree.** |
| **Problems** | Two disjoint policy models (see §9). The flat god-modules are simultaneously parser, policy, and executor. Zero event-bus participation. `automation` → `windows_window_control` (13 edges) bypasses `desktop/control/windows.py`. |
| **Migration risk** | **H** — this is the product's core, it is Windows-only, and CI has never exercised it (Linux-only runners). Any refactor here is untested by CI *by construction*. |
| **Target state** | `desktop/` owns actuation; `automation/` owns input pipelines; one `PolicyEngine` owns risk + approval for both the NL and API paths; `local_actions.py` decomposes into `intent/` (parse) + policy calls + `desktop/` calls. **Nothing here moves until a `windows-latest` CI job exists and is green.** |

### 8.7 Voice

| | |
|---|---|
| **Canonical candidate** | `voice/` (22 modules, 7,322 LOC) + `speech/` (STT/TTS backends) + `voice_service/` (out-of-process F5 runtime over HTTP on `:8765`). |
| **Duplicates** | **Five routing paths:** `voice/assistant.py` (15 handlers), `voice/operator.py` (1,613 LOC, 11 handlers), `voice/session.py`, `voice/cli_session.py`, `voice/loop.py`. Plus `jarvis/voice_input.py` (367 LOC) as a sixth input path used by `voice/diagnostics.py`, `voice/operator.py:1441`, and `cli/voice_cmd.py`. |
| **Consumers** | `voice` ← 5 packages; `cli` ↔ `voice` is a **cycle** (18/7). |
| **Dependencies** | → `core`, `automation` (10), `cli` (7), `speech`, `local_actions`. |
| **Problems** | A fix in one voice path does not reach the other four. `voice/operator.py` at 1,613 LOC is a god-module. **No `[voice]` section exists in `GrandpaConfig`** even though the live `~/.grandpa/config.toml` contains one — it is read via env and `voice/config.py`, outside the schema. 74 `GRANDPA_VOICE_*` env vars. Per `AUDIT.md`, this subsystem accounts for 9 of 13 test failures and both suite hangs. |
| **Migration risk** | **H** — hardware-dependent, untestable in CI, the most fragile subsystem by failure count. |
| **Target state** | One `VoiceSession` state machine; the five paths become configuration of it, not copies of it. Add a real `VoiceConfig` section to `GrandpaConfig`. Retire `jarvis/`. **The out-of-process F5 runtime boundary must be preserved** — keeping `torch` out of the main venv is a correct decision. |

### 8.8 Screen / vision

| | |
|---|---|
| **Canonical candidate** | `screen/` (11 modules, 1,541 LOC — capture, ocr, analyzer, redaction, models, windows, intents, config, errors, service). Per `AUDIT.md` the best-factored subsystem in the repository, and the structure supports that. |
| **Duplicates** | `screen_awareness.py` (664 LOC flat, **7 importers**, defines a second `OcrResult`), `desktop_context.py` (defines a second `MonitorInfo`), `vision/ocr.py` alongside `screen/ocr.py`. |
| **Consumers** | `screen` ← 6 packages including `vision` (11 edges) and `automation` (6). |
| **Dependencies** | `vision/` → `screen/`; `automation/locator.py` → `screen/`. |
| **Problems** | `screen_awareness.py` is the pre-refactor flat version of `screen/` and both are live. `vision/` (1,614 LOC — UIA + OCR + element graph + matcher + local_model) overlaps `screen/analyzer.py`. |
| **Migration risk** | **L–M** — clean interfaces, 7 importers to redirect. |
| **Target state** | `screen/` owns capture / OCR / redaction; `vision/` owns the semantic UI-element graph on top of it. Retire `screen_awareness.py`. **Redaction (`screen/redaction.py`, 7 pattern classes) must remain on every path.** |

### 8.9 Browser

| | |
|---|---|
| **Canonical candidate** | **None yet — four packages, no owner.** |
| **Duplicates** | `browser_control.py` (1,264 LOC flat, **10 importers**), `browser/` (7 modules — agent, automation, executor, models, parser, safety, urls), `browser_intelligence/` (12 modules, 2,247 LOC — page_reader, content_extractor, summarizer, navigator, research_mode, comparison_engine, source_verifier, link_resolver, session_memory, page_analyzer, formatter), `browser_awareness/` (6 modules — analyzer, automation, capture, models, parser, safety). Note `browser/safety.py` **and** `browser_awareness/safety.py`; `browser/parser.py` **and** `browser_awareness/parser.py`; `browser/automation.py` **and** `browser_awareness/automation.py`. |
| **Consumers** | `browser_control` ← 10 packages; `browser_intelligence` ← 4 (incl. `planner`, 7 edges); `browser` ← 6; `browser_awareness` ← 2. |
| **Dependencies** | → `screen/`, `automation/`, `security/ssrf.py`. |
| **Problems** | **`redact_screen_text` is applied in `screen/`, `vision/`, and `automation/locator.py` but in NONE of the four browser packages.** Page text — the single largest source of untrusted content the assistant ingests — reaches logs and prompts unredacted. Four packages with three duplicated module names is the worst-organised area in the tree. |
| **Migration risk** | **M** — 10 importers on the flat module, but browser paths are not on the critical `doctor`/`chat` path. |
| **Target state** | One `browser/` package: `browser/control` (drive), `browser/read` (extract — currently `browser_intelligence`), `browser/awareness` (observe). Redaction applied at every extraction boundary. **The redaction gap is a security fix, not a refactor — it should land before, and independently of, the consolidation.** |

### 8.10 API / server

| | |
|---|---|
| **Canonical candidate** | `server/` — `app.py:create_app()`, `routes.py` (60 endpoints), `api_routes.py` (114 endpoints / 26 sub-routers), `approval_routes.py` (3), `upload_router.py` (2), `auth_middleware.py`, `middleware.py`, `ws_bridge.py`, `stream_bridge.py`, `session_store.py`, `models.py`. **179 endpoints.** |
| **Duplicates** | `SessionStore` in `server/session_store.py` **and** `sessions/session.py`. Two approval endpoints for the same action (`/api/local-action/{id}/approve` and `/v1/local-actions/{id}/approve`). |
| **Consumers** | `cli/serve.py`; external OpenAI-compatible clients. |
| **Dependencies** | Widest fan-out in the tree: `services` (16), `agents` (15), `memory_context` (15), `core` (14), `voice` (13), `knowledge` (10), `pc_control` (9). |
| **Problems** | `api_routes.py` is 2,256 LOC with 26 sub-routers in one file. `POST /api/local-action` accepts a bare `dict[str, Any]` — no Pydantic model on the most security-relevant endpoint. Response shape adds non-standard `complexity` and `local_action` keys to `/v1/chat/completions`. Middleware order is correct (auth outermost). **Post-remediation:** auth on by default with a first-run generated key; approval requires an out-of-band code. **Pre-remediation (`main`):** all 179 endpoints are open. |
| **Migration risk** | **M** — a large surface, but conventional wiring. |
| **Target state** | Split `api_routes.py` by sub-router into `server/routers/*.py`. Typed Pydantic models on every action endpoint. One approval endpoint, not two. |

### 8.11 CLI

| | |
|---|---|
| **Canonical candidate** | `cli/` — 63 modules, 18,722 LOC, 51 lazily-imported commands via `cli.add_command(_lazy(...))`. |
| **Duplicates** | `grandpa model` and `grandpa models` are two separate commands. `cli/scan_cmd.py` defines a second `ScanResult`. |
| **Consumers** | Entry point `grandpa = "grandpa.cli:main"`. |
| **Dependencies** | Second-widest fan-out: `core` (79), `agent` (24), `engine` (19), `voice` (18), `intelligence` (14), `tools` (14), `agents` (11). Cycles with `voice`, `projects`, `server`, `tray`. |
| **Problems** | `chat_cmd.py` (2,156 LOC) mixes dispatch, slash-command parsing, memory formatting, and Rich rendering, with the 4-call side-effect block repeated ~15×. `cli` ↔ `voice` cycle. Pre-remediation, a PyPI network call fires on nearly every invocation. |
| **Migration risk** | **M** for `chat_cmd.py` (primary UX, 43 test files behind it); **L** elsewhere. |
| **Target state** | Lazy loading and the `safe_output` / `theme` / `hints` presentation modules preserved as-is. `chat_cmd.py` splits into `chat/dispatch.py`, `chat/slash.py`, `chat/render.py` once `IntentDispatcher` exists. |

### 8.12 MCP / SDK / A2A / workflow

| | |
|---|---|
| **Canonical candidate** | `mcp/` (5 modules, 885 LOC — client, server, protocol, transport, bridge; stdio / SSE / StreamableHTTP) and `sdk.py` (653 LOC — `Grandpa`, `GrandpaSystem`, `MemoryHandle`, `SystemBuilder`), both live and wired via `system/builder.py:339-465`. |
| **Duplicates** | `workflow/` overlaps `planner/` and `agent/execution/`. |
| **Consumers** | `mcp` ← `tools` (11 edges, bidirectional). `sdk` ← `grandpa/__init__.py` (the only public API). **`a2a/` ← nothing in `src/`; 1 test file only.** |
| **Dependencies** | `mcp` → `tools`; `sdk` → `tools`, `core`, `system`. |
| **Problems** | The MCP *server* is a third-party plugin runtime that the README says does not exist. `a2a/` is 460 LOC of dead code that nonetheless has a live `A2AConfig` section in `GrandpaConfig`. Neither MCP nor the SDK has a documentation page. |
| **Migration risk** | **L** — `a2a/` removal touches one test; MCP/SDK need docs, not surgery. |
| **Target state** | Archive `a2a/` and its config section. Document MCP and the SDK, or restrict the MCP server behind explicit opt-in. Answer Q-A2 first. |

### 8.13 Security

| | |
|---|---|
| **Canonical candidate** | `security/` (18 modules, 2,391 LOC). |
| **Duplicates** | `SecurityBlockError` in both `boundary.py` and `guardrails.py` **within the same package**. `SecurityContext` in `security/__init__.py` and `system/bundles.py`. `ScanResult` in `security/types.py` and `cli/scan_cmd.py`. |
| **Consumers** (external to `security/`) | `file_policy` 6 · `ssrf` 3 · `capabilities` 3 · `audit` 2 · `boundary` 2 · `scanner` 1 · `signing` 1 · `injection_scanner` 1 (a JSON converter in `_rust_bridge`, not a real use) · **`guardrails` 0** · **`rate_limiter` 0** · **`severity_policy` 0** · **`subprocess_sandbox` 0** · **`merkle` 0**. |
| **Dependencies** | → `_rust_bridge` (10 edges), `core` (8). |
| **Problems** | Five modules with zero consumers, including the ones whose config keys are documented as protections. Nine `SecurityConfig` keys are read nowhere outside `core/config.py`. `subprocess_sandbox.py:111` uses `shell=True` in the module named "sandbox". Capability RBAC fails **open**. Injection scanning never runs on any ingestion point, despite the assistant consuming screen OCR, browser text, web-search results, and file contents. |
| **Migration risk** | **L** to delete; **M** to wire — wiring `rate_limiter` and `injection_scanner` changes runtime behaviour. |
| **Target state** | One `PolicyEngine` merging the NL and API risk models. Injection scanning at every untrusted-ingress point. Capability policy fail-closed. Every remaining module either wired or deleted — **no third state.** |

### 8.14 Configuration

| | |
|---|---|
| **Canonical candidate** | `core/config.py` (1,302 LOC, 26 nested sections). Precedence: CLI flags → env → `~/.grandpa/config.toml` → dataclass defaults. `validate_config_key()` walks `dataclasses.fields()`. Back-compat shims (`cfg.memory` → `cfg.tools.storage`), legacy `[memory]` remapping, `GRANDPA_HOME` override. |
| **Duplicates** | `voice/config.py` and `screen/config.py` are parallel config surfaces outside the schema. |
| **Problems** | **The schema models the inherited platform, not the product** (§2.2 B3) — no section exists for desktop, screen, automation, vision, or voice. Nine security keys are inert. `.env` is documented but never loaded (no `python-dotenv` dependency). 74 env vars are read across `src/`; `.env.example` documents ~15. `Grandpa_API_KEY` breaks the `GRANDPA_*` convention. A live `[voice]` section exists that the schema does not know about. `A2AConfig` exists for a dead package. |
| **Migration risk** | **L** — additive sections are cheap; the validator already walks fields generically. |
| **Target state** | Add `DesktopConfig`, `ScreenConfig`, `AutomationConfig`, `VoiceConfig`, `VisionConfig`. Remove `A2AConfig`. Wire or delete the nine inert security keys. Resolve `.env` (implement or remove). |

### 8.15 Telemetry / observability

| | |
|---|---|
| **Canonical candidate** | `core/events.py` `EventBus` + `telemetry/` (aggregator, store, wrapper, instrumented_engine) + `traces/` (collector, store, analyzer). |
| **Duplicates** | The Windows layer has its **own** audit path: `pc_control` audit (sqlite + jsonl), `local_action_approvals.db`, `security/audit.py`, `desktop/kernel/audits.py`. |
| **Consumers** | Event-bus publishers: `a2a, agents, cli, connectors, core, kernel, scheduler, sdk, security, server, skills, system, telemetry, tools, traces, workflow`. |
| **Problems** | **`local_actions.py` and `pc_control.py` publish zero events.** `EventType` has no desktop / window / screen / voice members. The two observability systems do not meet: you cannot obtain one timeline covering "user said X → policy allowed → keyboard typed → window changed". |
| **Migration risk** | **L** — adding event types and publish calls is additive and non-breaking. |
| **Target state** | One event bus. Extend `EventType` with desktop / screen / voice / policy members. The Windows-layer audit becomes an *event-bus subscriber*, not a parallel path. **[FACT] Local-only telemetry holds** — zero network calls in `telemetry/` or `traces/`, verified by grep. Preserve that. |

### 8.16 Testing architecture

| | |
|---|---|
| **Canonical candidate** | `tests/` — 349 files, 69,587 LOC, ~4,234 test functions, 30 sub-directories mirroring the **platform** packages. `conftest.py` clears 12 registries and resets the event bus per test (correct isolation design). |
| **Duplicates** | 84 flat root-level `test_*.py` files covering the assistant, with no mirrored package structure. |
| **Problems** | **CI runs `ubuntu-latest` only** — the Windows-only product's core (pywin32, UIA, SAPI, pyautogui, window control) is never exercised in CI. CI selects 18 of 349 files and gates at `--cov-fail-under=20`. 12 markers are declared in `pyproject.toml`; only `live` is used as a decorator — everything else is applied programmatically against hardcoded path lists in `conftest.py`, and anything unlisted defaults to `core`. **The `microphone` marker is declared and never applied**, which is exactly why two voice tests hang forever. `pytest-timeout` is not a dependency. Cross-test state leakage is demonstrated (a Whisper test receives another test's output). No end-to-end test exercises chat → handler chain → action. |
| **Migration risk** | **L** to add a Windows runner; **M** to fix isolation. |
| **Target state** | A `windows-latest` job running the assistant suites. A real marker taxonomy driven by decorators, not path lists. `pytest-timeout` with a default bound. Mirror `tests/` structure to `src/` for the assistant packages too. **A green `windows-latest` build is a hard prerequisite for §8.6, §8.7, and §8.8 work.** |

### 8.17 Python / Rust boundary

| | |
|---|---|
| **Canonical candidate** | `_rust_bridge.py` (180 LOC) — the declared single point of contact. |
| **Duplicates** | None. |
| **Consumers** | 16 modules: `security/{scanner,ssrf,file_policy,capabilities,injection_scanner,rate_limiter}`, `tools/{calculator,file_read,file_write,git_tool,http_request,shell_exec,think}`, `tools/storage/{bm25,sqlite}`, `agents/loop_guard`. |
| **Problems** | The bridge's own contract is false: the docstring says "mandatory ... no Python fallback"; `RUST_AVAILABLE: bool = True` is hardcoded; every consumer falls back. `docs/architecture/domain-architecture.md` states the opposite. `tools/shell_exec.py` is the one Rust-first call site and it silently changes semantics. |
| **Migration risk** | **L** — nothing depends on Rust at runtime, so the boundary can be made honest with zero behavioural change. |
| **Target state** | Per [DECISION B]: honest bridge, no Rust-first paths, workspace archived, CI jobs removed. |

### 8.18 Dead / near-dead inventory

| Component | LOC | `src/` consumers | Evidence |
|---|---:|---:|---|
| `rust/` | 27,035 | 0 at runtime | Not in wheel; every call site falls back; 18 lines changed in 3 months |
| `kernel/` | 3,272 | 1 (`files/kernel_adapter.py`) | Docstring claims a canonicity it never received |
| `a2a/` | 460 | **0** | 1 test file; a live `A2AConfig` section for a dead package |
| `security/guardrails.py` | 317 | **0** external | Only reachable via `setup_security()` internal wiring |
| `security/injection_scanner.py` | 167 | 1 (a JSON converter) | Never runs on any ingress |
| `security/subprocess_sandbox.py` | 143 | **0** | Uses `shell=True` |
| `security/rate_limiter.py` | 113 | **0** | `rate_limit_enabled = True` ships as a default and does nothing |
| `security/severity_policy.py` | 22 | **0** | |
| `templates/`, `daemon/` | 149 | **0** | |
| `.dockerignore` | — | — | No Dockerfile exists anywhere in the tree |

**Total inherited / dead: ~31,600 LOC** (Rust 27,035 + `kernel/` 3,272 + `a2a/`
460 + unwired security ~760 + `templates`/`daemon` 149).

---

## 9. Security boundaries (as built)

**[FACT]** There are **two disjoint policy models** guarding the same actuators.

**Natural-language path** (`local_actions.py`):
`_normalise()` → `_is_dangerous()` (37-regex denylist) → allowlist parsers
(app / folder / url / window / screen / browser / pc_control / automation /
skill) → `classify_permission()` → `{allowed | requires_confirmation | blocked}`
→ `LocalActionApprovalStore` (pending, TTL, audit) → `_execute()` →
`desktop.control.*`.

**Structured API path** (`pc_control.py` → `desktop/kernel/risk.py`):
`classify()` → `{LOW | MEDIUM | HIGH | BLOCKED}` → `requires_approval = HIGH or
caller-requested` → **post-remediation:** `+ APPROVAL_REQUIRED_ACTIONS` (an
orthogonal set that gates `keyboard_type` / `keyboard_hotkey` / `mouse_*`
regardless of tier) → `_preflight_guard()` (protected paths, protected active
window) → `_execute()`.

**[FACT]** The two models share no code, no vocabulary
(`allowed / confirm / blocked` vs `LOW / MEDIUM / HIGH / BLOCKED`), and no
approval store (`local_action_approvals.db` vs `pc_control_approvals.db`). A
rule added to one does not exist in the other.

**[FACT]** Boundaries that **hold** and must be preserved:

1. **Deterministic-first.** Model output never becomes an action — verified at all four call sites. The single most important property in the codebase.
2. **Default-deny risk classification.** Unrecognised action → `BLOCKED`.
3. **Allowlist + denylist defence in depth.** A paraphrase that dodges the denylist lands in the allowlist parser and returns `no_match`, not an action.
4. **Path-traversal handling.** `_normalised_path_parts` resolves before protection checks; `open_folder` requires `is_dir()`.
5. **Redaction in `screen/`, `vision/`, `automation/locator.py`** (7 pattern classes).
6. **SSRF protection** in `tools/http_request.py`, `browser.py`, `web_search.py`.
7. **Local-only telemetry** — zero network egress, verified by grep.
8. **Bind safety** — `check_bind_safety()` refuses non-loopback binds without a key.
9. **Credential-stripping log formatter** on the `grandpa` logger.
10. **Out-of-process F5 voice runtime** — a genuine process boundary that also keeps `torch` out of the main venv.

**[FACT]** Boundaries that **do not hold**:

1. Two policy models (above) — a rule in one is absent from the other.
2. Capability RBAC fails **open**: `CapabilitiesConfig.enabled = False`, `CapabilityPolicy(default_deny=False)`, and `_check_python` returns `not self._default_deny` when a policy exists but no grant matches.
3. **No redaction on any browser path** — the largest untrusted-content ingress.
4. **No injection scanning anywhere** — the module exists and is unwired.
5. **No rate limiting** — the module exists, the config key ships `True`, nothing reads it.
6. `tools/shell_exec.py` Rust path bypasses env sanitisation and timeout (inert only because Rust is never built).
7. Only the `grandpa` logger is sanitised; uvicorn / FastAPI logs are not.
8. `security/subprocess_sandbox.py` uses `shell=True`.
9. **Pre-remediation only:** all 179 endpoints unauthenticated; `keyboard_type` / `keyboard_hotkey` MEDIUM with no approval; approval by action-id alone. **All four are fixed on `claude/grandpa-codebase-audit-bf609c` and unfixed on `main`.**

---

## 10. Current architecture in one paragraph

**[FACT]** Grandpa is a working Windows-first local AI assistant, built over
three months on top of a rebranded upstream agent platform (OpenJarvis, itself
derived from IPW). The inherited platform supplies the config schema, the typed
registries, the event bus, the tool and agent frameworks, the model-runtime
abstraction, and the security scanners — all of which the assistant genuinely
uses. The assistant itself was written as flat top-level modules *alongside*
those packages rather than inside them, which is why the six largest files in
the repository are un-packaged modules combining parsing, policy, and execution.
The result is a system with one excellent invariant (model output never becomes
an action), one excellent module (`core/config.py`), one very clean subsystem
(`screen/`), and one dominant structural defect: **no dispatcher** — which
produces six divergent entry points, two disjoint policy models, two
non-communicating observability planes, and five parallel voice paths. Roughly
31,600 LOC (the Rust workspace, `kernel/`, `a2a/`, and five unwired security
modules) is inherited infrastructure for a product direction abandoned at the
rebrand and never formally retired.

---

**Next:** `TARGET_ARCHITECTURE.md` · `ARCHITECTURE_DECISIONS.md` ·
`MODULE_OWNERSHIP.md` · `ARCHITECTURE_GAPS.md` · `MIGRATION_PLAN.md`
