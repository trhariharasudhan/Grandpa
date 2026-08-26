# Grandpa — Migration Plan

**Status:** Proposed. **No migration step has been started. No source, test,
config, CI, or runtime file has been modified.**
**Date:** 2026-08-26
**Supersedes:** the 2026-08-26 discovery draft. Revised for AD-019 (licensing
resolved — now Phase 0), AD-020 (`agent/development/` **retained**, removed from
all archive lists), AD-021 (per-database dispositions), and AD-022 (origin
tagging added to Phase 4).

Tag legend is in `CURRENT_ARCHITECTURE.md`.

---

## 0. Ground rules

1. **One structural change per pull request.** The dependency graph only holds
   if changes are individually revertible.
2. **Additive before subtractive.** Introduce the new owner, migrate consumers,
   *then* remove the old one — never both in one change.
3. **Every deprecation shim carries a removal release.** A shim with no removal
   date becomes a second live implementation. That is how most of the 31
   duplicate class names came to exist.
4. **No Windows-layer refactor without a green Windows CI job.**
5. **Characterisation tests before behaviour-preserving refactors.** For
   `local_actions.py`, `pc_control.py`, and `chat_cmd.py`, pin current behaviour
   *first*.
6. **Answer the blocking question before starting a phase that depends on it.**

---

## 1. Phase overview

| Phase | Name | Duration | Gate | Risk | Breaking |
|---|---|---|---|---|---|
| **0** | Baseline + legal compliance | 1–2 days | — | L | No |
| **1** | Close the safety gaps | 3–5 days | 0 | M | Partly |
| **2** | Make the tree honest | 3–5 days | 0 | L | No |
| **3** | Make the suite trustworthy | 1 week | 0 | M | No |
| **4** | Unify dispatch and policy | 2–4 weeks | 0–3 | **H** | **Yes** |
| **5** | Consolidate subsystems | 3–5 weeks | 4 | **H** | **Yes** |
| **6** | Memory redesign | 1–2 weeks | 5 | **H** | **Yes** |
| **7** | Decomposition and hygiene | ongoing | 5 | L–M | No |

**Total before new feature work: 8–12 weeks.** Phases 1–3 are parallelisable;
4–6 are strictly sequential.

---

## 2. Phase dependency graph

```
                    ┌────────────────────────────────────┐
                    │ PHASE 0 — Baseline + legal         │
                    │ merge stabilization · AD-019 NOTICE│
                    └─────────────────┬──────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────────┐
│ PHASE 1           │   │ PHASE 2           │   │ PHASE 3               │
│ Safety gaps       │   │ Honest tree       │   │ Trustworthy suite     │
│ browser redaction │   │ fix contracts     │   │ ★ windows-latest CI ★ │
│ injection scan    │   │ archive dead code │   │ pytest-timeout        │
│ RBAC fail-closed  │   │ config sections   │   │ real markers          │
│ shell_exec Rust   │   │ collapse engine/  │   │ daemon-thread leak    │
│ unified event bus │   │ orphaned DBs      │   │ 13 stale failures     │
└─────────┬─────────┘   └─────────┬─────────┘   └───────────┬───────────┘
          │                       │                         │
          └───────────────────────┴────────────┬────────────┘
                                               ▼
                          ┌──────────────────────────────────────┐
                          │ PHASE 4 — Dispatch + Policy          │
                          │ IntentDispatcher · PolicyEngine      │
                          │ origin tagging (AD-022) · e2e tests  │
                          │ ★ HARD GATE: Windows CI green ★      │
                          └───────────────────┬──────────────────┘
                                              ▼
                          ┌──────────────────────────────────────┐
                          │ PHASE 5 — Subsystem consolidation    │
                          │ voice · browser · agents · screen    │
                          └───────────────────┬──────────────────┘
                                              ▼
                          ┌──────────────────────────────────────┐
                          │ PHASE 6 — Memory redesign            │
                          │ ★ HARD GATE: approval + migration ★  │
                          └───────────────────┬──────────────────┘
                                              ▼
                          ┌──────────────────────────────────────┐
                          │ PHASE 7 — Decomposition, hygiene     │
                          └──────────────────────────────────────┘
```

**Critical path:** 0 → 3 → 4 → 5 → 6.

---

## PHASE 0 — Baseline and legal compliance

**Objective.** One branch, one truth, an importable package, and a repository
that states its own provenance honestly.

### Modules / files affected

| File | Change |
|---|---|
| *(merge)* `claude/grandpa-codebase-audit-bf609c` → `main` | 73 files, +4,400 / −925 |
| `LICENSE` | Restore upstream copyright line alongside the current one |
| `NOTICE` | **Create** — attribute OpenJarvis and IPW, Apache-2.0, and the derivative status |
| `README.md` | Add "Origins" section (2 sentences) |
| `.github/CODEOWNERS` | Replace 3 upstream handles with the actual owner |
| `voice_runtime/README.md` | Record the ffmpeg build provenance URL |
| `docs/architecture/ARCHITECTURE_BASELINE.md` | Create, or record that it never existed |

### Steps

| # | Step | Notes |
|---|---|---|
| 0.1 | Merge the stabilization branch into `main` | **Merge, do not rebase** |
| 0.2 | Verify: fresh `git clone` → `uv sync` → `grandpa doctor` → `pytest --co` | Expect 0 collection errors (was 56) |
| 0.3 | `git check-ignore -v src/grandpa/runtime/interface.py` prints nothing | |
| 0.4 | **AD-019:** restore `LICENSE` line, create `NOTICE`, README Origins, fix `CODEOWNERS` | |
| 0.5 | Record ffmpeg provenance URL | |
| 0.6 | Re-cut the architecture branch from the merge commit | |
| 0.7 | Move `AUDIT.md` onto `main` | Currently only on the stabilization branch |

**Dependencies.** None. This is the root of the graph.

**Risk.** **L.** 0.1 is a merge with possible conflicts across 73 files. 0.4–0.5
are text files with zero code impact.

**Tests required.** No new tests. Verification is 0.2 and 0.3 — a clean-clone
install and collection run. Existing suite must be no worse than the
stabilization branch baseline.

**Rollback.** 0.1: `git revert -m 1 <merge-commit>`, or reset the branch — the
stabilization branch remains intact and unmodified. 0.4–0.7: revert individual
file commits; nothing depends on them.

**Expected result.** `main` imports from a clean clone. `grandpa doctor` runs.
Attribution is compliant with Apache-2.0 §4. One baseline branch.

**Breaking change?** **No.** Zero API, CLI, config, or behavioural change.

**Blocking question.** **Q-3a** — is upstream OpenJarvis still public and still
Apache-2.0? Affects the NOTICE wording only, not whether to write one.

> **Why AD-019 is here and not Phase 2 (changed from the draft):** the repository
> is published at `github.com/trhariharasudhan/Grandpa`, so distribution is
> already occurring and every day is a day of non-compliance. It is also the
> cheapest item in the plan — under an hour, no code.

---

## PHASE 1 — Close the safety gaps

**Objective.** Fix the four correctness/safety defects that do not depend on any
structural work, and unify the observability plane while it is still cheap.

### Modules / files affected

| # | Step | Files | Closes |
|---|---|---|---|
| 1.1 | Apply `redact_screen_text` at every browser extraction boundary | `browser_intelligence/{content_extractor,page_reader,summarizer,page_analyzer}.py`, `browser_awareness/{capture,parser}.py`, `browser/parser.py`, `browser_control.py` | GAP-04 |
| 1.2 | Wire `security/injection_scanner.py` at untrusted ingress | `screen/ocr.py`, `browser/read`, `files/`, `web_search/`, `mcp/client.py` | GAP-05 |
| 1.3 | `capabilities._check_python` fails **closed** | `security/capabilities.py` | GAP-06 |
| 1.4 | Remove the Rust-first path | `tools/shell_exec.py:126-140` | GAP-20 |
| 1.5 | Extend `EventType`; publish from the Windows layer | `core/events.py`, `local_actions.py`, `pc_control.py`, `desktop/control/*` | GAP-09 |
| 1.6 | Re-verify zero telemetry egress after 1.5 | `telemetry/`, `traces/` | P11 |
| 1.7 | Credential-stripping formatter on uvicorn/FastAPI loggers | `cli/log_config.py`, `server/app.py` | GAP-24 |

**Dependencies.** Phase 0 only. Runs in parallel with Phases 2 and 3.
1.6 depends on 1.5.

**Risk.** **M overall; L for 1.1, 1.4, 1.5, 1.7.**
- 1.2 is the risky one — scanning can produce false positives that block real
  work.
- 1.3 deliberately breaks partially-specified capability policies. That is the
  intent, but it is a behaviour change.

**Tests required.**

| Step | Test |
|---|---|
| 1.1 | Assert a synthetic page containing a fake token/OTP/card number is redacted before it reaches logs or prompt assembly — one test per extraction path |
| 1.2 | Assert flagged content produces the configured response; assert clean content is unaffected (false-positive guard) |
| 1.3 | Assert a policy that exists with **no matching grant** now **denies**. Regression-test the fail-open case explicitly. |
| 1.4 | Assert `shell_exec` honours timeout and sanitised env, and returns the real return code |
| 1.5 | Assert one end-to-end event timeline exists for a `dry_run` desktop action |
| 1.6 | Re-run the egress grep as an automated assertion |

**Rollback.** Each step is an independent PR. 1.2 ships behind a config flag
defaulting to log-only, so rollback is a config change, not a revert. 1.3 is the
only one needing a real revert if it breaks a user's policy.

**Expected result.** Browser text is redacted on every path. Untrusted content is
scanned. Capability policy fails closed. No Rust-first execution path. A single
event-bus timeline covers a desktop action end to end.

**Breaking change?** **Partly.** 1.3 is intentionally breaking for anyone with a
partial capability policy. 1.2 may change behaviour depending on Q-6. 1.1, 1.4,
1.5, 1.7 are non-breaking.

**Blocking question.** **Q-6** — what happens on a flag: log, warn, or block?
And at what rate-limit thresholds? Only 1.2 needs this.

**[RECOMMENDATION]** Order within the phase: **1.4 → 1.1 → 1.5 → 1.7 → 1.3 →
1.2.** The first four are low-risk with immediate value and no open questions.

---

## PHASE 2 — Make the tree honest

**Objective.** Every docstring, constant, config key, and doc page states
something true. Dead inherited code leaves the tree.

### Modules / files affected

| # | Step | Files | Closes |
|---|---|---|---|
| 2.1 | Fix false contracts | `_rust_bridge.py` (docstring, `RUST_AVAILABLE`), `kernel/__init__.py`, `memory_context.py` (`SEMANTIC_MODEL`) | GAP-20 |
| 2.2 | Correct product description | `pyproject.toml:8`, `src/grandpa/__init__.py:1` | GAP-20 |
| 2.3 | Reconcile docs with code | `README.md` (`.env`, `qwen2.5:3b`), `docs/development/repo-structure.md`, `CHANGELOG.md`, `mkdocs.yml`, `docs/architecture/overview.md` | GAP-24 |
| 2.4 | Document MCP, SDK, agent runtime; add `agent/development/` pages to `nav:` | `docs/user-guide/*`, `mkdocs.yml` | GAP-24, AD-020 |
| 2.5 | Wire or delete the 9 inert `SecurityConfig` keys | `core/config.py:537-559` | GAP-19 |
| 2.6 | Delete zero-consumer security modules | `security/subprocess_sandbox.py`, `security/severity_policy.py` | GAP-17 |
| 2.7 | Add product config sections; remove `A2AConfig` | `core/config.py` | GAP-18 |
| 2.8 | Collapse `engine/` into `runtime/` | `engine/*` → `runtime/`; 44 import sites across 11 packages | GAP-16 |
| 2.9 | **Archive** `rust/`, `a2a/`, `templates/`, `daemon/`; remove `rust` CI job + `maturin develop` | `rust/`, `src/grandpa/{a2a,templates,daemon}/`, `.github/workflows/ci.yml`, `pyproject.toml` | GAP-17 |
| 2.10 | Delete generated dumps and dead config | `grandpa_tree.txt`, `grandpa_project_structure.txt`, `.dockerignore` | GAP-26 |
| 2.11 | **AD-021** orphaned databases: archive 2, delete 4, secure-delete 1 | `~/.grandpa/*.db` (7 files) + `tests/conftest.py` stale path | AD-021 |

**Dependencies.**
- 2.8 requires Phase 0 (`runtime/` must be tracked).
- 2.9 requires **AD-019 complete in Phase 0** — the archive must inherit correct
  attribution, not propagate the defect.
- 2.11 requires **approval A-4** and is the only step touching the user's
  runtime directory.

**Risk.** **L.** 2.1–2.4, 2.10 are text. 2.6 and 2.9 remove code with zero
consumers. 2.8 is 44 mechanical, test-covered import edits. 2.11 is L *because*
the audit is done — five databases contain no user data and two are archived
before deletion.

**Tests required.**

| Step | Test |
|---|---|
| 2.5 | For each key wired: assert it takes effect. For each deleted: assert `validate_config_key()` rejects it. |
| 2.7 | Assert new sections round-trip through TOML and that `validate_config_key()` accepts them |
| 2.8 | Full existing suite must pass unchanged — this is behaviour-preserving. Add an import test asserting `grandpa.engine` still resolves via the shim. |
| 2.9 | Assert `import grandpa` and `grandpa doctor` succeed with `rust/` absent; assert the 16 `_rust_bridge` consumers still work |
| 2.11 | None — no code path references these databases. Verify by re-running the reference grep. |

**Rollback.** 2.9: `git revert` restores the tree; the archive branch is
independent. 2.8: the `grandpa.engine` shim means consumers keep working, so
rollback is a single revert. 2.11: **the archive copies are the rollback** —
which is why 2 of the 7 are archived rather than deleted.

**Expected result.** ~31,300 LOC leaves the main tree with history and
attribution preserved. Zero inert config keys. Zero dishonest contracts. `rust`
CI job gone (it was red). 152 KB of orphaned runtime state resolved.

**Breaking change?** **No**, with one nuance: 2.8 changes the canonical import
path, but `grandpa.engine` remains a working shim for one release. 2.2 changes
package metadata text only.

**Blocking questions.** **Q-3a** (NOTICE wording, from Phase 0), **Q-2** (gates
2.4's MCP decision), **Q-8** (PyPI — gates whether `autotag.yml` /
`pypi-publish.yml` / `self-update` are fixed or removed).

**[RECOMMENDATION]** 2.1–2.3 on day one. Zero code risk, and they stop the
repository misleading every future reader — human or automated.

---

## PHASE 3 — Make the suite trustworthy

**Objective.** A test suite that terminates, exits 0, and exercises the product
on the product's platform. **This phase gates Phases 4–6.**

### Modules / files affected

| # | Step | Files | Closes |
|---|---|---|---|
| 3.1 | Add `pytest-timeout`; set a default bound | `pyproject.toml` | GAP-08 |
| 3.2 | Apply the declared-but-unused `microphone` marker | `tests/cli/test_voice_operator_cmd.py:7,16`, `tests/conftest.py` | GAP-08, GAP-23 |
| 3.3 | Fix the daemon-thread leak (exit 127 → 0/1) | `voice/`, `speech/`, `scheduler/` shutdown paths | GAP-08 |
| 3.4 | Fix the 13 stale failures | `tests/cli/`, `tests/speech/`, `tests/test_voice_*` | — |
| 3.5 | Fix cross-test state leakage | `tests/speech/test_faster_whisper.py`, `tests/conftest.py` | — |
| 3.6 | Replace hardcoded path lists with decorators across all 12 markers | `tests/conftest.py`, all test files | GAP-23 |
| 3.7 | **Add `windows-latest` CI job** | `.github/workflows/ci.yml` | **GAP-07** |
| 3.8 | Run the full deterministic suite, not 18 hand-listed files | `.github/workflows/ci.yml` | GAP-07 |
| 3.9 | Raise `--cov-fail-under` stepwise; measure assistant packages separately | `.github/workflows/ci.yml`, `pyproject.toml` | GAP-07 |

**Dependencies.** Phase 0. 3.8 depends on 3.1–3.5 (the suite must terminate
before it can be run in full). 3.7 depends on 3.1–3.2.

**Risk.** **M.** 3.7 will surface a large batch of previously-unrun failures at
once — that is the point, but it must be planned for rather than treated as a
regression. 3.3 touches shutdown paths in the most fragile subsystem.

**Tests required.** This phase *is* the tests. Verification criteria:

| Criterion | Measure |
|---|---|
| Suite terminates | `pytest` returns within the timeout, no hang |
| Exit code | 0 or 1, never 127 |
| Windows job | Green on the assistant suites |
| Markers | Every test's markers come from decorators; `pytest -m microphone` selects exactly the hardware tests |
| Isolation | Running any single test file in isolation gives the same result as in the full suite |

**Rollback.** 3.7–3.9 are CI-only; revert the workflow file. 3.3 is the only
source change and should be a separate PR from the CI work.

**Expected result.** `pytest` terminates and exits 0. `windows-latest` green.
Real marker taxonomy. **The gate for all structural work opens.**

**Breaking change?** **No.** Tests and CI only. No `src/` change except 3.3's
shutdown handling.

> **Why this gates Phases 4–6:** every subsequent phase refactors Windows-only
> code that CI has never executed. Without 3.7, a passing build proves nothing
> about the code that actually changed.

---

## PHASE 4 — Unify dispatch and policy

**Objective.** One dispatcher, one policy engine, origin-tagged actions. The
highest-value and highest-risk phase.

### Modules / files affected

| # | Step | Files | Closes |
|---|---|---|---|
| 4.1 | Characterisation tests pinning all six chains | `tests/dispatch/` **(new)** | GAP-22 |
| 4.2 | Resolve duplicate domain types | `core/types.py`, `planner/models.py`, `kernel/models.py`, `advanced_ai.py`, `smart_automation.py` | GAP-11 |
| 4.3 | Break the four single-edge `core →` back-edges | `core/{config,types,registry,events}.py` | GAP-10 |
| 4.4 | Introduce `grandpa/dispatch/` **additively** | `dispatch/{__init__,protocol,registry,context}.py` **(new)** | GAP-02 |
| 4.5 | Migrate `ask` (5 handlers — smallest) | `cli/ask.py` | GAP-02 |
| 4.6 | Migrate HTTP surfaces | `server/routes.py`, `server/api_routes.py` | GAP-02 |
| 4.7 | Migrate `chat` (28 handlers, 43 test files) | `cli/chat_cmd.py` | GAP-02 |
| 4.8 | Migrate both voice surfaces | `voice/assistant.py`, `voice/operator.py` | GAP-02 |
| 4.9 | Migrate the 3 bypass surfaces | `voice/session.py`, `task_scheduler.py`, `cli/jarvis_cmd.py` | GAP-02 |
| 4.10 | End-to-end test per surface asserting **identical** capability sets | `tests/dispatch/test_parity.py` **(new)** | GAP-22 |
| 4.11 | Introduce `grandpa/policy/` merging both funnels | `policy/{engine,models,store}.py` **(new)**, `local_actions.py`, `desktop/kernel/risk.py` | GAP-03 |
| 4.12 | **AD-022:** add `origin` to `ActionRequest`; thread it from every call site; record in audit | `policy/models.py`, all 24 funnel call sites, `security/taint.py`, `core/events.py` | AD-022 |
| 4.13 | One approval store, out-of-band code | `local_action_approvals.db` + `pc_control_approvals.db` → one | GAP-03 |
| 4.14 | Wire `rate_limiter` into `PolicyEngine` | `security/rate_limiter.py`, `policy/engine.py` | GAP-19 |
| 4.15 | Break `pc_control ↔ desktop` (27/16) | `pc_control.py` → thin surface over `policy/` + `desktop/` | GAP-10 |
| 4.16 | CI dependency-direction check (rules D1–D8) | `.github/workflows/ci.yml`, `tests/architecture/test_imports.py` **(new)** | GAP-10 |

**Dependencies.**
- **Hard gate: Phase 3.7 green.** Three of six surfaces are Windows-only.
- 4.5 → 4.6 → 4.7 → 4.8 → 4.9 is strictly ordered, smallest to largest.
- 4.11 depends on 4.4 (the dispatcher is where policy is invoked).
- 4.12 depends on 4.11.
- 4.15 depends on 4.11 (the cycle exists *because* `pc_control` holds policy).
- 4.2 should land before 4.4 — you cannot unify chains that speak different types.

**Risk.** **H.** The three specific dangers:

| Danger | Mitigation |
|---|---|
| The dispatcher silently changes behaviour | 4.1 characterisation tests **before** 4.4; one surface per PR |
| `PolicyEngine` weakens a guard while merging two tables | Port the post-remediation orthogonal design; never re-derive tiers from scratch. Diff the resulting table against both originals, action by action. |
| Origin threading misses a call site, defaulting to `user` | Make `origin` a **required** field with no default. A missed call site becomes a type error, not a silent privilege escalation. |

**Tests required.**

| Step | Test |
|---|---|
| 4.1 | For each of the six chains: record handler order and outcome for a fixed corpus of ~30 inputs. These become the regression baseline. |
| 4.5–4.9 | After each migration, the corresponding characterisation test must pass **unchanged** |
| 4.10 | **Parity test:** assert all surfaces expose the same handler set (modulo declared filters). This is what makes GAP-02 unfixable-by-regression. |
| 4.11 | For every action in both original tables, assert the merged engine produces a decision **at least as strict** as the stricter original |
| 4.12 | Assert an action from `origin=skill` and one from `origin=user` are distinguishable in the audit record; assert the `SkillTool` → `_pc_action` path tags `origin=skill` |
| 4.13 | Assert an action staged over channel A cannot be approved without the out-of-band code |
| 4.14 | Assert throttling engages at the configured threshold |
| 4.16 | Assert zero package import cycles; assert `core/` imports nothing from `grandpa.*` |

**Rollback.** Each surface migration (4.5–4.9) is an independent PR revertible on
its own, because 4.4 is **additive** — the dispatcher runs alongside the existing
chains until each surface is cut over. 4.11 ships behind a flag that routes to
either the new `PolicyEngine` or the two legacy classifiers, with a comparison
mode logging disagreements before the switch. 4.13 is the hardest to roll back
(store merge) and should be last within the phase.

**Expected result.** All six surfaces plus the three bypasses resolve through one
dispatcher and expose the same capability set, proven by a parity test. All
actions classify through one origin-aware policy engine into one approval store.
Zero package import cycles, CI-enforced.

**Breaking change?** **Yes.**
- Surfaces gain handlers they did not have (`ask` gains 9, HTTP gains 10). That
  is the goal, but it changes API behaviour.
- Approval-token semantics change (out-of-band code required).
- The approval store merge changes the on-disk format → **needs a migration
  step**, and it should be listed in release notes.
- `pc_control.py`'s public surface narrows.

**Blocking questions.** **Q-6** (4.14 thresholds), **Q-10** (should
agent/skill-originated actions require approval at a lower threshold? — shapes
4.12's policy table).

---

## PHASE 5 — Consolidate subsystems

**Objective.** One owner per concern. Zero duplicate domain class names.

### Modules / files affected

| # | Step | Files | Risk |
|---|---|---|---|
| 5.1 | Five voice paths → one `VoiceSession`; retire `jarvis/` | `voice/{assistant,operator,session,cli_session,loop}.py`, `jarvis/` | **H** |
| 5.2 | Four browser packages → one `browser/` | `browser_control.py`, `browser/`, `browser_intelligence/`, `browser_awareness/` | M |
| 5.3 | Retire `screen_awareness.py`; resolve `OcrResult`/`MonitorInfo`/`WindowInfo` | `screen_awareness.py`, `desktop_context.py`, `screen/models.py` | M |
| 5.4 | Absorb `windows_app_resolver.py` into `apps/resolver.py` | 4 importers | M |
| 5.5 | Absorb `task_scheduler.py` into `scheduler/`; resolve `SchedulerStore` | 13 importers | M |
| 5.6 | Absorb `agent/{executor,context,models,runtime}.py` into `agents/` — **`agent/development/` EXCLUDED (AD-020)** | 5 colliding type names | **H** |
| 5.7 | Absorb `agent/execution/` into `planner/`; decide `workflow/` | `agent/execution/`, `planner/`, `workflow/` | M |
| 5.8 | Fold `files/kernel_adapter.py` into `files/`; retire `tests/kernel/`; **archive `kernel/`** | `kernel/` (3,272 LOC), 8 test files | M |
| 5.9 | Rename `desktop/kernel/` → `desktop/execution/` | Free once 5.8 lands | L |
| 5.10 | Absorb `windows_window_control.py` into `desktop/control/windows.py` | 7 importers | **H** |
| 5.11 | Absorb `desktop_automation.py`, `desktop_context.py`, `smart_automation.py` | 1,491 LOC | M |
| 5.12 | Remove `_rust_bridge.py` and its 16 call sites (shim expires) | 16 modules | M |
| 5.13 | Assign RAG ownership between `knowledge/` and `connectors/` | Duplicate `KnowledgeStore`, `OllamaEmbedder` | M |

**Dependencies.** Phase 4 complete. 5.9 depends on 5.8. 5.12 depends on 2.9.
5.1 depends on 4.8.

**Risk.** **H**, concentrated in 5.1 (hardware-dependent, historically the most
failure-prone subsystem), 5.6 (backs 6 CLI commands), and 5.10 (7 importers on
Windows-only code).

**Tests required.**

| Step | Test |
|---|---|
| 5.1 | One behavioural test per voice **mode** asserting the mode still works after becoming configuration rather than a copy. Manual QA docs already exist in `docs/testing/` — run them. |
| 5.2 | Assert redaction (from 1.1) still applies after the merge — **this is the regression that matters most** |
| 5.3–5.5, 5.10–5.11 | Behaviour-preserving: the existing suite passes unchanged, plus an import test that the shim resolves |
| 5.6 | Assert all 3 `agent/development/` CLI groups still work — `project`, `roadmap`, `sprint`. `test_final_acceptance.py` must pass. |
| 5.8 | Assert `files/` behaviour unchanged after the adapter fold |
| 5.12 | Assert every former `_rust_bridge` consumer works with the module absent |
| Phase-wide | Assert zero duplicate domain class names (automatable — the detection script exists) |

**Rollback.** Each absorption is additive-then-subtractive: the new owner lands
first, consumers migrate, the shim stays for one release. Rollback at any point
is reverting the consumer migration while the shim still exists. 5.1 is the
exception — a state-machine rewrite is not incrementally revertible, so it must
be a single well-tested PR behind a feature flag selecting old or new session.

**Expected result.** One owner per concern per `MODULE_OWNERSHIP.md`. Zero
duplicate domain class names. `kernel/` archived. `_rust_bridge` gone.

**Breaking change?** **Yes**, for anything importing the absorbed flat modules
directly (`windows_window_control`, `screen_awareness`, `task_scheduler`,
`browser_control`, `windows_app_resolver`). Shims cover one release. **No
user-facing CLI or API change** — `agent/development/`'s commands are explicitly
preserved.

**Blocking question.** **Q-9** — `wip/floating-bubble-final` may contain a
seventh UI surface that would need to join the dispatcher.

---

## PHASE 6 — Memory redesign

**Objective.** One memory facade, four named stores, one owner per database file.
**The only phase that touches live user data.**

### Modules / files affected

| # | Step | Files |
|---|---|---|
| 6.1 | Design + review the migration (backup-first, idempotent, dry-runnable, revertible) | `scripts/migrate_memory.py` **(new)** |
| 6.2 | Introduce `MemoryFacade` **additively** | `memory/facade.py` **(new)** |
| 6.3 | Move the RAG document store `memory.db` → `documents.db`; give `memory.db` one owner | `memory/store.py`, `tools/storage/sqlite.py`, `core/config.py` |
| 6.4 | Migrate 45 `memory_context` importers; `memory_context.py` → shim | 45 modules |
| 6.5 | Break the `memory_context ↔ memory` cycle | `memory/`, `memory_context.py` |
| 6.6 | Rename `SEMANTIC_MODEL` or install a real embedding path | `memory_context.py` |

**Dependencies.** Phase 5. **Hard gate: approval A-3.** Q-5 is now **resolved**
(AD-021) and no longer blocks — the orphaned databases were audited and are
handled in Phase 2.11, separately from this phase's `memory.db` work.

**Risk.** **H — the highest in the plan, and the only irreversible one.**
45 importers, live user data (`personal_memory.db` is 1,085,440 bytes and
`memory.db` 61,440 bytes on this machine), and a schema collision inside a file
the user already has.

**Tests required.**

| Step | Test |
|---|---|
| 6.1 | Migration test on a **copy** of the real `~/.grandpa/memory.db`: assert row counts preserved per table, assert idempotence (running twice is a no-op), assert dry-run makes no writes |
| 6.3 | Assert `memories` and `documents` are queryable after the split with identical result sets |
| 6.4 | Assert every migrated importer returns the same data as before — snapshot-compare |
| 6.5 | Assert no import cycle remains |
| Phase-wide | **Restore test:** back up, migrate, restore from backup, assert the original state is byte-identical |

**Rollback.** The backup taken in 6.1 **is** the rollback, and the restore test
above proves it works before any real migration runs. The `memory_context.py`
shim means code rollback is independent of data rollback. **Do not run the
migration without a verified restore.**

**Expected result.** One facade, four named stores, one owner per file, no data
loss, verified rollback path.

**Breaking change?** **Yes.** On-disk schema change to `memory.db` — a
forward migration is required and users cannot downgrade past it without
restoring the backup. Must be in release notes.

---

## PHASE 7 — Decomposition and hygiene

**Objective.** Split the god-modules along boundaries the target already defines.

| # | Step | Files | Gate |
|---|---|---|---|
| 7.1 | Split `chat_cmd.py` (2,156 LOC) | → `cli/chat/{dispatch,slash,render}.py` | 4.7 |
| 7.2 | Split `api_routes.py` (2,256 LOC) | → `server/routers/*.py` (26 seams already exist) | 4.6 |
| 7.3 | Decompose `local_actions.py` (2,203 LOC) | parser → `intent/`, policy → `policy/`, executor → `desktop/` | 4.11 |
| 7.4 | Audit ~100 silent `except: pass` — action-path packages first | `desktop/`, `automation/`, `pc_control.py`, `local_actions.py` | 7.3 |
| 7.5 | Pydantic models on every action endpoint | `server/models.py`, `server/routers/*` | 7.2 |
| 7.6 | Merge `grandpa model` / `models`; rename `oj_sk_` → `gp_sk_` | `cli/model.py`, `server/auth_middleware.py:70` | — |
| 7.7 | Prune 15 merged branches; clean `config.toml.*.bak` (8 files incl. `.corrupt-`) | — | — |
| 7.8 | Add `api-reference` to `nav:`; adopt or delete 29 orphaned doc pages | `mkdocs.yml`, `docs/` | 2.4 |
| 7.9 | Move `pyautogui`/`pytesseract` out of core into the `screen` extra | `pyproject.toml` | — |
| 7.10 | **[separate decision — A-5]** Purge vendored ffmpeg from history | — | — |

**Risk.** L–M. All behaviour-preserving. **Breaking?** No, except 7.9 (install
extras change) and 7.10 (history rewrite invalidates existing clones).

**Note on 7.10:** per AD-019, **this is not required for LGPL compliance** —
ffmpeg is subprocess-invoked (mere aggregation) and its licence text ships. It is
purely a repository-size decision (207.6 MB, 91.6% of the pack).

---

## 3. Cross-phase dependency table

| Step | Requires | Because |
|---|---|---|
| 2.8 collapse `engine/` | 0.1 | `runtime/` is untracked on `main` |
| 2.9 archive `rust/` | **0.4 (AD-019)** | The archive must inherit correct attribution |
| 2.11 orphaned DBs | approval A-4 | Touches the user's runtime directory |
| 3.7 Windows CI | 0.1, 3.1, 3.2 | Package must import; suite must terminate |
| 3.8 full suite in CI | 3.1–3.5 | Suite must terminate and be green |
| 4.4 `IntentDispatcher` | **3.7 green**, 4.1, 4.2 | Windows surfaces; baseline; shared types |
| 4.11 `PolicyEngine` | 4.4 | The dispatcher is where policy is invoked |
| 4.12 origin tagging | 4.11 | `origin` lives on `ActionRequest` |
| 4.15 break `pc_control ↔ desktop` | 4.11 | The cycle exists because `pc_control` holds policy |
| 5.1 `VoiceSession` | 4.8, 3.7 | Voice paths are dispatch chains |
| 5.2 browser merge | **1.1** | Redaction must not wait on the merge |
| 5.6 absorb `agent/` | AD-020 ratified | Scope excludes `agent/development/` |
| 5.9 rename `desktop/kernel/` | 5.8 | Collision clears only once `kernel/` is gone |
| 5.12 remove `_rust_bridge` | 2.9 | Shim expiry |
| 6.x memory | 5.x, **approval A-3** | Live user data |
| 7.1 split `chat_cmd.py` | 4.7 | The split boundary is the dispatcher |
| 7.3 decompose `local_actions.py` | 4.11 | The policy half moves to `PolicyEngine` |

---

## 4. Risk register

| Phase | Primary risk | Mitigation |
|---|---|---|
| 0 | Merge conflicts across 73 files | Merge, don't rebase. Verify with clean-clone `doctor`. |
| 0 | NOTICE wording misstates the relationship | Q-3a first; keep it factual and minimal |
| 1 | Injection scanning false-positives block real work | Ship log-only by default; enforce after tuning |
| 1 | Fail-closed RBAC breaks a user's partial policy | Intended. Release-note it; provide the diagnostic. |
| 2 | Archiving something later needed | Archive, never delete. History preserved. |
| 2 | Deleting a database with real data | **Audited** — AD-021. 2 archived, 1 secure-deleted, 4 verified data-free. |
| 3 | Windows runner surfaces many failures at once | Expected. Quarantine with real markers; fix incrementally. |
| 4 | Dispatcher silently changes behaviour | 4.1 characterisation tests first; one surface per PR |
| 4 | `PolicyEngine` weakens a guard | Port, don't re-derive. Action-by-action diff against both originals. |
| 4 | Missed origin threading → silent privilege escalation | Make `origin` required with no default → type error, not silent bug |
| 5 | Voice consolidation breaks an untested mode | Windows CI + the existing `docs/testing/` manual QA docs |
| 6 | **Data loss** | Backup-first, idempotent, dry-run, verified restore test before any real run |
| 7 | Scope creep into a rewrite | One module per PR; behaviour-preserving only |

---

## 5. Definition of done

- [ ] `main` imports from a clean clone; one baseline branch
- [ ] `LICENSE` + `NOTICE` + README credit upstream; `CODEOWNERS` names the owner
- [ ] `windows-latest` **and** `ubuntu-latest` green on the full deterministic suite
- [ ] `pytest` terminates and exits 0
- [ ] One dispatcher; all surfaces expose the same capability set, proven by a parity test
- [ ] One origin-aware policy engine; one risk vocabulary; one approval store with out-of-band codes
- [ ] Every action's origin is recorded in the audit trail
- [ ] Zero package import cycles, CI-enforced
- [ ] Zero duplicate domain class names
- [ ] One owner per concern per `MODULE_OWNERSHIP.md`
- [ ] One event bus covering the Windows layer; audit is a subscriber
- [ ] Redaction and injection scanning at every untrusted ingress
- [ ] Capability RBAC fails closed
- [ ] Zero inert config keys; zero unwired security modules
- [ ] Every docstring, constant, and doc page matches the code
- [ ] `agent/development/` retained, documented, and on the roadmap
- [ ] All P1/P1a/P1b invariants intact and re-verified

---

## 6. What must NOT be changed

### 6.1 Behavioural invariants — never weaken

| # | Invariant | Where |
|---|---|---|
| 1 | **P1 — no action executes without policy classification and, where required, approval.** Applies to *all* origins. | Funnel A + Funnel B |
| 1b | **P1b — deterministic-first on the NL path.** `handle_local_action` receives only user text, parsed by allowlist. | `cli/ask.py:739`, `cli/chat_cmd.py:1918`, `server/routes.py:295`, `server/api_routes.py:1829` |
| 2 | **Default-deny.** Unrecognised action → `BLOCKED`. | `pc_control._classify_risk_impl` |
| 3 | **Allowlist + denylist defence in depth.** | `local_actions.py` |
| 4 | **Path resolution before protection checks**; `open_folder` requires `is_dir()`. | `_normalised_path_parts` |
| 5 | **Screen/vision redaction**, 7 pattern classes. | `screen/redaction.py`, `vision/graph.py:63`, `automation/locator.py` |
| 6 | **SSRF protection** on all outbound URLs. | `security/ssrf.py` + 3 consumers |
| 7 | **Zero telemetry egress.** | `telemetry/`, `traces/` |
| 8 | **Bind safety** — non-loopback refused without a key. | `check_bind_safety()` |
| 9 | **Auth on by default.** | `server/auth_middleware.py` |
| 10 | **Out-of-band approval codes** — the staging channel cannot approve. | `pc_control` approval flow |
| 11 | **Emergency stop**; `pyautogui.FAILSAFE = True`. | `pc_control.emergency_stop` |
| 12 | **BLOCKED set stays blocked**: `shell_run`, `script_run`, `file_permanent_delete`, `browser_submit_form`, `browser_extract_password`, `browser_purchase`. | `pc_control.BLOCKED_ACTIONS` |

### 6.2 Modules that are correct — extend, do not restructure

`core/config.py` (precedence model, generic validator, back-compat shims,
`GRANDPA_HOME`) · `core/registry.py` · `core/types.py` · `core/events.py` ·
`screen/` · `desktop/control/*` · `runtime/ollama_adapter.py` ·
`security/{scanner,ssrf,file_policy,taint}.py` · `voice_service/` +
`voice_runtime/` boundary · `cli/__init__.py` lazy loader ·
`cli/{safe_output,theme,hints}.py` · `conftest.py` registry isolation ·
**`agent/development/` (AD-020)**.

### 6.3 User-facing contracts

The 51-command CLI surface (additions fine; removals need deprecation) ·
OpenAI-compatible `/v1/chat/completions` · `~/.grandpa/` layout (Phase 6
migrates, never breaks) · `GRANDPA_HOME` · the `grandpa doctor` readiness
contract.

---

## 7. What can be safely deprecated

### 7.1 Zero consumers — safe immediately

| Component | LOC | Evidence | Phase |
|---|---:|---|---|
| `a2a/` + `A2AConfig` | 460 | 0 `src/` consumers; 1 test file | 2.9 |
| `templates/` | 115 | 0 consumers | 2.9 |
| `daemon/` | 34 | 0 consumers | 2.9 |
| `security/subprocess_sandbox.py` | 143 | 0 consumers; uses `shell=True` | 2.6 |
| `security/severity_policy.py` | 22 | 0 consumers | 2.6 |
| `.dockerignore` | — | No Dockerfile exists | 2.10 |
| `grandpa_tree.txt`, `grandpa_project_structure.txt` | 10.7 MB | Generated dumps | 2.10 |
| 4 orphaned DBs (iot, future_features, communication, real_world) | 60 KB | **Audited: zero user data** | 2.11 |
| Stale `test_autonomous_workflows.py` path | 1 line | File does not exist | 2.11 |

### 7.2 Safe after a stated prerequisite

| Component | LOC | Prerequisite | Phase |
|---|---:|---|---|
| `rust/` | 27,035 | **AD-019 complete** | 2.9 |
| `engine/` | 342 | Consumers on `runtime/` | 2.8 |
| `kernel/` | 3,272 | `files/kernel_adapter.py` folded; `tests/kernel/` retired | 5.8 |
| `_rust_bridge.py` | 180 | `rust/` archived; one shim release | 5.12 |
| `jarvis/` | 698 | `voice/` consolidation | 5.1 |
| `router/` | 518 | `intent/` exists | 4/5 |
| `screen_awareness.py` | 664 | 7 importers redirected | 5.3 |
| `windows_app_resolver.py` | 675 | Absorbed into `apps/` | 5.4 |
| `task_scheduler.py` | 880 | Absorbed into `scheduler/` | 5.5 |
| `windows_window_control.py` | 1,362 | 7 importers redirected | 5.10 |
| `browser_control.py` + 2 packages | 4,009 | Merged into `browser/` | 5.2 |
| `desktop_automation`/`desktop_context`/`smart_automation` | 1,491 | Absorbed | 5.11 |
| `agent/{executor,context,models,runtime}.py` | ~1,500 | AD-008 re-scoped | 5.6 |
| `sync_state.db`, `autonomous_workflows.db` | 60 KB | **Archive first** | 2.11 |
| `mobile_integration.db` | 32 KB | **Secure delete; do not archive to shared storage** | 2.11 |
| `memory_context.py` | 1,302 | **Approval A-3**; 45 importers; live data | 6.4 |

### 7.3 NOT safe to deprecate — listed to prevent assumptions

| Component | Why not |
|---|---|
| **`agent/development/`** | **AD-020 — RETAINED.** Owner-authored, newest code in the repo, 3 CLI groups with top-level imports, 6 test files, state modified today. **Removed from every archive list.** |
| `mcp/` client | Live, wired into `SystemBuilder` |
| `sdk.py` + `system/` | The only public API; blocked on Q-1 |
| `services/` | A genuine assistant-facing façade; one of the few clean layer seams |
| `security/guardrails.py` | Zero *external* in-degree is a measurement artefact — wired via `setup_security()` |
| `voice_service/` | Zero in-degree **by design** — invoked over HTTP |
| `learning/routing/` | Live routing policy (the Rust crate goes; the Python stays) |
| `knowledge/` **or** `connectors/` | One should own RAG — an unresolved ownership call, not a deprecation |
| `personal_memory.db`, `memory.db`, `knowledge.db`, `scheduler.db`, `telemetry.db`, `traces.db`, and the other 22 live DBs | **Not orphaned.** Only the 7 audited in AD-021 are. |

---

## 8. What requires explicit approval before implementation

| # | Item | Why | Phase |
|---|---|---|---|
| **A-1** | **Ratify AD-001** — Windows assistant on a retained substrate | Everything in Phases 2, 5, 7 assumes it | Before 2 |
| **A-2** | **Ratify AD-002** — archive `rust/` | 27,035 LOC, 2 CI jobs. Reversible, but not a default. | 2.9 |
| **A-3** | **Phase 6 memory migration** | **The only change touching live user data.** Irreversible without the backup. | 6 |
| **A-4** | **Execute AD-021 database dispositions** | Touches `~/.grandpa/`. Audit complete; execution still needs a go-ahead. | 2.11 |
| **A-5** | **Purge ffmpeg from git history** | History rewrite; invalidates every clone and fork. **Not required for licence compliance.** | 7.10 |
| **A-6** | **AD-019 NOTICE wording** | A public statement about the project's provenance | 0.4 |
| **A-7** | **Wire `rate_limiter`** (Q-6) | Requests that succeed today may be throttled | 4.14 |
| **A-8** | **Wire `injection_scanner`** (Q-6) | Needs a defined flag response | 1.2 |
| **A-9** | **Capability RBAC fail-closed** | Deliberately breaks partial policies | 1.3 |
| **A-10** | **Any change to a §6.1 invariant** | These are the safety model | Any |
| **A-11** | **The final risk-tier table in `PolicyEngine`** | AD-006 fixes the mechanism; the tiers are a security decision | 4.11 |
| **A-12** | **Origin-based approval thresholds** (Q-10) | Whether agent/skill actions need approval sooner than user actions | 4.12 |
| **A-13** | **Gating or removing the MCP server** (Q-2) | Changes third-party integration capability | 2.4 |
| **A-14** | **Removing or renaming any CLI command** | 51 commands are a user-facing contract | Any |
| **A-15** | **SDK stability contract** (Q-1) | Public API or internal seam | 3 |
| **A-16** | **PyPI publishing** (Q-8) | The name belongs to an unrelated party | 2 |

**No longer requiring approval** (resolved by evidence):

| Was | Now |
|---|---|
| ~~Archiving `agent/development/`~~ | **AD-020: retained.** Not an archive candidate. |
| ~~Deleting the 7 orphaned databases blind~~ | **AD-021: audited.** Per-DB dispositions assigned; only execution needs go-ahead (A-4). |
| ~~Whether archiving `rust/` is legally safe~~ | **AD-019: yes**, provided attribution is restored first. |

---

## 9. First five concrete implementation tasks

Ordered. Each is independently valuable, independently revertible, and blocks
something downstream.

### Task 1 — Merge the stabilization branch *(Phase 0.1–0.3)*

**Do:** merge `claude/grandpa-codebase-audit-bf609c` into `main`.
**Verify:** fresh clone → `uv sync` → `grandpa doctor` → `pytest --co` gives 0
collection errors (currently 56).
**Why first:** `main` does not import from a clean clone. Every measurement,
test, and refactor downstream is built on a tree nobody else can reproduce.
**Effort:** half a day. **Breaking:** no. **Rollback:** `git revert -m 1`.

### Task 2 — Restore upstream attribution *(Phase 0.4–0.5, AD-019)*

**Do:** restore the `Copyright 2025 The OpenJarvis Authors` line in `LICENSE`
alongside the Grandpa line; create `NOTICE` naming OpenJarvis and IPW; add a
two-sentence "Origins" section to `README.md`; fix `CODEOWNERS`; record the
ffmpeg provenance URL.
**Why second:** the repository is published, so distribution is occurring under
a §4(c) defect. Under an hour, zero code risk, and it must precede the `rust/`
archive so the archive inherits correct attribution.
**Effort:** under an hour. **Breaking:** no. **Approval:** A-6 (wording).

### Task 3 — Remove the Rust-first path in `shell_exec` *(Phase 1.4)*

**Do:** delete `tools/shell_exec.py:126-140`; keep only the Python
implementation.
**Why third:** it discards the sanitised environment and the timeout and
hardcodes `returncode: 0, success: True`. It is inert only because the extension
is never built — and AD-002 archives the extension, so it becomes permanently
dead code guarding nothing. It is also a ~15-line deletion.
**Test:** assert `shell_exec` honours the timeout and sanitised env and returns
the real return code.
**Effort:** an hour. **Breaking:** no. **Rollback:** trivial revert.

### Task 4 — Apply redaction to every browser extraction boundary *(Phase 1.1)*

**Do:** call `redact_screen_text` in `browser_intelligence/content_extractor.py`,
`page_reader.py`, `summarizer.py`, `page_analyzer.py`,
`browser_awareness/{capture,parser}.py`, `browser/parser.py`, and
`browser_control.py`.
**Why fourth:** browser page text is the largest volume of untrusted content the
assistant ingests, it reaches both logs and LLM prompts unredacted, and the
README explicitly promises redaction of passwords, tokens, OTPs, card numbers,
and private keys. The function and the call pattern already exist in three other
packages. **Land it before the Phase 5 browser consolidation, not as part of it.**
**Test:** synthetic page containing a fake token / OTP / card number is redacted
before logging or prompt assembly — one test per path.
**Effort:** a day. **Breaking:** no.

### Task 5 — Add `pytest-timeout` and quarantine the two hanging tests *(Phase 3.1–3.2)*

**Do:** add `pytest-timeout` to the `dev` extra, set a default timeout, and apply
the **already-declared, never-used** `microphone` marker to
`tests/cli/test_voice_operator_cmd.py::test_voice_operator_command_typed_quit`
and `::test_voice_operator_command_typed_fallback_action`, skipping unless
opted in.
**Why fifth:** these two tests hang forever, so the documented `pytest` command
never terminates. They are classified `core` only because `conftest.py` defaults
everything unlisted to `core` and the `microphone` marker is declared but never
applied. This unblocks Task 6 (the Windows CI job), which gates all of Phase 4.
**Verify:** `pytest` returns; `pytest -m microphone` selects exactly those tests.
**Effort:** an hour. **Breaking:** no.

**Then:** the Windows CI job (Phase 3.7) — the gate that opens Phase 4.

---

## 10. What to do this week

If only one thing happens: **Task 1**. `main` does not import from a clean clone.

If two: **Task 1 and Task 2**. The second is under an hour and resolves a live
licence-compliance defect on a published repository.

**Do not start Phase 4.** It is the highest-value work in this plan and it is
gated on a Windows CI job that does not yet exist.
