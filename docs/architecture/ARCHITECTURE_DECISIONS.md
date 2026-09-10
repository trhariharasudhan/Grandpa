# Grandpa — Architecture Decisions

**Status:** Final decision package. Decisions marked *Needs ratification* are
binding only after your approval.
**Date:** 2026-08-26
**Supersedes:** the 2026-08-26 discovery draft. Q-3, Q-4, and Q-5 are now
**resolved from evidence**. AD-019 is a **correction** to a claim made in the
discovery draft and in `AUDIT.md`.

Tag legend is defined in `CURRENT_ARCHITECTURE.md` and applies unchanged.

---

## Index

| ID | Decision | Status |
|---|---|---|
| AD-001 | Product identity: Windows assistant on a retained substrate | Needs ratification |
| AD-002 | Rust workspace: archive out of tree | Needs ratification |
| AD-003 | SDK is a secondary, supported surface | Needs ratification |
| AD-004 | MCP server gated behind explicit opt-in | Needs ratification + Q-2 |
| AD-005 | One `IntentDispatcher` | Recommended |
| AD-006 | One `PolicyEngine` | Recommended |
| AD-007 | Collapse `engine/` into `runtime/` | Recommended |
| AD-008 | `agents/` is the agent framework | Recommended |
| AD-009 | `planner/` is the assistant planner | Recommended |
| AD-010 | One `MemoryFacade`, four named stores | Needs approval (data migration) |
| AD-011 | One `browser/` package; redaction at ingress | Recommended |
| AD-012 | Archive `a2a/`, `kernel/`, `templates/`, `daemon/` | Recommended |
| AD-013 | Wire or delete — no third state for security modules | Recommended |
| AD-014 | One `VoiceSession` | Recommended |
| AD-015 | One event bus; audit becomes a subscriber | Recommended |
| AD-016 | `windows-latest` CI is a hard prerequisite | Recommended, gating |
| AD-017 | Config schema describes the product | Recommended |
| AD-018 | Merge the stabilization branch before anything else | Recommended, gating |
| **AD-019** | **Restore upstream attribution (Apache-2.0 §4 compliance)** | **RESOLVED — action required** |
| **AD-020** | **`agent/development/` is RETAINED as product** | **RESOLVED** |
| **AD-021** | **Orphaned-database dispositions** | **RESOLVED — per-DB** |
| **AD-022** | **P1 is a policy-layer invariant, not a path-absence invariant** | **RESOLVED — correction** |
| **AD-023** | **`ActionOrigin` conflates three provenance dimensions; the burn-in `direct` fallback is not a classification** | **RESOLVED — direction recorded** |
| **AD-024** | **Funnel-A approval does not satisfy `desktop_automation`'s confirmation contract; confirmation-requiring automation stays unexposed** | **RESOLVED — decision C** |
| **AD-025** | **Retire Funnel-A's duplicate automation execution path; `grandpa/automation/` is canonical** | **RESOLVED — option A, retire** |
| **AD-026** | **Retirement intentionally removes three undocumented HTTP automation capabilities; no bridge, parity stays GAP-02's** | **RESOLVED — option 1, accept** |
| **AD-027** | **`rate_limiter.py` disposition changes WIRE → DELETE; no runtime rate limiting is introduced** | **RESOLVED — delete** |
| **AD-028** | ~~**The `pc_control ↔ desktop` cycle is mostly type location**~~ — **measurement CORRECTED (41 statements, not 17); the type relocation stands, the characterisation does not.** **Addendum AD-028.1** authorises `desktop/control → policy.models` for eight modules; **Addendum AD-028.2** authorises `desktop/kernel/risk.py → policy.engine` and clarifies the reach of AD-028.1 e | **RESOLVED — relocation + two allowlist addenda** |
| **AD-029** | **An approval that gates execution requires an out-of-band credential; `/v1/approvals/{id}/approve` is recorded as non-conforming.** Store-3 ownership, TTL, action binding, attempt cap, provenance and execution-state semantics all stay open | **RESOLVED — contract only, no implementation** |
| **AD-030** | **Store 3 is one approval domain — patch proposals. No executable proactive-action domain exists and `ProactiveAgent` is not an implemented component; generic schema/API naming is not evidence of a second live domain.** Premise clarification only — D-1, D-4 and D-5 stay open and AD-029 continues to apply | **RESOLVED — scope clarification, no implementation** |
| **AD-031** | **Retire the dead remembered-permission subsystem in `tools/approval_store.py`** — `permission_memory`, its four CRUD methods, `PermissionRule`, the `DECISION_*` constants and `get_seen_ids`. No wiring; the tier vocabulary, schema migration, D-1 and D-5 all stay separate and open | **RESOLVED — RETIRE; no wiring; implementation/deletion deferred to a dedicated follow-up slice** |
| **AD-032** | **Retire the `/v1/approvals/*` route family** (`GET /pending`, `POST /{id}/approve`, `POST /{id}/deny`) — its ApprovalBell client and its proactive-action domain are both gone, and AD-029's non-conformance is resolved by **removal, not migration**. A potentially breaking API change; the CLI patch path is the supported replacement. D-1, tier retirement and schema migration stay open | **RESOLVED — RETIRE; deletion deferred to a dedicated follow-up slice** |

---

# Part I — Resolved blockers

## AD-019 — Q-3 RESOLVED: this repository is a hard fork of Apache-2.0 upstream, and attribution was removed

### Evidence

**[FACT] The repository is a fork of a real multi-contributor open-source project.**

| Measure | Value | Command |
|---|---|---|
| Commits before the rebrand (2026-03-12 → 2026-05-22) | **697** | `git log --since --until \| wc -l` |
| Commits after the rebrand (2026-05-23 →) | **140** | |
| **Upstream share of history** | **83%** | |
| Distinct upstream authors | **36** | `git log --format='%ae' \| sort -u \| wc -l` |
| Top upstream author | Jon Saad-Falcon — 427 commits | |
| Other named upstream contributors | krypticmouse (66), Robby Manihani \<manihani@stanford.edu\> (25+3), Avanika Narayan (22), Tarun Suresh (13), Gabriel Bo (12), Prathap (11+3), Andrew Park (10), Tanvir Bhathal (9+4), **Eddie Richter \<eddie.richter@amd.com\> (8)**, Abhinav Cherukuru (5), Isaac H (4), Gilles Ceyssat (4), Ali Shahkar (4), Jana Bergant (3), … | |
| Post-rebrand authors | `trhariharasudhan` / `Hari Hara Sudhan` only | |

**[FACT]** Commit `8798e2ee` ("init commit", 2026-03-12) was authored by **Jon
Saad-Falcon** and contained **1,197 files** — the complete OpenJarvis codebase
including `configs/openjarvis/`, `deploy/docker/`, `desktop/` (Tauri),
`assets/OpenJarvis_*.png`, and four CI workflows. This is an imported upstream
tree, not original authorship.

**[FACT] The upstream lineage is two levels deep.** Commit `8de28bdf` — "fix:
update project links from **intelligence-per-watt.ai** to OpenJarvis (#47)" —
establishes that OpenJarvis was itself derived from **IPW**. Four Python files
still carry explicit headers:

| File | Header |
|---|---|
| `src/grandpa/core/registry.py:3` | "Adapted from IPW's `src/ipw/core/registry.py`" |
| `src/grandpa/engine/_stubs.py:3` | "Adapted from IPW's `InferenceClient` at `src/ipw/clients/base.py`" |
| `src/grandpa/agents/_stubs.py:3` | "Adapted from IPW's `BaseAgent` at `src/agents/base.py`" |
| `src/grandpa/agents/prompt_registry.py:3` | "Adapted from IPW's `prompt_registry.py`" |

**[FACT] The licence is Apache-2.0 at both levels, and the copyright line was
replaced rather than retained.**

```
git show 8798e2ee:LICENSE | grep 'Copyright 20'
   Copyright 2025 The OpenJarvis Authors        ← upstream

git show ad316476 -- LICENSE
-  Copyright 2025 The OpenJarvis Authors
+  Copyright 2025 The Grandpa Authors           ← rebrand commit, 1,812 files
```

**[FACT] No NOTICE file has ever existed** in this repository, on any branch, at
any commit: `git log --all --diff-filter=AD -- NOTICE NOTICE.txt NOTICE.md`
returns nothing. This is materially favourable — see the obligation analysis.

**[FACT] There is no attribution to OpenJarvis or IPW anywhere in the
user-facing documentation.** `README.md`, `CONTRIBUTING.md`, and
`CODE_OF_CONDUCT.md` contain zero references to either project. The only
occurrences in `docs/` are inside this architecture analysis.

**[FACT]** `.github/CODEOWNERS` still reads `* @jonsaadfalcon @ANarayan
@robbym-dev` — three upstream authors, none of whom is the repository owner.

### Obligation

Apache-2.0 §4 governs redistribution of derivative works. Assessed clause by
clause:

| Clause | Requirement | Status |
|---|---|---|
| **§4(a)** | Give recipients a copy of the Licence | ✅ **Satisfied** — `LICENSE` is present and is the full Apache-2.0 text |
| **§4(b)** | Modified files must carry prominent notices stating that you changed them | ❌ **Not satisfied** — no changed-file notices anywhere |
| **§4(c)** | **Retain**, in the Source form of derivative works, **all copyright, patent, trademark, and attribution notices** from the Source form of the Work | ❌ **Violated** — commit `ad316476` **deleted** the upstream copyright line rather than retaining it alongside the new one |
| **§4(d)** | If the Work includes a NOTICE file, include a readable copy of its attribution notices | ✅ **No obligation** — upstream shipped **no** NOTICE file, so nothing was required to be propagated |
| **§6** | The Licence grants no permission to use upstream trade names or trademarks | ✅ **Satisfied, and improved by the rename** — removing OpenJarvis branding is what §6 asks for. The rename itself was correct; only the copyright deletion was not. |

**[FACT] Apache-2.0 is permissive.** It explicitly permits forking, rebranding,
modification, commercial use, and distribution of derivative works. There is
**no copyleft obligation**, no requirement to publish changes, and no
requirement to keep the upstream name. **The only defect is the deleted
attribution.**

### Secondary obligation — vendored LGPL ffmpeg

**[FACT]** `voice_runtime/tools/ffmpeg-7.1-lgpl-shared/` contains **217 tracked
files** — DLLs, headers, and `LICENSE.txt` (**LGPL v3**, not 2.1) — plus the
original `ffmpeg-7.1-lgpl-shared.zip`. Together 207.6 MB, 91.6% of the git pack.

**[FACT] ffmpeg is invoked as a subprocess, not linked.**
`voice_service/post_processing.py:47` resolves it via
`shutil.which("ffmpeg")` and passes the path to a subprocess call;
`voice_runtime/scripts/generate_10s_clarity_tests.py:42` globs for
`tools/ffmpeg-*/**/bin/ffmpeg.exe`. **No Python module links against
`avcodec`/`avformat`.**

This materially lightens the obligation. Because ffmpeg runs as a separate
executable, this is **mere aggregation**, not a "Combined Work" under LGPL-3 §4.
The obligations reduce to: ship the licence text (**already satisfied** —
`LICENSE.txt` is present) and be able to point to the corresponding source of
the exact build.

**[RECOMMENDATION]** Record the provenance URL of the exact prebuilt archive in
`voice_runtime/README.md`. That plus the included `LICENSE.txt` is a defensible
position for an unmodified upstream binary invoked as a subprocess.

### Affected files

**Must change (attribution):**

| File | Change |
|---|---|
| `LICENSE` | Restore the upstream copyright line **alongside** the new one |
| `NOTICE` *(new)* | Create — attribute OpenJarvis and IPW, and the Apache-2.0 origin |
| `README.md` | Add a short "Origins" / "Acknowledgements" section |
| `.github/CODEOWNERS` | Replace upstream handles with the real owner (they cannot approve PRs, and their presence implies a governance relationship that does not exist) |
| `pyproject.toml` | `authors = [{name = "Grandpa Contributors"}]` — consider noting the derivation |

**Should carry changed-file notices (§4(b)) — the four with explicit IPW headers:**
`core/registry.py`, `engine/_stubs.py`, `agents/_stubs.py`,
`agents/prompt_registry.py`.

**[RECOMMENDATION]** Rather than annotating hundreds of files individually, a
single `NOTICE` entry stating that the work is a modified derivative of
OpenJarvis (Apache-2.0), that substantial modifications were made from
2026-05-23 onward, and that the Grandpa-era changes are the current authors',
is the conventional and proportionate way to satisfy §4(b) for a whole-project
fork.

**Also affected (cosmetic residue of the same fork):**
`server/auth_middleware.py:70` still generates keys with the `oj_sk_`
(OpenJarvis) prefix.

### Recommended action

> **[DECISION AD-019]** Restore upstream attribution before any further
> redistribution. Specifically:
>
> 1. **`LICENSE`** — restore the upstream line and add the current one:
>    ```
>    Copyright 2025 The OpenJarvis Authors
>    Copyright 2025-2026 The Grandpa Authors
>    ```
> 2. **Create `NOTICE`** naming OpenJarvis and IPW as the upstream works, their
>    Apache-2.0 licence, and the fact that Grandpa is a modified derivative with
>    substantial changes made from 2026-05-23 onward.
> 3. **Add an "Origins" section to `README.md`** — two sentences.
> 4. **Fix `CODEOWNERS`** to name the actual repository owner.
> 5. **Record the ffmpeg build provenance URL** in `voice_runtime/README.md`.
> 6. **Rename the `oj_sk_` key prefix** to `gp_sk_` (cosmetic, but it is the same
>    fork residue and it leaks the origin into generated credentials).

**Cost:** under an hour. No code changes, no behavioural change.

**[RECOMMENDATION]** Do this in **Phase 0**, not Phase 2 as previously
sequenced. The repository is published at
`github.com/trhariharasudhan/Grandpa` (per `pyproject.toml` `[project.urls]`),
so distribution is already occurring, and every day it continues is a day of
non-compliance. It is also the cheapest item in the entire plan.

**This is not legal advice.** The clause-by-clause reading above is a
good-faith engineering assessment of a well-understood permissive licence. If
the project is or becomes commercial, have counsel confirm it.

### Is archive-out-of-tree legally and technically safe?

> **Legally: yes — and it is strictly safer than the status quo.**
>
> - Apache-2.0 imposes **no obligation to retain, build, or ship** any part of
>   the Work. Removing `rust/` from the main tree is expressly permitted.
> - The attribution obligation attaches to **what you distribute**. Archiving to
>   a branch or a separate repository means the archive location must carry the
>   same `LICENSE` + `NOTICE`. That is one file copy.
> - Deleting outright would also be lawful — but see below.
> - **§4(c) applies to the archive too.** Do AD-019 **first**, then archive, so
>   the archive inherits correct attribution rather than propagating the defect.
>
> **Technically: yes.**
>
> - Zero runtime consumers. The wheel is `hatchling`-built and cannot contain a
>   cdylib, so no installed copy has ever used it.
> - All 16 `_rust_bridge` call sites fall back to Python.
> - Removing the `rust` CI job removes a currently-red gate.
>
> **[RECOMMENDATION] Archive, do not delete — and the licensing evidence
> strengthens this.** The Rust workspace embeds contributions from ~36 people
> including Stanford- and AMD-affiliated engineers, and carries real upstream
> security fixes (`b8245136` IPv4-mapped-IPv6 SSRF handling, `f21eec6c`
> signature-verification hardening). Discarding that irreversibly, in a
> repository whose attribution is currently defective, is the wrong direction.
> Archiving preserves both the code and the provenance trail.

**[OPEN QUESTION] Q-3a — now the only remaining licensing question.** Is the
upstream OpenJarvis repository still public, and does it still carry Apache-2.0?
If it was relicensed or withdrawn after the fork, that does not retroactively
affect rights already granted, but it is worth confirming before publishing a
NOTICE that points at it.

---

## AD-020 — Q-4 RESOLVED: `agent/development/` is product code and is RETAINED

**This inverts the discovery draft**, which listed it as an archive candidate
pending evidence. The evidence arrived and points the other way.

### Evidence

**[FACT] It is the newest code in the repository, authored by the owner, three
months after the rebrand.**

```
git log --date=short --format='%h %ad %an | %s' -- src/grandpa/agent/development/
  72a67e80 2026-08-04 Hari Hara Sudhan | feat(cli): fullscreen terminal UI and UX polish
  102c552b 2026-08-02 Hari Hara Sudhan | feat: complete Grandpa V1 autonomous assistant workflow

git log --diff-filter=A -- src/grandpa/agent/runtime.py
  e007069e 2026-08-01 Hari Hara Sudhan | feat(agent): implement Grandpa Agent Runtime V1
```

**[FACT] It is not inherited.** OpenJarvis's init commit contains no
`development/`, `sprint`, or `roadmap` module —
`git ls-tree -r 8798e2ee | grep -iE 'development|sprint|roadmap'` returns only
doc pages. This package did not exist upstream.

**[FACT] It has 23 live import sites across 4 source modules.**

| Consumer | Sites | Import style |
|---|---:|---|
| `cli/project_cmd.py` | 7 | **top-level** (lines 9, 10, 11) + lazy |
| `cli/roadmap_cmd.py` | 5 | **top-level** (lines 10, 11, 15) + lazy |
| `cli/sprint_cmd.py` | 2 | **top-level** (lines 9, 10) |
| `agent/runtime.py` | 8 | lazy (registry, sprint, engine, planner ×3, roadmap_generator ×2) |

Top-level imports in three CLI modules mean this is not an optional path — those
commands fail to import without it.

**[FACT] It backs 3 registered CLI command groups**, verified in
`cli/__init__.py`: `project_group` (:158), `roadmap_group` (:165),
`sprint_group` (:325).

**[FACT] It has 6 dedicated test files** — `test_autonomous_development.py`,
`test_final_acceptance.py`, `test_multi_project_memory.py`,
`test_project_engineer_mode.py`, `test_self_planning_engine.py`,
`test_sprint_runner.py` — with 20 import sites between them. Note
`test_final_acceptance.py`: this package is part of the owner's own acceptance
criteria.

**[FACT] It has 4 documentation pages** —
`autonomous-development-workflow-v1.md`, `project-engineer-mode-v1.md`,
`self-planning-engine-v1.md`, `agent-execution-v2.md` — all orphaned from
`mkdocs.yml` `nav:` (but so are 29 of 51 doc pages; that is a nav problem, not a
signal about this package).

**[FACT] It has live runtime state.** `D:\Grandpa\.grandpa\development_state.json`
is 14,797 bytes, last modified **2026-08-26 09:42** — today. There is also a
`checkpoints/` directory. **This feature is in active daily use by the owner.**

### Why the README roadmap does not contradict this

**[FACT]** The README's 12-item roadmap predates the package. The README has not
been substantively revised since the early Grandpa era, and it also fails to
mention MCP, the SDK, the agent runtime, `grandpa vault`, `grandpa operators`,
and `grandpa skill_builder` — all of which exist and work. **The roadmap is
stale documentation, not a scope boundary.** Treating its silence as evidence of
exclusion would have been a reasoning error; the discovery draft flagged this as
an open question precisely to avoid making it.

### Decision

> **[DECISION AD-020] Classification: RETAIN — with consolidation.**
>
> `agent/development/` is first-class Grandpa product code: owner-authored,
> recently written, CLI-exposed, test-covered, documented, and in daily use.
>
> Actions:
> 1. **Retain the package and all 3 CLI command groups.** Remove it from every
>    archive and deprecation list.
> 2. **Consolidate the type collisions only.** AD-008 folds
>    `agent/executor.py`, `agent/context.py`, `agent/models.py` into `agents/`
>    to resolve `AgentExecutor` / `AgentContext` / `AgentResult` / `AgentGoal` /
>    `AgentRuntime`. **`agent/development/` is not part of that merge** — it has
>    no colliding type names.
> 3. **Add it to the README roadmap** and to `mkdocs.yml` `nav:`. The gap is in
>    the documentation, not the code.
> 4. **Re-scope AD-008.** `agent/` is not "a duplicate framework to absorb"; it
>    is *two* things — a duplicated executor/context/model layer (absorb) and a
>    distinct autonomous-development product feature (retain).

**Consequence for AD-001:** this slightly widens the product definition. Grandpa
is a Windows-first assistant **that includes an autonomous
software-development mode**. That is coherent — the owner is a developer using
the assistant on their own projects — and it does not affect the platform /
product layering.

---

## AD-021 — Q-5 RESOLVED: all 7 orphaned databases audited; dispositions below

### Provenance — a single, decisive finding

**[FACT] All seven are residue from one feature burst that the owner
deliberately removed.**

```
Modules added:   2301d59d  2026-06-01  trhariharasudhan
                 "complete assistant capability foundations and diagnostics"

Modules deleted: c40b58ab  2026-07-28  trhariharasudhan
                 "refactor(repo): focus Grandpa on local Windows assistant"
                 (mobile_integration removed slightly earlier at 2cabd560, 2026-07-26)
```

Every database's mtime (2026-06-01 → 2026-06-06) falls inside that module
lifetime. **No current source, test, config, or script references any of them** —
the only repository matches are this analysis and one stale test path (below).

**[FACT] This is independent confirmation of [DECISION A].** The owner already
performed this exact scope reduction, in a commit whose message is literally
*"focus Grandpa on local Windows assistant"*. AD-001 ratifies a decision the
repository has already made once.

### Per-database audit

All figures read live from `C:\Users\ASUS\.grandpa\`, opened **read-only**
(`file:...?mode=ro`). **Nothing was modified or deleted.**

---

#### 1. `iot_smart_home.db` — 20,480 bytes, mtime 2026-06-01

| | |
|---|---|
| **Schema** | `iot_devices(id, created_at, name, kind, address, simulated, status)` — 2 rows; `sensor_events(id, created_at, device_id, event_type, value)` — 0 rows |
| **Writer** | `src/grandpa/iot_smart_home.py` — added `2301d59d`, deleted `c40b58ab` |
| **Readers / runtime / CLI / API / migration / tests** | **None** |
| **User data?** | **No.** Both rows are `simulated=1`: `('Demo Smart Light','light',1,'ready')`, `('Demo Smart Plug','plug',1,'ready')` — seeded demo fixtures |
| **Safe to delete?** | **Yes** |
| **Disposition** | **DELETE** |

---

#### 2. `future_features.db` — 12,288 bytes, mtime 2026-06-01

| | |
|---|---|
| **Schema** | `future_connectors(id, created_at, kind, name, mode, status)` — 5 rows |
| **Writer** | `src/grandpa/future_features.py` — added `2301d59d`, deleted `c40b58ab` |
| **Readers / runtime / CLI / API / migration / tests** | **None** |
| **User data?** | **No.** All 5 rows are `mode='simulation'`: Grandpa Presence (avatar, ready), AR Overlay (foundation), Wearable Bridge (foundation), Drone Connector (placeholder), Car Connector (placeholder) — pure scaffolding for features that never shipped |
| **Safe to delete?** | **Yes** |
| **Disposition** | **DELETE** |

---

#### 3. `communication_integration.db` — 16,384 bytes, mtime 2026-06-01

| | |
|---|---|
| **Schema** | `communication_notifications(id, created_at, service, sender, subject, summary, unread, redacted)` — **0 rows**; `pending_replies(id, created_at, service, recipient, draft, status)` — **0 rows** |
| **Writer** | `src/grandpa/communication_integration.py` — added `2301d59d`, deleted `c40b58ab` |
| **Readers / runtime / CLI / API / migration / tests** | **None** |
| **User data?** | **No — the database is completely empty.** |
| **Safe to delete?** | **Yes — no data exists to lose** |
| **Disposition** | **DELETE** |

---

#### 4. `real_world_tasks.db` — 12,288 bytes, mtime 2026-06-01

| | |
|---|---|
| **Schema** | `real_world_workflows(id, created_at, kind, query, status, plan_json)` — 10 rows |
| **Writer** | `src/grandpa/real_world_tasks.py` — added `2301d59d`, deleted `c40b58ab` |
| **Readers / runtime / CLI / API / migration / tests** | **None** |
| **User data?** | **Effectively no.** All 10 rows are identical: `('shopping', 'checkout payment', 'blocked')`. These are repeated developer test invocations, and **every one was blocked by the safety layer** — `browser_purchase` is a BLOCKED action. Incidentally a nice piece of evidence that the policy layer worked. |
| **Safe to delete?** | **Yes** |
| **Disposition** | **DELETE** — optionally screenshot the 10 blocked rows first as a safety-layer regression fixture |

---

#### 5. `sync_state.db` — 12,288 bytes, mtime 2026-06-01

| | |
|---|---|
| **Schema** | `sync_state(connector_id, items_synced, cursor, last_sync, error)` — 2 rows |
| **Writer** | No module matched by name. Written by the connector layer during the same burst. |
| **Readers / runtime / CLI / API / migration / tests** | **None** |
| **User data?** | **Indirectly.** `('hackernews', 5, '2026-05-24T12:05:15Z')` and `('obsidian', 2, '2026-06-01T05:58:50Z')`. These are **sync cursors**, not content — but `obsidian` implies the owner connected a real personal vault. The synced content lives in `knowledge.db`, which is **not** orphaned. |
| **Safe to delete?** | **Yes**, but with a caveat: deleting the cursor means a future re-enabled connector would re-sync from scratch rather than resume. |
| **Disposition** | **ARCHIVE, then delete.** It is 12 KB. Copy it aside before removing. |

---

#### 6. `autonomous_workflows.db` — 49,152 bytes, mtime 2026-06-03

| | |
|---|---|
| **Schema** | `autonomous_workflows(workflow_id, name, prompt, category, state, steps_json, created_at, updated_at, started_at, completed_at, checkpoint, summary, dry_run)` — **6 rows**; `autonomous_workflow_events(id, workflow_id, timestamp, event_type, step_id, message, metadata_json)` — **40 rows** |
| **Writer** | No module matched by name; written by the autonomous-workflow feature during the same burst |
| **Readers / runtime / CLI / API / migration** | **None** |
| **Tests** | ⚠️ **`tests/conftest.py` lists `tests/test_autonomous_workflows.py` in `_RELEASE_TEST_PATHS` — and that file does not exist.** A stale path, the same class of defect as the three phantom CI test files fixed by P0-2. Harmless (the marker simply never applies) but it should be removed. |
| **User data?** | **Yes — genuine user-initiated runs.** 6 workflows: "Downloads Organization" (`file_organization`, `waiting_approval`) and "Developer Startup" (`developer_startup`, `completed`), repeated across 2026-06-03/04/05. **All have `dry_run=1`** — nothing was actually executed. Two rows sit in `waiting_approval`: stale pending approvals for a feature that no longer exists. |
| **Safe to delete?** | **Yes**, after archiving. The 40 events are real behavioural history with some diagnostic value; nothing depends on them. |
| **Disposition** | **ARCHIVE, then delete.** Also remove the stale `conftest.py` path. |

---

#### 7. `mobile_integration.db` — 32,768 bytes, mtime 2026-06-01 — ⚠️ **HANDLE WITH CARE**

| | |
|---|---|
| **Schema** | `mobile_devices(device_id, created_at, name, paired, **pairing_hash**, last_seen_at, status_json, pairing_expires_at, **token_hash**, **permissions_json**, trusted)` — **10 rows**; `mobile_events(...)` — 5 rows; `mobile_commands`, `mobile_notifications`, `mobile_outbox` — **0 rows each** |
| **Writer** | `src/grandpa/mobile_integration.py` — added `2301d59d`, deleted `2cabd560` (2026-07-26) |
| **Readers / runtime / CLI / API / migration / tests** | **None** |
| **User data?** | **Yes, and it is credential-shaped.** 10 device rows, all named `'Pixel'` — the owner repeatedly pairing a real personal Android phone. 5 `pairing_created` events: *"Pairing code created for local Android companion."* **Mitigating: every row is `paired=0, trusted=0`**, so no live trust relationship exists, and `pairing_expires_at` means any codes are long expired. But the table carries `pairing_hash`, `token_hash`, and `permissions_json` columns. |
| **Safe to delete?** | **Yes — and deletion is the recommended outcome.** This is the one database where *leaving it in place* is the worse option: it is dormant credential material for a removed feature. |
| **Disposition** | **SECURE DELETE. Do not archive to any shared or synced location.** If a record is wanted, export only `(name, paired, trusted, created_at)` — never the hash columns. |

### Summary table

| Database | Size | Rows | User data | Disposition |
|---|---:|---:|---|---|
| `iot_smart_home.db` | 20 KB | 2 | No — demo fixtures | **DELETE** |
| `future_features.db` | 12 KB | 5 | No — simulation scaffolding | **DELETE** |
| `communication_integration.db` | 16 KB | **0** | No — empty | **DELETE** |
| `real_world_tasks.db` | 12 KB | 10 | No — repeated blocked tests | **DELETE** |
| `sync_state.db` | 12 KB | 2 | Indirect — connector cursors | **ARCHIVE → delete** |
| `autonomous_workflows.db` | 48 KB | 46 | Yes — dry-run history | **ARCHIVE → delete** |
| `mobile_integration.db` | 32 KB | 15 | **Yes — credential-shaped** | **SECURE DELETE** |
| **Total** | **152 KB** | | | |

> **[DECISION AD-021]** Adopt the dispositions above. **Nothing has been
> deleted by this analysis.** Execution requires your go-ahead (approval item
> A-4) and should be a single reviewed script that archives first and deletes
> second, with the archive written to a local, non-synced path.

**[RECOMMENDATION]** Also remove the stale `tests/test_autonomous_workflows.py`
entry from `_RELEASE_TEST_PATHS` in `tests/conftest.py`. It is a one-line fix
and the same defect class as the phantom CI paths.

**Scope note:** these seven total **152 KB**. This item is about correctness and
hygiene, not space. The reason it mattered was the possibility of user data —
now established: five have none, and the two that do are dry-run history and
dormant pairing hashes.

---

## AD-022 — CORRECTION: P1 is a policy-layer invariant, not a path-absence invariant

This corrects a claim in the discovery draft and in `AUDIT.md` §6. It changes no
recommendation, but it changes what the target architecture must *guarantee*,
so it must be stated precisely.

### What was claimed

> "Model output never becomes an action. `handle_local_action` is called only
> with *user* text." — `AUDIT.md` §6, repeated in the discovery draft as P1.

### What is actually true

**[FACT] There are two actuation funnels, not one**, and the claim holds for
only one of them.

**Funnel A — `handle_local_action` (natural language).** 12 call sites. Every
one passes user-originated text. **The claim holds here, exactly as stated.**

> **[CORRECTED by AD-023]** The descriptive wording is wrong for three of the
> twelve. `burnin.py` (×2) and `cli/doctor_cmd.py` pass **program-authored
> static literals**, not user-originated text. The **safety property stated
> below is unaffected** — no model-generated text enters Funnel A from any of
> the twelve — but "user-originated" overstates what was verified. See AD-023.

```
cli/ask.py · cli/chat_cmd.py · server/routes.py · server/api_routes.py
voice/assistant.py (×3) · voice/session.py · task_scheduler.py
burnin.py (×2) · cli/doctor_cmd.py
```

**Funnel B — `run_local_action` (structured payload).** 12 call sites. Most pass
hardcoded or user-derived payloads. **But two paths carry model-influenced
data:**

1. **Agent context gathering** — `agents/context.py:90` and
   `agents/goal_mode.py:381`. **Verified safe:** both pass a hardcoded literal
   `{"action_type": "desktop_summary", "target": "desktop", "dry_run": True}` —
   a read-only action with `dry_run=True`. No model output enters the payload.

2. **Skills invoked as agent tools** — `skills/registry/defaults.py:_pc_action`:
   ```python
   payload = {
       "action_type": params.get("action_type", action_type),
       "target": params.get("target", params.get("text", target)),
       "args": params.get("args", {}),
       ...
   }
   response = run_local_action(payload)
   ```
   `params` are supplied by the caller. And `skills/tool_adapter.py:1` states
   plainly: *"SkillTool — wraps a skill as a tool **that agents can invoke**."*
   `SkillManager.get_skill_tools()` is wired into the tool registry at
   `system/builder.py:150` whenever `config.skills.enabled`.

   **So the chain LLM → agent → ToolRegistry → SkillTool → `_pc_action` →
   `run_local_action` exists and is live.**

### Why the system is nonetheless safe

Model-influenced payloads reaching Funnel B are **still fully policy-gated**:
`desktop/kernel/risk.classify()` runs, unrecognised actions default to
`BLOCKED`, `shell_run` / `script_run` / `browser_purchase` are `BLOCKED`
outright, HIGH-risk actions require approval, and (post-remediation) synthetic
keyboard and mouse input require approval regardless of tier.

**The safety property is real. Its mechanism is different from what was
claimed.**

### The precise statement

> **[DECISION AD-022]** The invariant is:
>
> **"No action executes without passing risk classification and, where required,
> human approval — regardless of whether its parameters originated from a human,
> a skill, or a model."**
>
> The stronger property — *"model output never reaches the actuation layer"* —
> holds for the natural-language funnel only. It does **not** hold for the
> structured funnel, because agent-invocable skills are a designed feature.

### Consequences for the target architecture

1. **`PolicyEngine` (AD-006) is load-bearing, not merely tidying.** It is the
   *sole* thing standing between a model-chosen `action_type` and execution.
   This raises its priority.
2. **Provenance must be a first-class field.** Every `ActionRequest` should
   carry `origin ∈ {voice, direct, api, agent, skill, scheduler}` — the six
   shipped values, defined in `grandpa/policy/models.py` and described under
   P1a in `TARGET_ARCHITECTURE.md`. The policy table should be able to require
   approval based on origin — e.g. a `MEDIUM` action from `direct` may proceed
   while the same action from `agent` requires approval.
   `security/taint.py` already exists; this was named as its natural home.
   **[CORRECTED by AD-023]** That module is *not* unused — it is referenced
   from `tools/_stubs.py` and `core/events.py` defines `TAINT_VIOLATION`. Nor
   is it an execution-provenance model: `TaintLabel` describes **data
   sensitivity** for information-flow control, keyed by tool name, not who
   composed a request.

   **Not yet done.** Origin is recorded and nothing keys on it: the approval
   digest excludes it deliberately, `classify_risk` ignores it, and the
   approval token is random. Making policy origin-aware is Q-10, still open.
   Until it is answered, this vocabulary is audit-only — which is precisely
   what let D-5 widen it without touching a single stored approval.

   > **[SUPERSEDED by Q-10 / AD-023]** **Q-10 has since been answered: no.**
   > Policy is provenance-agnostic. Origin does not alter risk classification
   > or the approval requirement, and may never lower either. **The
   > `direct`-versus-`agent` approval example above is therefore an
   > illustration of a capability that was never adopted — it is not a
   > contract, and nothing may be built on it.** `direct` remains the
   > least-privilege coercion fallback for an unrecognised or absent origin,
   > which is only safe *because* no origin carries privilege.
   >
   > This changes no runtime behaviour: the sentence describes a capability
   > that was never built. The invariant is pinned executably in
   > `tests/test_action_origin_invariant.py` (Q-10E) across all six values.
   > The wording above is kept rather than deleted so the reasoning that led
   > here stays legible.
3. **The audit trail must record origin.** Today it cannot distinguish a
   user-typed action from a model-selected one.
4. **`config.skills.enabled` is a security-relevant setting** and should be
   documented as one.

**[RECOMMENDATION]** Add origin-tagging to Phase 4 alongside `PolicyEngine`. It
is a small addition at design time and expensive to retrofit.

**[OPEN QUESTION] Q-10 (new).** Should agent- and skill-originated actions
require approval at a *lower* risk threshold than user-typed ones? This is a
policy decision, not an architecture one, but the architecture must support it.

> **[RESOLVED — no.]** Recorded in the Part III ledger and in AD-023. Policy
> remains provenance-agnostic; provenance stays audit-only. The architecture
> does still *support* an origin-aware table — nothing prevents one being
> built later — but no such table is specified, authorised, or implied by
> this decision.

---

## AD-023 — `ActionOrigin` conflates three provenance dimensions, and the burn-in `direct` fallback is not a classification

Recorded from the 4.12C-DEC and 4.12D audits. This decision changes no runtime
behaviour. It exists so that the `direct` currently reaching the audit trail from
`burnin.py` cannot later be read as a deliberate provenance classification for
that harness.

### Evidence

**[FACT] `ActionOrigin` carries three dimensions in one enum.** Reading the six
values against their own documented definitions in `grandpa/policy/models.py`
and the P1a table in `TARGET_ARCHITECTURE.md`:

| Value | Initiator | Execution surface / modality | Action composer |
|---|---|---|---|
| `voice` | human | speech | human |
| `direct` | human | the CLI | human |
| `api` | not stated | the HTTP boundary | not stated |
| `scheduler` | a timer, no human present | — | not stated |
| `agent` | autonomous agent | — | **the agent itself** |
| `skill` | autonomous agent | `SkillTool` | **a model** |

Two earlier statements in this repository already record part of this split
without naming it. `dispatch/context.py`, written for 4.5G, observes that "two
of its six values are already surface-shaped and four are initiator-shaped"; and
the P1a table gives `api` no conceptual category at all, because a boundary is
not an actor class.

**[FACT] `agent` versus `skill` is a composer distinction and nothing else.**
Both are automated initiators reached through the same agent tool chain. P1a
states what separates them: "an agent reading its own context passes literals it
wrote, while a skill reached through `SkillTool` can be handed arguments a model
produced." Two of the six values are therefore already spent encoding *who
composed the action*, which is a different question from *who initiated it*.

The audit record confirms which question the field is meant to answer.
`pc_control` writes `origin` under the comment "the trail must distinguish a
user-typed action from a model-selected one" — composer language, on a field
whose other four values are initiator and surface labels.

These dimensions are **not** separate fields today. They are one enum whose
members answer different questions.

**[FACT] Three Funnel-A call sites are not user-authored.**

| Call site | Executes? | Initiator | Composer |
|---|---|---|---|
| `cli/doctor_cmd.py` | no (`execute=False`) | a person running `grandpa doctor` | a hardcoded probe string |
| `burnin.py` soak loop | no (`execute=False`) | a person running the harness | a static command list |
| `burnin.py` scenario runner | **yes** (`execute=True`, 4 scenarios) | a person running the harness | the static `_scenario_pack` table |

Only the third reaches real actuation, and therefore an approval row and an
audit line. In all three the human starts the harness but composes none of the
commands.

**[FACT] The `direct` recorded on that path is a dataclass default, not a
decision.** `LocalActionRequest.origin` defaults to `DEFAULT_ACTION_ORIGIN`.
`handle_local_action` accepts no `origin`, so nothing on the burn-in path ever
names one and the default is what reaches the approval database and the audit
log. `_coerce_origin` maps anything unrecognised to the same value.

### The decisions

> **[DECISION AD-023 a]** `ActionOrigin` conflates initiator, execution
> surface/modality, and action composer. This is recorded as a finding about the
> existing vocabulary, not as a claim that these are already separate fields.

> **[DECISION AD-023 b]** The `direct` currently recorded for burn-in's
> executing scenarios is an **existing fallback behaviour, not an approved
> semantic classification**. It must not be cited as precedent that burn-in is
> direct-origin.

> **[DECISION AD-023 c]** No new `ActionOrigin` value is added for burn-in.
> Neither `burnin.py` nor `cli/doctor_cmd.py` is stamped with an existing value.
> No burn-in-specific provenance vocabulary is introduced. All six shipped values
> and the current compatibility behaviour are preserved unchanged.

> **[DECISION AD-023 d]** The architectural **direction** is an *additive second
> provenance dimension* alongside the existing `ActionOrigin`, rather than a
> refactor of it. A refactor is rejected because stored `agent` and `skill` rows
> already encode composer information that a naive split would drop.
>
> **This is a direction, not an approved implementation contract.** No field,
> column, or vocabulary is authorised by this decision.
>
> **Narrowed by Q-10.** With policy confirmed provenance-agnostic, this
> direction survives only as a possible improvement to **audit and
> observability fidelity**. It is not a policy requirement, and no security
> decision depends on it.

> **[DECISION AD-023 e]** Implementation was deferred until Q-10 was answered,
> because that answer defines what a second dimension would have to
> distinguish. Designing the field beforehand would fix a vocabulary without
> knowing its consumer — the failure 4.5G avoided when it removed
> `RequestContext.surface` rather than let the first consumer invent the
> contract.
>
> **Q-10 is now answered: no.** The policy layer consumes no provenance at
> all. `ActionOrigin` is not a risk or approval decision input, and origin may
> never lower a requirement.
>
> **Consequence for this decision.** A second provenance dimension is
> therefore **not justified by policy need**. Its only remaining motivation is
> audit fidelity — the three call sites in the evidence above whose composer
> the vocabulary cannot express. That is a materially weaker mandate than the
> one assumed when this decision was written, and it remains deferred: the
> next thing that would justify building it is a stated audit requirement, not
> a security one.

### Corrections carried by this decision

1. **AD-022's Funnel-A wording.** "Every one passes user-originated text" is
   wrong for `burnin.py` (×2) and `cli/doctor_cmd.py`. The safety property is
   unaffected: no model-generated text enters Funnel A from any of the twelve
   call sites, and program-authored probes do not weaken that guarantee.
2. **`security/taint.py` is not unused.** It is referenced from
   `tools/_stubs.py`, and `core/events.py` defines `TAINT_VIOLATION`. It is also
   not an execution-composer model: `TaintLabel` describes data sensitivity for
   information-flow control, keyed by tool name.

### Frozen by this decision

Unchanged, and not to be altered on the strength of this record:

- the six `ActionOrigin` values and `DEFAULT_ACTION_ORIGIN`
- `LocalActionRequest.origin` behaviour, including the coercion fallback
- the `handle_local_action` signature
- action-digest semantics — origin remains excluded
- approval semantics, risk classification, emergency stop, dry-run
- the guard forbidding `origin=` in `burnin.py` and `cli/doctor_cmd.py`

### Scope

Documentation only. No production behaviour, schema, or provenance-vocabulary
change accompanies this decision.

---

## AD-024 — Funnel-A approval does not satisfy `desktop_automation`'s confirmation contract; confirmation-requiring automation stays unexposed until it is under the structured actuation boundary

Recorded from the 4.14F preflight, the 4.14F-DECISION characterization, and the
4.14G decision slice. This decision changes no runtime behaviour. It exists
because ten natural-language commands the parser advertises cannot execute, and
the reason they cannot is a gate nobody chose — so the next person to find it
does not "fix" it by passing a boolean.

### Evidence

**[FACT] The chain has two confirmation gates and only the first can be
satisfied.** `classify_permission` returns `requires_confirmation` for every
`automation` result unconditionally (`local_actions.py:600`, no target
inspection). `create_pending` stages the exact `kind` + `target` with an
out-of-band token; `authorize_approval` verifies it under a five-attempt cap;
`claim_pending` claims it atomically. `_execute` then calls
`execute_automation(result.target)` at `local_actions.py:2006` **passing neither
`confirmed=` nor `confirm_callback=`**, so `desktop_automation._check_permission`
sees `confirmed=False` and `callback=None` and returns `cancelled`.

**[FACT] Measured behaviour of all fourteen parser-minted targets.** Characterized
in-process with a stub `pyautogui` and the 0.75 s cooldown neutralised; no
hardware touched, no database opened:

| Outcome | Targets | Count |
|---|---|---|
| `cancelled` | `type\|*`, `press\|enter`, `press\|tab`, `press\|escape`, `hotkey\|ctrl+c`, `hotkey\|ctrl+v`, `hotkey\|alt+tab`, `click_center`, `click_highlighted` | 9 |
| `unsupported` | `focus\|notepad` — no handler exists; the `focus\|notepad\|\|type\|…` chain aborts here | 1 |
| `handled` (actuates) | `scroll\|down` → `scroll(-5)`, `scroll\|up` → `scroll(5)`, `move_center` → `moveTo(960,540)` | 3 |
| `handled`, but **not reachable through Funnel A** | `focus\|chrome` → `hotkey('alt','tab')` — shadowed by the window parser, see below | 1 |

**[FACT] `confirmed=True` would revive eight targets, not six.** Measured across
all nine `cancelled` targets: `type|hello`, `press|enter`, `press|tab`,
`press|escape`, `hotkey|ctrl+c`, `hotkey|ctrl+v`, `hotkey|alt+tab` and
`click_center` all become `handled` and reach `pyautogui`. Only
`click_highlighted` stays `unsupported`, because it has no handler. An earlier
figure of six came from a six-target probe that omitted `press|tab` and
`press|escape`; they take the same branch and revive too.

**[FACT] `confirmed=True` cannot bypass a block.** `_check_permission` tests
`blocked` before it tests `confirmed`. Measured: `type|my password is hunter2`,
`delete system32` and `run|powershell` all remain `blocked` with
`confirmed=True`. The blast radius of a shortcut would be bounded to the
confirm-required tier — which is why the shortcut is tempting, and why it must
still be refused.

**[FACT] There is exactly one production caller.** `grep -rn "execute_automation"
src/` returns `local_actions.py:2006` and the module's own definition and
`__all__`. It passes neither parameter. The `confirm_callback` occurrences in
`agent/executor.py`, `agent/runtime.py`, `agents/operative.py`,
`agents/native_react.py` and `agents/monitor_operative.py` are a different
callback — signature `Callable[[str], bool]`, not
`ConfirmationCallback(spec, permission)` — and none reaches this module.

**[FACT] The gate post-dates the approval system and was never wired to it.**
`02403254 add approval system for local actions` landed 2026-05-24.
`27e87d72 feat(desktop): add permission checks for automation actions` landed
2026-06-12 and `git merge-base --is-ancestor` confirms it is not an ancestor of
the approval commit. That commit touched only `desktop_automation.py` and its
own tests. `git log -S "confirm_callback" -- src/grandpa/local_actions.py`
returns nothing: the callback was never wired, at any point in history.

**[FACT] The composition is untested in both directions.** Every existing test
(`tests/test_desktop_automation.py`) calls `execute_automation` or
`_execute_with_pyautogui` **directly**, covering `confirmed=True`,
`confirmed=False` and `confirm_callback` in isolation. No test goes through
`approve_pending_action`. The approval-flow suites
(`test_local_action_approve_endpoint.py`, `test_approval_execution_race.py`,
`test_local_action_approval_tokens.py`) all stage `kind="url"`. Nothing asserts
that a locally-approved automation action executes, and nothing asserts that it
is refused — which is why nine dead commands went unnoticed.

**[FACT] Fail-closed on a missing callback is an endorsed pattern elsewhere in
this repository.** `ACTION_ORIGIN_AUDIT.md:135-138` records: "`ToolExecutor`
fails **closed** on confirmation (`tools/_stubs.py:209-219`): a tool requiring
confirmation with no `confirm_callback` is refused, not executed." The automation
gate behaves identically. The two cases differ in one respect that matters here:
for `ToolExecutor` the refusal is the only gate, whereas for automation a
token-bound, target-specific approval has already succeeded upstream and is then
discarded at the call site.

**[FACT] `focus|chrome` is classified `safe` and performs synthetic keyboard
input — but nothing reaches it through Funnel A.** `_SAFE_ACTIONS` contains
`focus`, so the spec passes `_check_permission` without confirmation, and its
handler executes `pyautogui.hotkey("alt", "tab")`. Its honest `pc_control`
equivalent is `keyboard_hotkey`, which is MEDIUM **and** in
`APPROVAL_REQUIRED_ACTIONS`. The name says window focus; the code sends a
keystroke. That capability is real and still present in the module; what the
next FACT establishes is that no natural-language command arrives at it.

**[FACT] Two automation mints never reach the automation parser — for two
different reasons.** Found by 4.14H; the mechanism corrected by 4.14J.

| Command | `_parse_automation_action` would mint | Why it never arrives |
|---|---|---|
| `switch window` | `hotkey\|alt+tab` (`:1211`) | **`_normalise` rewrites it before any parser runs.** `re.sub(r"\bswitch\b", "focus", cmd)` at `local_actions.py:684` turns the command into `focus window`, and the verb regex at `:703` keeps it that way. The literal `== "switch window"` test at `:1211` is therefore **structurally unreachable**, independently of parser ordering |
| `focus chrome` | `focus\|chrome` (`:1220`) | **Parser ordering.** `handle_local_action` consults `_parse_window_action` (`:775`) before `_parse_automation_action` (`:787`), and the window parser claims it at `:1282` as `kind="window"`, target `focus\|chrome` |

4.14H attributed both to the window parser. That is right for `focus chrome`
and wrong for `switch window`, which is already dead one stage earlier — a
normaliser rewrite, not a dispatch race. Both remain unreachable; only the
mechanism differs.

Three layers have to be kept apart here, and conflating them is what produced
the error this FACT corrects:

1. **`desktop_automation`'s internal capability** — `focus|chrome` and
   `hotkey|alt+tab` are implemented, classified, and would actuate if invoked.
2. **Funnel-A parser reachability** — neither is reachable, because an earlier
   parser claims the command. The automation surface is narrower than its own
   mint list suggests.
3. **The window branch that already routes** — `focus` is in
   `_WINDOW_ROUTED_VERBS` (`:1752`), so since 4.14D `focus chrome` executes
   *behind* `pc_control` as `focus_window`, with the emergency stop and risk
   classification that branch gained. The shadowing is therefore benign: it
   diverts the command onto the guarded path, not around it.

`switch window`'s window-side resolution is a **fuzzy** match against the
installed-app inventory and so varies per machine; only the fact that it never
reaches the automation branch is stable.

**[FACT] Nothing on this path is behind the structured boundary.**
`desktop_automation` never consults `pc_control`'s emergency stop — its only
`emergency` symbol is `emergency_stop_placeholder()`, which returns a string
describing a design and is called by nothing. `active_window_is_protected` has
exactly two call sites, both inside `pc_control._preflight_guard`, which fires
only for `{keyboard_type, keyboard_hotkey, mouse_click, mouse_drag}` — so
`mouse_move` and `mouse_scroll` receive no protected-window guard even under
`pc_control`. Conversely `desktop_automation` has a `COOLDOWN_SECONDS = 0.75`
rate limit and a `_log_automation` audit line that `pc_control` does not have;
`MIGRATION_PLAN` §4.14 ("Wire `rate_limiter` into `PolicyEngine`") is not done.

**[FACT] A structured, live, `pc_control`-gated replacement already exists.**
Established by 4.14J. `grandpa/automation/` implements the *same intent set* as
the Funnel-A automation branch and routes it through the mandatory boundary:

| Intent | `grandpa/automation/` | `pc_control` action type | `desktop_automation` equivalent |
|---|---|---|---|
| type / write | `planner.py:145` → `keyboard.py:11` | `keyboard_type` | `type\|{text}` |
| press / paste / copy / hotkey | `planner.py:156,163` → `keyboard.py:17` | `keyboard_hotkey` | `press\|*`, `hotkey\|*` |
| scroll | `planner.py:122` → `mouse.py:22` | `mouse_scroll` | `scroll\|{direction}` |
| mouse movement | `mouse.py:17` | `mouse_move` | `move_center` |
| click | `mouse.py:21` | `mouse_click` | `click_center` |

`automation/executor.py:165-167` calls `pc_control.run_local_action`, so this
path is **already** an enforced structured-actuation path: risk classification,
`APPROVAL_REQUIRED_ACTIONS`, the protected-active-window guard and the emergency
stop all apply to it, and none of them apply to the `desktop_automation` path
described in the FACT above.

It is wired to live surfaces, not shelved:

- `cli/automation_cmd.py:25,33,35` — `service.handle()`, `.confirm(token)`,
  `.reject(token)`
- `planner/executor.py:187,407` — `.handle(choice)`,
  `.confirm(result.confirmation_token)`
- `cli/chat_cmd.py:1420,1669` and `voice/assistant.py:51,256` — both thread the
  service into the planner executor

(`agent/executor.py:220` is **not** a live caller: it returns a canned
`{"status": "success"}` rather than driving the service.)

The source names the duplication itself. `automation/planner.py:139-142`:
"… so both phrasings take one path to `keyboard_type` instead of reaching it
through two different executors."

The development record separates the two stacks cleanly.
`git log -S "_parse_automation_action"` returns exactly one commit
(`241311b3 add safe desktop automation layer`) — the branch was never revisited.
`desktop_automation.py` has six commits, all ending 2026-06-12;
`grandpa/automation/` was actively developed through 2026-08-04. This is
consistent with `MODULE_OWNERSHIP.md:248` (`desktop_automation.py` … **ABSORB**)
and `CURRENT_ARCHITECTURE.md:574`, which already list the module as a duplicate.

### The decisions

> **[DECISION AD-024 a]** Funnel-A local approval **does not** satisfy
> `desktop_automation`'s independent confirmation contract. Approval staged and
> claimed by `local_action_approvals` authorizes release of the staged action
> into the executor; it is not an assertion that the inner allowlist's
> confirmation requirement has been met.

> **[DECISION AD-024 b]** Confirmation-requiring automation **must not** be made
> executable by passing `confirmed=True` from `local_actions`, nor by supplying a
> `confirm_callback` that returns `True` unconditionally, nor by adding
> `automation` verbs to `_SAFE_ACTIONS`. Any of these would move synthetic
> keyboard and mouse input into production while it is still outside the
> enforcement boundary.

> **[DECISION AD-024 c]** The nine currently unreachable confirmation-requiring
> commands **must not be revived through a shortcut**. They stay unreachable
> until they can execute under the structured boundary. Reviving them locally
> would also make the double-gating found in 4.14F user-facing: each maps to
> `keyboard_type`, `keyboard_hotkey` or `mouse_click`, all of which are in
> `APPROVAL_REQUIRED_ACTIONS`, so a later migration would then owe the operator
> two credentials from two stores for one intent.

> **[DECISION AD-024 d]** Future execution of these commands **must** go through
> the structured desktop-actuation enforcement architecture. This follows the
> standing invariant, not a new one: `ACTION_ORIGIN_AUDIT.md` records that
> "`run_local_action` is the single mandatory enforcement boundary for desktop
> actuation… risk is computed, never accepted", and `TARGET_ARCHITECTURE.md` P1
> requires that every action "passes through exactly one `PolicyEngine` that
> classifies risk and enforces approval before execution."
>
> **Amended by 4.14K — the architecture is not future work.** This decision was
> written as though the structured enforcement architecture had yet to be built.
> It exists, it is live, and it already covers every one of these intents:
> `grandpa/automation/` reaches `pc_control.run_local_action` and is wired to the
> CLI, planner, chat and voice surfaces (see the FACT above). The requirement
> stated here is therefore **satisfiable today** rather than pending.
>
> **The decision itself is unchanged.** What changes is the shape of the
> remaining question, which is now a disposition question about the *duplicate*
> rather than an architecture question about the *replacement*:
>
> > Should Funnel-A's duplicate automation parser be **deleted**, **bridged** to
> > the structured automation service, or **frozen** until the
> > `MIGRATION_PLAN` §5.11 absorption?
>
> Each option is supported by repository evidence and each has a different cost:
> deletion retires four committed assertions in `tests/test_local_actions.py`;
> bridging is the largest change but makes the dead commands work under the
> existing gates; freezing defers. **This addendum does not choose among them**
> — it records that the choice is now the open item, and that it is a product
> question of the same kind AD-024 itself answered.
>
> **Answered by AD-025:** retire. That decision selects among these three
> options; nothing else in AD-024 changes.

> **[DECISION AD-024 e]** The **three** automation behaviours reachable through
> Funnel A — `scroll|down`, `scroll|up` and `move_center` — are **also in scope
> for review**, and are not grandfathered by this decision. They execute on the
> local confirmation alone, outside the structured boundary, and their `safe`
> classification has not been ratified. This decision does not remove them; it
> records that the classification is unreviewed.
>
> **Amended by 4.14I.** This decision originally said *four*, counting
> `focus|chrome` as a live behaviour and naming it as the specific reason for the
> review. That was wrong: `focus|chrome` is shadowed by the window parser and no
> Funnel-A command reaches it, so the discrepancy it illustrates — a spec
> classified `safe` that sends a keystroke — is **latent in
> `desktop_automation`, not live in Funnel A**. It stays in scope as a hazard
> that a parser change could make live without anyone noticing, which is why
> `tests/test_automation_confirmation_contract.py` pins both the behaviour and
> the shadowing. The review it triggers is unchanged; only the count and the
> reachability claim are corrected.

> **[DECISION AD-024 f]** The two blockers found in 4.14F remain **separate and
> unresolved** by this decision: `_execute_via_pc_control` forwards only
> `{action_type, target}` and has **no `args` channel**, while `mouse_scroll`
> requires an integer amount (`int("down")` raises) and `mouse_move` reads
> `x`/`y` from `args` and ignores `target` entirely — so routing `move_center`
> through the seam as it stands would move the cursor to `(0, 0)` rather than the
> screen centre. Neither is fixed by choosing C, and neither may be worked around
> by widening the seam without its own decision.
>
> **Clarified by 4.14K.** `grandpa/automation/` does not hit this blocker,
> because it builds full payloads rather than passing a bare target:
> `keyboard.py:13` sends `args={"text": …}`, `keyboard.py:20` sends
> `args={"keys": […]}`, and `mouse.py:17,21,22` send coordinate and amount
> args. It has solved the args problem **for its own execution model**.
>
> That is not transferable. `_execute_via_pc_control` in `local_actions.py`
> still forwards `{action_type, target}` and nothing else, so **AD-024 f stands
> unchanged for any direct Funnel-A migration**: routing `move_center` or
> `scroll|down` through the local seam remains blocked on exactly the grounds
> stated above. The existence of a stack that solves the problem elsewhere is
> not permission to widen the local seam.

> **[DECISION AD-024 g]** Absorption of `desktop_automation.py` remains future
> work under `MIGRATION_PLAN` §5.11 ("Absorb `desktop_automation.py`,
> `desktop_context.py`, `smart_automation.py`", 1,491 LOC). This decision states
> the semantics that absorption must carry; it does not schedule it and does not
> authorise it.

> **[DECISION AD-024 h]** No production behaviour changes in this slice.
> Documentation only.

### Corrections carried by this decision

- **"Automation is the only genuine double-gating branch" is too coarse.**
  Measured, of the targets that actually actuate, `scroll` → `mouse_scroll` and
  `move_center` → `mouse_move` are MEDIUM but **not** approval-required, so they
  are not double-gated at all. `focus|chrome` would be, via its honest
  `keyboard_hotkey` mapping — but 4.14I establishes it is unreachable through
  Funnel A, so **no reachable automation target is double-gated today**. The
  double-gate is a property of the nine unreachable confirmation-requiring
  targets, which is where AD-024 c already places it. This sharpens the evidence
  and changes neither Decision C nor the security conclusion: the reachable
  three still actuate outside the enforcement boundary, which is the finding the
  decision rests on.
- **`focus|chrome` was described as one of four live behaviours.** Corrected by
  4.14I to three reachable behaviours; see the shadowing FACT above.
- **"The inner gate is a dangling wire" overstated the case.** The fail-closed
  pattern it implements is documented and endorsed for `ToolExecutor`
  (`ACTION_ORIGIN_AUDIT.md:135-138`). What is undecided is its composition with
  an upstream approval, not the pattern itself.
- **Eight targets, not six, would be revived by `confirmed=True`.**

### Relationship to standing decisions

- **AD-013 (wire it or delete it; no third state)** is in tension with the
  current arrangement: a gate that is present, reachable and unsatisfiable is a
  third state. AD-024 resolves that tension in the direction of *neither wire nor
  delete yet* — the commands are withdrawn from reach, and the gate's disposition
  is settled by §5.11 absorption, not by this slice.
- **AD-023 (Funnel-A provenance)** is unaffected and explains part of the cost:
  `execute_automation` has no `origin` parameter at all, so nothing on this path
  can carry provenance today. Bringing these actions under the structured
  boundary is also what would finally give them one.
- **GAP-03** already names the two disjoint policy models; the automation
  allowlist's `{safe, confirm_required, dangerous, blocked}` is a third
  vocabulary inside the NL path. Its `[RECOMMENDATION]` — generalise
  `APPROVAL_REQUIRED_ACTIONS` as an axis orthogonal to the risk tier, do not
  re-derive it — is the rule that AD-024 b and c protect.
- **`MIGRATION_PLAN` §4.13** ("One approval store, out-of-band code") is
  unchanged and remains a prerequisite for any migration that would otherwise
  demand two credentials.

### Frozen by this decision

Until superseded:

- the `execute_automation` call at `local_actions.py:2006` passes neither
  `confirmed` nor `confirm_callback`
- `_SAFE_ACTIONS`, `_CONFIRM_REQUIRED_ACTIONS`, `_DANGEROUS_ACTIONS` and
  `_BLOCKED_SPEC_PATTERNS` membership
- the `cancelled` / `unsupported` / `handled` / `blocked` outcomes of all
  fourteen parser-minted targets
- `classify_permission` returning `requires_confirmation` for every `automation`
  result
- `COOLDOWN_SECONDS = 0.75` and the `_log_automation` audit line

### Scope

Documentation only. No production code, test, database, schema, approval-store
or classification change accompanies this decision. The characterization tests
that would pin the behaviour above are deliberately **not** written in this
slice; they are written to match this decision, not before it.

---

## AD-025 — Retire Funnel-A's duplicate automation execution path; `grandpa/automation/` is the canonical structured automation stack

Recorded from the 4.14J duplicate/replacement audit and the 4.14K addendum. This
decision selects among the three options AD-024 d left open. It changes no
runtime behaviour and **does not authorise deleting any code**.

### Evidence

All of the following is established in AD-024's evidence section and in 4.14J;
it is restated here only in the compressed form the decision rests on.

**[FACT] The structured implementation already exists and is canonical in
practice.** `grandpa/automation/` implements the same intent set as the Funnel-A
automation branch:

| Intent | `grandpa/automation/` | `pc_control` action type |
|---|---|---|
| type / write | `planner.py:145` → `keyboard.py:11` | `keyboard_type` |
| press / paste / copy / hotkey | `planner.py:156,163` → `keyboard.py:17` | `keyboard_hotkey` |
| scroll | `planner.py:122` → `mouse.py:22` | `mouse_scroll` |
| mouse movement | `mouse.py:17` | `mouse_move` |
| click | `mouse.py:21` | `mouse_click` |

**[FACT] It builds the typed arguments the actions require.** `keyboard.py:13`
sends `args={"text": …}`; `keyboard.py:20` sends `args={"keys": […]}`;
`mouse.py:17,21,22` send coordinate and amount args. This is the capability the
Funnel-A seam lacks and, per AD-024 f as clarified by 4.14K, may not acquire by
being widened.

**[FACT] It routes through the mandatory boundary.**
`automation/executor.py:165-167` calls `pc_control.run_local_action`, so risk
classification, `APPROVAL_REQUIRED_ACTIONS`, the protected-active-window guard
and the emergency stop all apply.

**[FACT] It is wired to live surfaces.** `cli/automation_cmd.py:25,33,35`;
`planner/executor.py:187,407`; and `cli/chat_cmd.py:1420,1669` and
`voice/assistant.py:51,256`, which thread the service into the planner executor.
(`agent/executor.py:220` is not a live caller — it returns a canned response.)

**[FACT] Retirement is the already-documented disposition.**
`MODULE_OWNERSHIP.md:248` states `desktop_automation.py` … **ABSORB**;
`MODULE_OWNERSHIP.md:245` and `CURRENT_ARCHITECTURE.md:574` list it among the
duplicates; `MIGRATION_PLAN` §5.11 schedules the absorption.

**[FACT] The Funnel-A branch has no documented production dependency and no
restoration plan.** `git log -S "_parse_automation_action"` returns exactly one
commit (`241311b3`); the branch was never revisited. `desktop_automation.py`'s
six commits all end 2026-06-12, while `grandpa/automation/` was developed
through 2026-08-04. No document, test or commit proposes reviving the dead
commands. `press|tab`, `press|escape`, `click_highlighted` and `copy selection`
have no test or documentation reference at all outside the 4.14H
characterization file.

### The decisions

> **[DECISION AD-025 a]** The duplicate Funnel-A automation execution path is
> **retired**, not bridged. `grandpa/automation/` is the canonical structured
> automation stack for keyboard and mouse actuation.

> **[DECISION AD-025 b]** **Bridging is rejected.** Bridging would wire Funnel A
> into the structured service so the ten dead commands begin working. It is
> rejected on the evidence, not on effort: it would preserve a second natural-
> language entry point to a capability that already has one, and the duplication
> — not the dead commands — is the defect the architecture documents already
> name. It would also be the largest of the three changes while adding no
> capability the product does not already have through the CLI, planner, chat
> and voice surfaces.

> **[DECISION AD-025 c]** **Freezing indefinitely is rejected.** Freezing was
> defensible while the replacement was unproven; 4.14J established it is live on
> four surfaces. What freezing preserves is a parser that advertises ten
> commands it cannot execute and three that actuate outside the enforcement
> boundary — a standing misrepresentation to the operator and a standing
> violation of the `ACTION_ORIGIN_AUDIT` invariant. Deferral without an endpoint
> is how the third state AD-013 forbids becomes permanent.

> **[DECISION AD-025 d]** **This decision does not authorise deleting code.** No
> parser branch, module, or test may be removed under it. Retirement is
> implemented in a later slice, scoped and reviewed on its own terms, and
> sequenced with the `MIGRATION_PLAN` §5.11 absorption rather than ahead of it.

> **[DECISION AD-025 e]** **Existing tests pin the legacy parser and must be
> retired or amended deliberately.** `tests/test_local_actions.py:199-236`
> asserts `status`, `kind`, exact target and confirmation wording for
> `type hello`, `type hello in notepad`, `press enter` and `copy selected text`;
> `tests/test_automation_confirmation_contract.py` (4.14H) pins all fourteen
> targets including the cancelled and shadowed ones. These are correct records of
> current behaviour, not obstacles: the implementation slice retires them
> explicitly, stating what each stopped protecting, and does not delete them as
> incidental cleanup.

> **[DECISION AD-025 f]** **AD-024 remains authoritative until retirement is
> implemented.** Funnel-A local approval still does not satisfy
> `desktop_automation`'s independent confirmation contract, and the three
> shortcuts AD-024 b forbids — `confirmed=True`, an unconditional
> `confirm_callback`, and widening `_SAFE_ACTIONS` — remain forbidden. Choosing
> retirement is not a reason to make the doomed path work first.

> **[DECISION AD-025 g]** No production behaviour changes in this slice.
> Documentation only.

### What this decision does not settle

- **The three reachable behaviours.** `scroll|down`, `scroll|up` and
  `move_center` actuate today, outside the boundary. AD-024 e keeps their `safe`
  classification unratified; retirement is the eventual answer, but the interim
  exposure is unchanged by this decision and is not authorised to persist beyond
  the implementation slice.
- **The seam.** AD-024 f stands: `_execute_via_pc_control` still forwards only
  `{action_type, target}`, and retirement removes the need to widen it rather
  than resolving the question of whether it could be widened.
- **Sequencing against §5.11.** Whether retirement lands before, with, or as part
  of the `desktop_automation.py` absorption is left to the implementation slice.

### Scope

Documentation only. No production code, test, database, schema, approval-store
or classification change accompanies this decision. It selects among options
AD-024 d recorded; it authorises no removal.

---

## AD-026 — Retiring the Funnel-A automation parser intentionally removes three undocumented HTTP capabilities

Recorded from the 4.14M implementation preflight and the 4.14N surface-coverage
audit. This decision resolves the one question AD-025 assumed rather than
established: whether the capabilities retirement removes from the HTTP surfaces
must be preserved first. They must not. This decision changes no runtime
behaviour and authorises no code removal — AD-025 d still governs that.

### Evidence

**[FACT] Three commands work today and stop working after retirement.**
`scroll down`, `scroll up` and `move mouse to center` are the only Funnel-A
automation targets that actuate (4.14F, 4.14H). Every automation result is
`requires_confirmation` at `local_actions.py:600`, so no surface actuates
in-request; the commands stage a pending row and complete only through
`approve_pending_action`.

**[FACT] The genuine loss is confined to two HTTP surfaces, and they share one
completion route.** 4.14N measured `approve_pending_action`'s production call
sites: `server/routes.py:1359` (`POST /v1/local-actions/{id}/approve`, live,
out-of-band code) and `server/api_routes.py:1803`, which is **dead** because its
call site at `:1715-1720` hardcodes `confirmed=False` under AD-024's predecessor
decision (4.12K-DEC). So:

| Surface | Entry | Stages | Can complete |
|---|---|---|---|
| `/v1/chat/completions` | `routes.py:328` | yes | yes, via the shared approve route |
| `/v1/voice/command` | `api_routes.py:1797` | yes | yes, via the same shared route |
| `task_scheduler` | `task_scheduler.py:619` | yes | **no** — no `approve_pending_action` in the module |
| `composition/ask_handlers` | `ask_handlers.py:95` | yes | **no** — no approval in the handler chain |

**This corrects 4.14M**, which reported the regression as covering four
surfaces. `task_scheduler` and `ask` can only file a pending row that a human
must complete elsewhere; they never actuated anything. The capability loss is
narrower and shallower than first stated.

**[FACT] No structured replacement exists on those surfaces.** `grep -c` for
`WindowsCommandPipeline|ScreenAutomationService|automation_service` returns **0**
in `server/routes.py`, `server/api_routes.py`, `task_scheduler.py` and
`composition/ask_handlers.py`. The only HTTP automation routes
(`/v1/automation/diagnostics`, `/workflows`, `/workflows/{name}/simulate`,
`routes.py:1070-1091`) import `grandpa.smart_automation` — a different module
from the canonical `grandpa/automation/`.

**[FACT] The exposure is accidental, not designed.** `routes.py:328` forwards
arbitrary free text into Funnel A; these commands are reachable only because of
that generality. No route names them, no user-guide documents them, and no test
covers them on any of the four surfaces — `scroll down` / `scroll up` /
`move mouse to center` appear in `tests/` only in
`test_automation_confirmation_contract.py` (4.14H, in-process) and
`test_screen_automation_v2.py` (the structured stack).

**[FACT] Cross-surface parity already has an owner, and it is not this slice.**
`GAP-02` names this exact failure mode: "'Check my email' works in `chat`,
`voice/assistant`, and `voice-operator`; it does not work in `ask` or over HTTP.
Every new handler requires six correct edits, and there is no mechanism that
notices when one is missed." Its target is one `IntentDispatcher`
(`TARGET_ARCHITECTURE.md` §4.1), scheduled as `MIGRATION_PLAN` §4.8-4.10, whose
§4.10 requires "End-to-end test per surface asserting **identical** capability
sets | `tests/dispatch/test_parity.py` **(new)**". That file does not exist:
`tests/dispatch/` holds only `test_action_module_adapters.py`,
`test_contract_shapes.py`, `test_dispatch_contract.py` and `test_golden_order.py`.

### The decisions

> **[DECISION AD-026 a]** Retirement of the Funnel-A automation parser
> **intentionally removes** the currently reachable HTTP exposure of
> `scroll down`, `scroll up` and `move mouse to center` via
> `/v1/chat/completions` and `/v1/voice/command`. The removal is accepted, and
> is recorded here so that it is a documented consequence rather than a silent
> regression discovered later.

> **[DECISION AD-026 b]** These three behaviours are **not a supported public
> API contract**. No route, document, user guide or test represents them as
> supported; they are reachable only because the chat route forwards arbitrary
> free text into Funnel A. Their removal is the withdrawal of an accidental
> exposure, not the breaking of a promise.

> **[DECISION AD-026 c]** **No replacement bridge is introduced.** Adding
> `WindowsCommandPipeline`, `ScreenAutomationService`, or any other ad-hoc
> automation path to the HTTP, scheduler or `ask` surfaces is **not authorised**
> by this decision or by AD-025. Hand-patching four surfaces would pre-empt the
> dispatcher design GAP-02 specifies.

> **[DECISION AD-026 d]** **Cross-surface capability parity remains GAP-02's
> responsibility.** If these intents are to work over HTTP again, they return
> through the `IntentDispatcher` unification (`MIGRATION_PLAN` §4.8-4.10) and are
> proved by the parity test §4.10 requires — not by a bridge added to make a
> retirement look lossless.

> **[DECISION AD-026 e]** **`grandpa/automation/` remains canonical**, exactly as
> AD-025 a states. Nothing here reopens the choice between retiring, bridging and
> freezing; this decision only settles whether retirement must be sequenced
> behind surface coverage. It must not.

> **[DECISION AD-026 f]** **AD-024 and AD-025 are unchanged.** AD-024 remains
> authoritative for the independent confirmation contract and its three forbidden
> shortcuts until retirement is implemented; AD-025 d still means no code or test
> may be removed without its own slice.

> **[DECISION AD-026 g]** No production behaviour changes in this slice.
> Documentation only.

### What this decision does not settle

- **The scheduler and `ask` staging behaviour.** Both will stop filing pending
  automation rows. Since neither could complete one, nothing that worked stops
  working — but if a workflow depended on a human completing a
  scheduler-staged row through the approve route, that path also ends. No
  evidence of such a workflow was found.
- **Whether the three intents should return over HTTP later.** That is GAP-02's
  scope and is neither promised nor foreclosed here.
- **The implementation.** AD-025 d stands: retirement is a separate, reviewed
  slice.

### Scope

Documentation only. No production code, test, database, schema, approval-store
or classification change accompanies this decision. No parity test is created.
`GAP-02` and `MIGRATION_PLAN` are cited, not modified.

---

## AD-027 — `security/rate_limiter.py` is deleted, not wired; no runtime rate limiting is introduced

Recorded from the Plan-Row-4.14 preflight and the DELETE impact audit. This
decision **reverses a standing disposition** in `MODULE_OWNERSHIP.md` and
therefore needs its own record. It changes no runtime behaviour and, by itself,
deletes nothing — the removal is a separate slice.

### The decisions

> **[DECISION AD-027 a]** `security/rate_limiter.py`'s disposition changes from
> **WIRE** to **DELETE**. `MODULE_OWNERSHIP.md`'s `rate_limiter.py` row is
> superseded on this point.

> **[DECISION AD-027 b]** **No runtime rate limiting is introduced anywhere.**
> Not in `pc_control`, not in `policy/`, not at any surface. Deletion is the
> resolution, not a step toward wiring.

> **[DECISION AD-027 c]** **`PolicyEngine` wiring is explicitly not part of this
> resolution.** No `PolicyEngine` class exists — `policy/` holds `RiskTables`
> plus the `classify_risk` / `sensitive_app_risk` functions. Nothing here
> creates one, and nothing here may be cited as authorising one.

> **[DECISION AD-027 d]** **AD-013's third state is resolved on the DELETE
> side** for this module. `rate_limiter.py` is present, unwired and undeleted —
> precisely the state AD-013 forbids. This decision picks the branch; it does
> not weaken the rule.

> **[DECISION AD-027 e]** **`MIGRATION_PLAN` row 4.14 ("Wire `rate_limiter` into
> `PolicyEngine`") is closed as obsolete**, and risk row **A-7** ("Requests that
> succeed today may be throttled") is **voided** — deletion throttles nothing.
> Row 4.14's acceptance test ("assert throttling engages at the configured
> threshold") is retired with it: there is no configured threshold, because the
> keys that would have carried one are gone.

> **[DECISION AD-027 f]** **Q-6 remains OPEN.** It covers `rate_limiter` **and**
> `injection_scanner`; only the rate-limiter half is answered here.
> `MODULE_OWNERSHIP.md` still records `injection_scanner.py` as **WIRE** into
> `policy/` ingress, "it has never run on anything". Nothing in this decision
> unblocks or prejudges that work.

> **[DECISION AD-027 g]** No production behaviour changes in this slice.
> Documentation only; the deletion is a separate, reviewed change.

### Rationale

**Zero production consumers.** `grep -rn "rate_limiter\|RateLimiter" src/`
returns only the module's own definition. `security/__init__.py` does not
re-export it. No startup, CLI, HTTP, voice, scheduler, skill or planner path
imports it. `CURRENT_ARCHITECTURE.md` §8 already records the consumer count as
**0**.

**The premise behind WIRE has expired.** `MODULE_OWNERSHIP.md` justified WIRE
with "`rate_limit_enabled = True` already ships". It does not.
`core/config.py:60-64` lists `security.rate_limit_enabled`,
`security.rate_limit_rpm` and `security.rate_limit_burst` in
`REMOVED_CONFIG_KEYS` ("never read; no request path consults the rate limiter"),
and a config still setting one gets a warning on load. Pinned by
`tests/security/test_network_defaults.py` and `tests/core/test_config.py`. The
operator-is-misled harm that motivated wiring no longer exists.

**GAP-19's key-level target is already met, by its other branch.** GAP-19's
target is "Every key wired **or deleted**. No third state." For `rate_limit_*`,
**deleted** was chosen and implemented. That is a statement about *config keys*.
What remained unresolved is the **module**, which is AD-013's question — a
different one, answered by AD-027 a. Keeping the two apart matters: neither
document requires the other's outcome.

**The Rust implementation is not a live dependency.**
`rust/crates/grandpa-security/src/rate_limiter.rs` is a complete parallel
implementation, exposed to Python as `RateLimiter` by
`rust/crates/grandpa-python/src/security.rs` and registered in that module's
`lib.rs`. It is not reached: `security/rate_limiter.py:70-79` wraps the bridge
import in `try/except Exception` and falls back to the Python token bucket on
any failure, and AD-002's evidence summary records that "All 16 call sites fall
back" — `link.exe` is absent on the developer's Windows machine and the
hatchling-built wheel cannot contain a cdylib.

**AD-002 is not assumed.** It remains *Needs ratification* and `rust/` is still
in tree with all 17 crates. This decision does not claim the Rust workspace has
been archived, does not depend on AD-002 being executed, and does not touch it.

### Scope

Documentation only. It authorises a later slice to delete
`src/grandpa/security/rate_limiter.py` and the two test surfaces that exist
solely to exercise it. No production code, test, database, schema or
configuration change accompanies this decision.

### Non-goals

Introducing rate limiting in any form; creating or wiring a `PolicyEngine`;
restoring the removed `rate_limit_*` config keys; closing Q-6; deciding the
disposition of `injection_scanner`; touching the Rust workspace or pre-empting
AD-002; changing `pc_control`'s gate order, approval semantics, emergency stop
or `ActionOrigin`.

### Consequences

- The product gains no throttling and loses none — nothing was throttled.
- `PyRateLimiter` remains exported from the Rust bridge with no Python consumer.
  That is an artefact of the Rust workspace, whose disposition is AD-002's
  question, not this one's.
- `tests/security/test_rate_limiter.py` (12 isolated unit tests) and
  `tests/core/test_rust_bridge.py::test_rate_limiter_uses_rust` are removed with
  the implementation. The second is named for a property it does not test: it
  asserts `check()` returns `True`, which the Python fallback satisfies
  identically, so it has never exercised the Rust path on this machine.
  Recorded here so its removal is not later mistaken for lost bridge coverage.
- `tests/security/test_network_defaults.py` and `tests/core/test_config.py` are
  **untouched** — they pin the config-key removal, not the module.
- Anyone later wanting rate limiting starts from Q-6, not from this module.

### Evidence

`security/rate_limiter.py:70-79` · `core/config.py:60-64, 75-78` ·
`CURRENT_ARCHITECTURE.md` §8 (security consumers, migration risk, dead-code
table) · `MODULE_OWNERSHIP.md` (`rate_limiter.py` and `injection_scanner.py`
rows) · `ARCHITECTURE_GAPS.md` GAP-19 · `MIGRATION_PLAN.md` rows 4.14 and A-7 ·
AD-002, AD-013, Q-6 · `rust/crates/grandpa-security/src/rate_limiter.rs`,
`rust/crates/grandpa-python/src/security.rs` ·
`tests/security/test_rate_limiter.py` · `tests/core/test_rust_bridge.py` ·
`tests/security/test_network_defaults.py` · `tests/core/test_config.py`

---

## AD-028 — The `pc_control ↔ desktop` cycle is mostly type location; that portion may be resolved independently of 4.11

Recorded from the read-only preflight for `MIGRATION_PLAN` row 4.15. This
decision changes no runtime behaviour and **authorises no code change**. It
records what the cycle is actually made of, because the plan's stated cause is
not what the code shows, and re-scopes the dependency accordingly.

> ### [CORRECTION — the measurement below was incomplete]
>
> **Everything from `### Evidence` to `### Evidence references` is preserved as
> written, including the parts this correction contradicts.** It is the record of
> a decision that was taken on a wrong number, and deleting it would hide that.
> Read the original text as history; read this block as the current position.
>
> **1. The 17-statement measurement was incomplete.** It was produced with a
> pattern matching `from grandpa.pc_control import …` and `import
> grandpa.pc_control`. It did **not** match the form `from grandpa import
> pc_control`, which `desktop/kernel/` uses throughout.
>
> **2. The complete measurement is 41 `desktop → pc_control` import
> statements** — not 17.
>
> | Import form | Statements |
> |---|---|
> | `from grandpa.pc_control import …` | 17 |
> | `from grandpa import pc_control` | **24** |
> | **Total** | **41** |
>
> **3. The 24 are concentrated in `desktop/kernel/`**: `approvals.py` (8),
> `audits.py` (5), `execution.py` (4), `emergency.py` (3), `risk.py` (3),
> `requests.py` (1).
>
> **4. Those 24 reach into substantive `pc_control` policy and execution
> internals**, not types: `_classify_risk_impl`, `_launch_needs_approval`,
> `_normalise_action_type`, `APPROVAL_REQUIRED_ACTIONS`, `BLOCKED_ACTIONS`,
> `LOW_RISK_ACTIONS`, `MEDIUM_RISK_ACTIONS`, `HIGH_RISK_ACTIONS`,
> `_create_pending`, `_approve_local_action_impl`, `_reject_local_action_impl`,
> `_list_pending_actions_impl`, `_list_approval_records_impl`,
> `_approval_message`, `_EMERGENCY_STOP_ACTIVE`, `_emergency_stop_impl`,
> `_reset_emergency_stop_impl`, `_preflight_guard`, `_run_local_action_impl`,
> `_coerce_request`, `_execute`, `_audit`, and the audit/retention helpers.
>
> **5. `MIGRATION_PLAN`'s original explanation is therefore supported by the
> complete evidence.** "The cycle exists *because* `pc_control` holds policy" is
> what 24 of the 41 statements show: `desktop/kernel/` is a facade over
> `pc_control`'s risk classifier, policy tables, approval lifecycle and
> emergency-stop state.
>
> **6. This decision's characterisation of the cycle as "mostly type location"
> was incorrect** — including in this decision's own title and index row — and
> **must no longer be treated as a current architectural fact.**
>
> **7. The projected "17 statements to 3" reduction is incorrect** as a statement
> about the complete graph. Repointing the 14 pure type-import statements would
> take the complete graph from **41 to 27**: 14 statements removed, the mixed
> `desktop/control/applications.py` statement reduced to `_is_protected_path`
> alone, and the 2 `run_local_action` plus all 24 `from grandpa import
> pc_control` statements untouched.
>
> **8. The type relocation itself remains valid.** `LocalActionRequest` and
> `LocalActionResponse` are canonical in `policy/models.py`, `pc_control`
> re-exports them, and the relocated definitions are byte-identical to the
> originals. Nothing about that is affected by the miscount, and none of it is
> reversed by this correction.
>
> **9. Repointing the 14 pure type imports remains a possible follow-up**
> dependency reduction. It does **not** establish that the overall cycle is
> independent of row 4.11.
>
> **10. The remaining `desktop/kernel/` policy and execution dependencies stay
> governed by row 4.15's original architectural objective and its dependency
> reasoning**, which this correction restores rather than replaces.
>
> **11. Nothing here claims 4.11 is unnecessary** for the remaining
> behavioural and policy edges. The evidence points the other way, and in any
> case that question is not settled by this decision.
>
> **12. GAP-10 and `MIGRATION_PLAN` row 4.15 remain OPEN.**
>
> **Terminology used above, precisely:** *41* is import statements in the
> complete `desktop → pc_control` measurement. *18* is imported symbols within
> the `from grandpa.pc_control import …` subset of 17 statements. *15* is the
> type symbols among those 18. The 15 type symbols are **not** 15 of 41, and
> they are **not** 15 of 17 statements.
>
> **What survives of this decision:** AD-028 a and b — the relocation was
> authorised and has shipped. **What does not:** the claim that the cycle is
> mostly type location, and anything derived from it, including the re-scoping
> of row 4.15's dependency on 4.11, which `MIGRATION_PLAN` has been restored to
> state without that qualification.


### Evidence

**[FACT] The back-edge is 17 import statements carrying 18 symbol imports.**
Measured across `src/grandpa/desktop/`:

| Symbol imported from `pc_control` | Occurrences | Kind |
|---|---|---|
| `LocalActionResponse` | 14 | type |
| `LocalActionRequest` | 1 | type |
| `run_local_action` | 2 | behavioural |
| `_is_protected_path` | 1 | behavioural, **private** |

**[CORRECTED — see the correction block above.]** The paragraph that follows is
accurate about the 17-statement subset it measured, and wrong as a description of
the cycle, which is 41 statements.

**15 of the 18 symbols are the two dataclasses.** Counted by *statement* rather
than symbol: **14** statements import only types, **2** import only
`run_local_action`, and **1** is mixed
(`desktop/control/applications.py:57` imports `LocalActionResponse` and
`_is_protected_path` together). Relocating the types would therefore remove 14
statements outright and reduce the mixed one to a single behavioural symbol; it
would not touch the other 2.

**[FACT] Both types are defined in `pc_control`.** `LocalActionRequest` at
`pc_control.py:234`, `LocalActionResponse` at `:261`.

**[FACT] Every back-edge is a function-local import.** All 17 appear inside
function bodies, not at module scope. The cycle is a static package-graph cycle,
not a runtime import failure — nothing is currently broken by it.

**[FACT] Policy is already partially delegated out of `pc_control`.** It imports
from `grandpa.policy` in five places and calls `policy.engine`'s `classify_risk`
and `sensitive_app_risk` rather than defining them. What it still *owns* are
three tables: `BLOCKED_ACTIONS` (`:134`), `APPROVAL_REQUIRED_ACTIONS` (`:154`)
and `SENSITIVE_APP_RISK` (`:873`).

**[FACT] `policy/models.py` is an available canonical home.** It already holds
`ActionOrigin`, `DEFAULT_ACTION_ORIGIN`, `CanonicalTarget`, `PolicyRequest` and
`PolicyDecision`, and imports nothing from `pc_control`.

**[FACT] The re-export pattern is already established in `pc_control` itself**,
for the same reason, by the same D-5 work. `pc_control.py:215-222` records it
for `ActionOrigin`: "Re-exported, not defined. `grandpa.policy.models` is the
canonical home … These names stay importable from `pc_control` because callers
and tests already bind to them here, and breaking that would be a change to a
public surface for no benefit."

**[FACT] Existing bindings are broad.** 141 test references name
`LocalActionRequest`/`LocalActionResponse`, at least ten importing them directly
from `grandpa.pc_control`.

**[PLAN — and contradicted]** `MIGRATION_PLAN` states twice, at the 4.15 row's
dependency bullet and in the dependency table, that "the cycle exists *because*
`pc_control` holds policy". On the measured evidence that explanation accounts
for at most the 3 behavioural symbols, not the 15 type symbols.

### The decisions

> **[DECISION AD-028 a]** The **type-location portion** of GAP-10's
> `pc_control ↔ desktop` cycle **may proceed independently of row 4.11**.
> `LocalActionRequest` and `LocalActionResponse` may be relocated to the
> canonical policy model layer.

> **[DECISION AD-028 b]** If relocated, `pc_control` **must re-export both
> names**, following the `ActionOrigin` precedent at `pc_control.py:215-222`.
> They are a public surface: 141 test references and at least ten direct imports
> bind to them there, and breaking that would be a change to a public surface
> for no benefit.

> **[DECISION AD-028 c]** **This decision does not authorise the relocation
> itself.** No file is moved, edited or created under it. Implementation is a
> separate, scoped and reviewed slice.

> **[DECISION AD-028 d]** **The remaining behavioural back-edges are out of
> scope.** `run_local_action` (2) and `_is_protected_path` (1) are not
> authorised to change. They are dependencies on execution and on a private
> helper, and they need their own design work.

> **[DECISION AD-028 e]** **`_is_protected_path` is not authorised to be
> relocated, exported, or made public** by this decision.

> **[DECISION AD-028 f]** **No architectural change to `run_local_action`** is
> authorised — not its signature, its callers, or its position as the single
> mandatory enforcement boundary.

> **[DECISION AD-028 g]** **This does not complete GAP-10 or row 4.15.**
> Relocating the types would leave 3 back-edges and a live cycle. Row 4.15 stays
> **OPEN**, and no work under this decision may be described as closing it.

> **[DECISION AD-028 h]** **Row 4.11 stays OPEN and unchanged.** There is still
> no `PolicyEngine` class and no `policy/store.py`. This decision does **not**
> claim 4.11 is unnecessary for the remaining behavioural edges — whether those
> edges require it is a separate question that the repository evidence gathered
> here does not answer.

> **[DECISION AD-028 i]** **Row 4.15's stated dependency on 4.11 is re-scoped,
> not deleted.** The plan's explanation is corrected so it no longer implies the
> whole cycle is caused by policy ownership. The dependency continues to apply
> to whatever portion of 4.15 genuinely turns on policy ownership.

> **[DECISION AD-028 j]** No production behaviour changes in this slice.
> Documentation only.

### Terminology

GAP-10 and row 4.15 concern the **import cycle**. Row 4.11 concerns
**`PolicyEngine` and policy ownership**. They are distinct, and this decision
separates them only for the 15 type symbols where the evidence supports the
separation. It asserts nothing about the other three.

### Scope

Documentation only. It authorises a later slice to relocate two dataclasses with
a compatibility re-export. No production code, test, database, schema,
configuration or Rust change accompanies it.

### Non-goals

Relocating or exporting `_is_protected_path`; changing `run_local_action`;
closing GAP-10 or row 4.15; completing, re-scoping or bypassing row 4.11;
creating `policy/store.py` or a `PolicyEngine` class; moving any of
`BLOCKED_ACTIONS`, `APPROVAL_REQUIRED_ACTIONS` or `SENSITIVE_APP_RISK`; changing
approval flow, emergency stop, `ActionOrigin` semantics, risk classification or
gate ordering.

### Consequences

- ~~If the relocation slice runs, the back-edge falls from 17 statements to 3, and
  the cycle persists — smaller, and reduced to edges that are genuinely about
  execution rather than about where a dataclass lives.~~
  **[CORRECTED]** The complete graph is 41 statements; repointing the 14 pure
  type imports would take it to **27**, not 3.
- Row 4.15 gains no acceptance test from this. It still has none of its own; the
  cycle assertion belongs to row 4.16.
- The 141 existing test references remain valid unchanged, which is what makes
  the relocation low-risk and also what makes the re-export mandatory.
- Anyone reading the plan's 4.15 dependency will now find it qualified rather
  than absolute.

### Evidence references

`src/grandpa/desktop/` (17 back-edge statements: `automation.py:401`,
`control/applications.py:57,222,260`, `control/automation.py:64`,
`control/clipboard.py:23`, `control/diagnostics.py:22`, `control/files.py:18`,
`control/monitors.py:17`, `control/power.py:16,45,88,126,170`,
`control/windows.py:16,24`, `operator.py:368`) ·
`pc_control.py:134, 154, 215-222, 234, 261, 873` · `policy/models.py` ·
`MIGRATION_PLAN.md` row 4.15, its dependency bullet and dependency table ·
`ARCHITECTURE_GAPS.md` GAP-10 · AD-006, AD-013

### Addendum AD-028.1 — `desktop/control → policy.models` is an authorised dependency

Recorded from the allowlist decision preflight that followed AD-028's relocation
slice. **Everything above — the original decision, its Evidence, and the
correction block — stands unchanged.** This addendum supplies one decision the
original did not make, and it is an authorisation, **not** an implementation.

**Why it exists.** The AD-028 relocation shipped, and the follow-up slice that
would repoint `desktop/control/`'s type imports failed two governance tests:
`tests/test_policy_models.py` and `tests/test_policy_resolver.py`, both
`TestNothingElseChanged::test_only_the_intended_modules_import_the_new_package`.
That gate pins the exact set of modules permitted to import `grandpa.policy` —
`composition/files.py`, `dispatch/context.py`, `files/executor.py`,
`pc_control.py` — and states its purpose plainly: "The list is pinned rather
than removed, so each new dependant is a decision rather than a discovery." The
repoint was reverted, and the decision the gate exists to force is made here.

#### Evidence

**[FACT] The intended layering is stated in the repository.**
`policy/boundary.py`: "A capability package must not import the execution
module. The layering is `entry surfaces -> dispatch -> policy -> capability
packages -> core`, and `pc_control` sits on the wrong side of that line for
`files/` to depend on it." The governance test's own docstring gives the same
rule as the reason `files/executor.py` was admitted: "a capability package may
depend on `policy`, and must not depend on the execution module."

**[FACT] `desktop/control/` is the canonical typed Windows capability/actuator
layer.** `CURRENT_ARCHITECTURE.md` names it the canonical candidate — "9 typed
services: applications, windows, files, power, clipboard, monitors, automation,
registry, diagnostics" — and its layer diagram places those modules in the
`ACTUATION — Windows` band, below the policy and approval band.
`MODULE_OWNERSHIP.md` records "`desktop/control/*` **KEEP** — the typed service
layer is correct; only its callers change." Each module declares a service
identity and returns responses; none classifies risk or stages approval.

**[FACT] These modules currently take the forbidden direction.** All eight
import `pc_control` — the execution module — solely to name a response type.
That is the condition the boundary protocol describes as wrong-side-of-the-line,
and repointing to `policy.models` moves them onto the sanctioned one.

**[FACT] The reverse direction stays clean.** `policy/models.py` imports only
`__future__`, `dataclasses` and `typing`. The sibling assertions that "policy
imports nothing back" are unaffected.

**[FACT] Nothing behavioural depends on the import path.** `pc_control` binds
the same class objects from `policy.models` rather than redefining them, so
`grandpa.pc_control.LocalActionResponse` **is**
`grandpa.policy.models.LocalActionResponse`. When the repoint was applied and
then reverted, 937 tests passed and the only two failures were the allowlist
gate itself; no behavioural test failed.

#### The decisions

> **[DECISION AD-028.1 a]** Direct `desktop/control -> grandpa.policy.models`
> is an **allowed dependency direction**, on the layering rule stated in
> `policy/boundary.py`: capability packages may depend on `policy` and must not
> depend on the execution module.

> **[DECISION AD-028.1 b]** **Exactly these eight modules are authorised**, and
> no others:
>
>     src/grandpa/desktop/control/applications.py
>     src/grandpa/desktop/control/automation.py
>     src/grandpa/desktop/control/clipboard.py
>     src/grandpa/desktop/control/diagnostics.py
>     src/grandpa/desktop/control/files.py
>     src/grandpa/desktop/control/monitors.py
>     src/grandpa/desktop/control/power.py
>     src/grandpa/desktop/control/windows.py
>
> `desktop/control/*` is **not** authorised wholesale: `__init__.py`,
> `registry.py` and `verification.py` are excluded because they do not need the
> dependency.

> **[DECISION AD-028.1 c]** The authorised symbols are **`LocalActionResponse`
> (13 occurrences) and `LocalActionRequest` (1, `windows.py:16`)** — 14 import
> statements. Nothing else may be imported from `policy` by these modules under
> this decision.

> **[DECISION AD-028.1 d]** The **mixed statement at
> `desktop/control/applications.py:57`** — `LocalActionResponse` together with
> `_is_protected_path` — is **outside this decision**. `_is_protected_path` is a
> private helper of the execution module and its disposition is untouched here.

> **[DECISION AD-028.1 e]** **No `desktop/kernel/` dependency change is
> authorised.** The 24 `from grandpa import pc_control` statements in
> `desktop/kernel/{approvals,audits,emergency,execution,requests,risk}.py`
> remain exactly as they are.

> **[DECISION AD-028.1 f]** **AD-028's relocation remains valid.**
> `LocalActionRequest` and `LocalActionResponse` stay canonical in
> `policy/models.py` with `pc_control` re-exporting both.

> **[DECISION AD-028.1 g]** **AD-028 did not authorise this.** Its decisions
> authorised the mechanical relocation and required the re-export; neither
> addressed `desktop/control/` becoming a direct `grandpa.policy` dependant.
> This addendum supplies that missing architectural decision.

> **[DECISION AD-028.1 h]** **This is not a cycle break.** The expected
> reduction is `desktop -> pc_control` **41 -> 27** import statements. The
> `pc_control <-> desktop` cycle survives in full: risk, approval,
> emergency-stop, audit, request-coercion and execution all still round-trip
> through `desktop/kernel/`.

> **[DECISION AD-028.1 i]** **The real cycle still requires the architectural
> work governed by rows 4.11 and 4.15.** `MIGRATION_PLAN` row 4.15 **remains
> OPEN and remains dependent on 4.11**; nothing here re-scopes it.

> **[DECISION AD-028.1 j]** The implementation slice this authorises must
> **update both governance allowlists** (`tests/test_policy_models.py` and
> `tests/test_policy_resolver.py`, which carry the same importer list under
> different docstrings and different second assertions) and **repoint only the
> 14 authorised type imports**.

> **[DECISION AD-028.1 k]** **The decision changes no behaviour.** No runtime
> behaviour, approval semantics, emergency-stop semantics, risk classification,
> `ActionOrigin` semantics or public API behaviour is altered by it.

> **[DECISION AD-028.1 l]** **This is an authorisation, not an
> implementation.** No production file, test or import is changed by this
> addendum.

#### Scope

Documentation only. It authorises a later slice to repoint 14 import statements
and extend two test allowlists from four entries to twelve. No production code,
test, database, schema, configuration or Rust change accompanies it.

### Addendum AD-028.2 — `desktop/kernel/risk.py → policy.engine` is an authorised dependency

Recorded from the read-only preflight for the dependency the §4.11
approval-predicate extraction introduced. **AD-028 and AD-028.1 above stand
unchanged**, including AD-028's correction block and every one of AD-028.1's
decisions a-l. This addendum ratifies one import edge and clarifies the reach of
one sentence in AD-028.1 e. It authorises no code change: the implementation it
ratifies is already complete and is not reopened here.

**Why it exists.** The §4.11 approval-predicate slice extracted the four-clause
approval rule into `policy.engine.requires_approval` and repointed
`desktop/kernel/risk.py`'s view at it. That made `risk.py` the thirteenth entry
on the policy-importer allowlist and the first from `desktop/kernel/`, so the
gate whose stated purpose is to make each new dependant "a decision rather than
a discovery" did exactly that. The decision it forces is made here.

#### Evidence

**[FACT] The target layer table already permits it.** `TARGET_ARCHITECTURE.md`
§5.8 gives the capability layer as `desktop/`, `automation/`, `screen/`,
`vision/`, `browser/`, `voice/`, `files/` and the rest, with "May import:
**policy, core**". That permission names the whole `desktop/` package. It
carries no clause excluding `desktop/kernel/`, and none restricting which part
of `policy` may be imported. `policy/boundary.py` states the same rule from the
other side: the prohibition is on a package importing the **execution module**,
not on it importing `policy`.

**[FACT] `MODULE_OWNERSHIP.md` already assigns this responsibility to
`policy/`.** Its ownership table gives "Action policy + approval" the canonical
owner `policy/` **(new)**, and names its current scattered homes as
`local_actions.classify_permission` and **`desktop/kernel/risk.py`**. Pointing
`risk.py` at `policy` moves a named responsibility toward its named owner
rather than leaking one outward.

**[FACT] `requires_approval` is a view, and has no production caller.** A
search across `src/` finds the definition and no call site; every other
occurrence of the name is an unrelated status-vocabulary string literal. Its
consumers are `tests/test_pc_control_kernel.py`, which pins the kernel facades
under the contract that they *preserve behavior*, and
`tests/test_action_origin_invariant.py`, which uses it to assert the skill path
cannot skip an approval gate.

**[FACT] The live gate is untouched and still computes the condition itself.**
`pc_control._run_local_action_impl` reads `APPROVAL_REQUIRED_ACTIONS` and calls
`_launch_needs_approval` inline, as before.
`tests/test_kernel_approval_facade.py` holds both halves of that: one test reads
the gate's source to prove it was not relocated, another neuters the view to
`False` and asserts `regedit` and `terminal` are still staged.

**[FACT] The direction stays clean, measured.** `policy -> pc_control` is 0 and
`policy -> desktop` is 0; `policy/engine.py` imports exactly `__future__`,
`collections.abc`, `dataclasses` and `grandpa.policy.models`, pinned by test.
`desktop -> pc_control` is **27** statements, unchanged by the extraction --
`risk.py` still imports `pc_control` for the risk tables, and what narrowed is
the symbol surface it reaches for, from `_normalise_action_type`,
`APPROVAL_REQUIRED_ACTIONS` and `_launch_needs_approval` down to
`_risk_tables` alone.

**[FACT] The dependency is inert at runtime.** The predicate reads no file,
opens no database and actuates nothing;
`tests/test_policy_boundary.py::test_policy_holds_no_execution_state_or_approval_store`
forbids `sqlite3`, `subprocess`, `shutil`, `compare_digest`,
`_mark_pending_decision` and `EMERGENCY_STOP` anywhere in `policy/`.

#### The decisions

> **[DECISION AD-028.2 a]** Direct `desktop/kernel/risk.py ->
> grandpa.policy.engine` is an **allowed dependency**, and the allowlist entry
> for `src/grandpa/desktop/kernel/risk.py` is **formally authorised by this
> addendum**.

> **[DECISION AD-028.2 b]** It **follows the intended layering**, `entry
> surfaces -> dispatch -> policy -> capability packages -> core`, and the
> target architecture's rule that `desktop/` may import `policy`. Policy
> ownership sits above execution and capability implementation, and this points
> that way.

> **[DECISION AD-028.2 c]** **`desktop/kernel/` is an execution-side delegation
> facade today**, and `MODULE_OWNERSHIP.md` plans its rename to
> `desktop/execution/`. **That rename does not invalidate this dependency.**
> Policy ownership remains above execution, so an execution layer naming the
> policy rule it reports on is the sanctioned direction; the alternative --
> holding a second copy of the rule -- is what this replaces.

> **[DECISION AD-028.2 d]** **`risk.py::requires_approval` is a policy view and
> compatibility function only.** It reports what the boundary would decide. It
> is **not** the live enforcement boundary and must not become one.

> **[DECISION AD-028.2 e]** **The live enforcement gate remains
> `pc_control._run_local_action_impl`**, unchanged and unrelocated. It is still
> the single mandatory enforcement boundary for desktop actuation.

> **[DECISION AD-028.2 f]** The dependency creates **no `policy -> desktop`
> edge, no `policy -> pc_control` edge, no new cycle, no actuation dependency
> and no approval-store dependency.** It does not increase `desktop ->
> pc_control`, which stays at 27 statements.

> **[DECISION AD-028.2 g]** **AD-028.1 e is clarified, not overruled.** Its
> prohibition concerned **changing the existing `desktop/kernel -> pc_control`
> dependency set** within that slice -- the 24 `from grandpa import pc_control`
> statements, which remain exactly as they were and are not touched here. It
> did **not** prohibit **adding** the separately authorised `desktop/kernel/
> risk.py -> policy.engine` dependency that the later approval-predicate
> extraction requires. Read AD-028.1 e as scoped to AD-028.1's own slice and to
> the `pc_control` edge it names.

> **[DECISION AD-028.2 h]** **This does not authorise wholesale
> `desktop/kernel/ -> policy` imports.** Exactly one module and one symbol are
> authorised: `risk.py` importing `requires_approval`. `approvals.py`,
> `audits.py`, `emergency.py`, `execution.py` and `requests.py` are **not**
> authorised, and any further policy dependency from `desktop/kernel/` needs
> its own architectural justification and its own record.

> **[DECISION AD-028.2 i]** **This unblocks neither §4.11 nor §4.15.** It
> ratifies one dependency edge. Row 4.11 stays **OPEN** -- there is still no
> `PolicyEngine` class and no `policy/store.py`, the two funnels are still
> unmerged, and the two approval stores are still separate. Row 4.15 stays
> **OPEN** and stays dependent on 4.11.

> **[DECISION AD-028.2 j]** **The existing implementation is complete and is
> not changed by this addendum.** No production Python, no test behaviour, no
> risk table, no approval semantics, no `ActionOrigin` semantics, no
> emergency-stop behaviour and no public API is altered.

> **[DECISION AD-028.2 k]** **The allowlist is not weakened.** It stays pinned
> and exact at thirteen entries; the importer is not removed and no other
> importer is added.

#### What this does not settle

- **Whether the view should exist at all.** `requires_approval` has no
  production caller, so this dependency exists entirely to serve a function
  only tests call. Deleting it instead is a coherent alternative that would
  remove the edge outright -- and would also remove the instrument
  `test_action_origin_invariant.py` uses to assert the skill path is gated.
  That is a separate decision and is neither taken nor foreclosed here.
- ~~**The name of `test_no_second_execution_or_approval_implementation_exists`.**
  Its enforced list is about stores, crypto and mutable state, none of which the
  predicate has, and it passes. Its *name* now reads as though it forbids what
  was added. Worth an amendment; not one this addendum makes.~~ **Done in a
  later governance-cleanup slice:** renamed to
  `test_policy_holds_no_execution_state_or_approval_store`, with the forbidden
  token set and the assertion unchanged. Recorded rather than deleted, because
  the reasoning for the rename is this bullet.

#### Scope

Documentation and governance only. It ratifies an allowlist entry that already
exists and updates the rationale that points at it. No production code, test
behaviour, database, schema, configuration or Rust change accompanies it.

## AD-029 — An approval that gates execution requires an out-of-band credential

Recorded from the §4.13 approval-store ownership preflight. It settles one
question of the six that preflight raised -- whether a credential-free approval
path is an acceptable canonical contract -- and deliberately settles nothing
else. No production code, test, endpoint or database changes under it.

**Why this one first.** Three live approval stores were characterised
independently. Two of them gate execution behind a code the stager cannot see;
the third gates nothing behind anything. Whether that third arrangement is
acceptable is a precondition for every remaining §4.13 question: whether a
store may stay separate depends on what a separate store must still guarantee.
Deciding it first keeps the store-ownership question open rather than
prejudging it.

### Evidence

**[FACT] Two of the three stores already require an out-of-band code.**
`local_action_approvals.authorize_approval` verifies a bound token under a
five-attempt cap; `pc_control._approve_local_action_impl` verifies a token with
`secrets.compare_digest` before it checks anything else. Both deliver the code
to the operator console rather than through the response that staged the
action. `server/routes.py` states the reason in the route's own docstring: "The
code is deliberately not obtainable over HTTP: it appears in no pending
listing, no response and no user-visible field, so the caller that stages an
action cannot be the caller that approves it."

**[FACT] The third store has no credential at all.**
`tools/approval_store.py` has no token column, no digest column, no attempt
counter, and no verification method. `update_status` is an unconditional
`UPDATE ... WHERE id = ?`. `POST /v1/approvals/{action_id}/approve`
(`server/approval_routes.py:57-66`) sets `STATUS_APPROVED` from an action id
alone.

**[FACT] That state is consumed as an execution gate.**
`agent/runtime.py:1068` refuses to apply a patch unless
`proposal.approval_status == "approved"`, and that string is derived from the
store-3 row by the status map at `agent/execution/approval.py:93-96`. So the
credential-free endpoint sets one of the conditions a real execution path
reads. This corrects a narrower earlier reading -- that the store's `approved`
state authorised nothing. It authorises nothing *by itself*; it is an input to
something that does.

**[FACT] The exposure is bounded by gates that are not this decision's
subject.** `apply_patch` is reachable only from `grandpa agent patch apply`
(`cli/agent_run_cmd.py:240`) and never over HTTP, and it additionally requires
`resolve_and_verify_workspace` to pass and `is_proposal_fresh` to hold -- every
affected file's hash unchanged since the proposal was written. An HTTP approve
applies nothing on its own. What it removes is the human decision, not the
whole guard.

**[FACT] `MIGRATION_PLAN` §4.13 already assumes this contract.** Its row reads
"One approval store, out-of-band code", and its required test is "assert an
action staged over channel A cannot be approved without the out-of-band code".
The plan states the requirement; no decision record had yet said that a path
lacking it is non-conforming.

**[FACT] There is no `ProactiveAgent`.** The class named in
`server/approval_routes.py:24` and `tools/approval_store.py:366` does not exist
in the repository, and `get_seen_ids`, documented as its consumer, has none.
The only production caller of `queue_action` is
`agent/execution/approval.py`. No conclusion about proactive actions is
therefore available from the code, and none is drawn here.

### The decisions

> **[DECISION AD-029 a]** **Every approval path that gates execution requires a
> server-generated out-of-band approval credential.** The credential must not
> be obtainable through the surface that staged the action -- not in its
> response, not in a pending listing, and not in any user-visible field -- so
> that the caller who stages an action cannot be the caller who approves it.

> **[DECISION AD-029 b]** **A credential-free approval endpoint is not an
> accepted canonical security contract.** `POST /v1/approvals/{id}/approve` is
> recorded as **non-conforming** to the contract this decision states.
> Non-conforming is a status, not an instruction to change it today.

> **[DECISION AD-029 c]** **This applies to Store 3 and `/v1/approvals/*` as a
> future migration requirement.** Any slice that brings that path under the
> unified approval model must add the credential. This decision does **not**
> choose that path's final store ownership.

> **[DECISION AD-029 d]** **No Store-3 behaviour changes in this slice.** No
> credential is implemented, no endpoint is altered, no schema is migrated, no
> row is touched, and no database is written.

> **[DECISION AD-029 e]** **Patch application's existing additional gates are
> unchanged and are not superseded.** CLI-only invocation, workspace
> verification and proposal/file freshness stay exactly as they are. This
> decision adds a requirement to the approval step; it removes nothing from the
> apply step.

> **[DECISION AD-029 f]** **Whether Store 3 belongs inside the eventual unified
> approval store is NOT decided here.** Merge, remain separate, partial
> migration and retirement all stay open. What is decided is only that
> whichever option is chosen, an execution-gating approval within it carries a
> credential.

> **[DECISION AD-029 g]** **No conclusion is drawn about proactive actions**,
> because no `ProactiveAgent` implementation exists. Nothing here may be cited
> as authorising one, and the absent class must not be invented to satisfy this
> decision.

> **[DECISION AD-029 h]** **Nothing else about the approval contract is
> decided.** TTL values, the action-binding mechanism, the failed-attempt cap,
> provenance persistence and execution-state tracking all remain open; the
> preflight marked each of them OPEN DECISION and this record does not narrow
> them.

> **[DECISION AD-029 i]** Documentation only. No production behaviour changes.

### Relationship to existing decisions

- **AD-013 (wire it or delete it; no third state)** is untouched. This decision
  states a contract; it does not dispose of any module, and the dead
  remembered-permission subsystem inside `tools/approval_store.py` keeps its
  open disposition question.
- **AD-022 (P1 is a policy-layer invariant)** is complemented, not amended.
  AD-022 governs classification before execution; this governs the credential on
  the approval step that classification may demand.
- **AD-023 (Funnel-A provenance)** is unaffected. Provenance persistence stays
  open per decision h.
- **AD-028 and its addenda** are unaffected; they concern dependency direction,
  not approval semantics.

### Scope

Documentation only. It records a security contract and marks one existing
endpoint non-conforming. No production code, test, endpoint, schema,
configuration, database or Rust change accompanies it.

### Non-goals

Implementing a credential anywhere; changing `/v1/approvals/*`; choosing Store
3's ownership; merging, migrating or retiring any store; deciding TTL, action
binding, attempt caps, provenance or execution-state semantics; disposing of the
remembered-permission subsystem; correcting §4.13's two-store count; creating
`policy/store.py` or a `PolicyEngine`.

### Consequences

- §4.13 gains a stated contract its acceptance test can be written against.
- One endpoint is now recorded as non-conforming, so its status is a known
  position rather than an undiscovered gap.
- The store-ownership question (D-1) can now be asked without the answer
  implying a security level, because the security floor is fixed independently.
- A future slice that adds the credential to `/v1/approvals/*` is a behaviour
  change to a live endpoint and will need its own scoped, reviewed slice.

### Evidence references

`local_action_approvals.py` (`authorize_approval`, `verify_approval_token`,
`MAX_APPROVAL_ATTEMPTS`) · `pc_control.py:380-410` ·
`tools/approval_store.py:263-283` · `server/approval_routes.py:57-77` ·
`server/routes.py:1330-1360` · `agent/runtime.py:1068` ·
`agent/execution/approval.py:93-96, 175-181` · `cli/agent_run_cmd.py:240` ·
`MIGRATION_PLAN.md` §4.13 and its test row · `ARCHITECTURE_GAPS.md` GAP-03 ·
`tests/test_approval_store_characterization.py` ·
`tests/test_local_action_approval_tokens.py` ·
`tests/test_approval_identity_binding.py` · AD-013, AD-022, AD-023

## AD-030 — Store 3 is one approval domain: patch proposals. There is no proactive-action domain

Recorded from the D-3 approval-domain preflight. It corrects a premise that
every remaining §4.13 question was being asked against, and it decides nothing
about disposition. AD-029 deliberately withheld this conclusion -- its decision
g says "no conclusion is drawn about proactive actions, because no
``ProactiveAgent`` implementation exists" -- and the audit that followed
supplies the evidence to state it positively. This is that statement, and
nothing more.

**Why it is worth a record.** `tools/approval_store.py`, its routes and its
schema are named and documented for a second approval domain. Reading the
module, the two `ProactiveAgent` comments, the generic `permission_key` format
in its header and the four-tier vocabulary, a reasonable person concludes the
store serves two kinds of thing. It does not. Every question about store
ownership asked against that premise would be asked against a fiction.

### Evidence

**[FACT] One producer.** `agent/execution/approval.py:40` is the sole
production caller of `queue_action`. No other module in `src/` creates a
Store-3 row.

**[FACT] One `action_type`.** `"patch_proposal"`, written at
`agent/execution/approval.py:41`. No other value is produced anywhere in
production.

**[FACT] One `permission_key` form.** `f"patch_proposal:{proposal.proposal_id}"`
at `agent/execution/approval.py:44`. The generic
`"{action_type}:{fingerprint}"` shape documented in
`tools/approval_store.py:6-8` -- `"email_delete:domain:..."`,
`"sms_draft_reply:contact:..."` -- appears **only** in that docstring and in
test data. No production code writes it.

**[FACT] One consumer chain, and it is the patch path.**
`agent/runtime.py:1068` refuses to apply a patch unless
`proposal.approval_status == "approved"`, derived from the Store-3 row by the
status map at `agent/execution/approval.py:93-96`. `grandpa agent patch apply`
(`cli/agent_run_cmd.py:240`) is the execution entry point, and it additionally
requires `resolve_and_verify_workspace` to pass and `is_proposal_fresh` to hold
-- gates this decision leaves exactly as they are.

**[FACT] `ProactiveAgent` does not exist.** No class of that name is defined in
`src/` or `tests/`. Its two occurrences are comments:
`server/approval_routes.py:24` and `tools/approval_store.py:366`.

**[FACT] The supporting machinery for a second domain has no consumers.**
`get_seen_ids` -- documented as `ProactiveAgent`'s -- has zero production
callers. The permission-memory subsystem (`get_permission`, `set_permission`,
`clear_permission`, `list_permissions`, `PermissionRule`, `DECISION_ALWAYS_*`,
the `permission_memory` table) has zero production and zero test consumers, and
the table is never read or written by any ordinary store operation. The tier
vocabulary has no executable production semantics: `TIER_MEDIUM` is written as
a constant and never read, and `TIER_TRIVIAL`, `TIER_LOW` and `TIER_HIGH` are
named nowhere in production.

**[FACT] The generic HTTP surface acts on the patch domain.**
`/v1/approvals/{id}/approve` is generic *by shape* -- it takes any row id --
but the only rows that exist are patch proposals. So the endpoint AD-029
recorded as non-conforming is an uncredentialed approval surface over **code
patch application**, not over a hypothetical proactive action. That is a
sharper statement of the same exposure, not a new one.

### The decisions

> **[DECISION AD-030 a]** **Store 3's currently implemented approval domain is
> patch-proposal approval.** That is the only domain the executable code
> supports.

> **[DECISION AD-030 b]** **No executable proactive-action approval domain
> exists** in this repository. The claim "Store 3 contains both patch approvals
> and proactive actions" is **not justified by executable code** and must not be
> repeated as an architectural fact.

> **[DECISION AD-030 c]** **`ProactiveAgent` is not an implemented repository
> component.** It must not be cited as one, and it must not be invented in
> order to satisfy any decision, test, document or migration step.

> **[DECISION AD-030 d]** **Generic naming is not evidence of a second live
> domain.** The store's generic `action_type` and `permission_key` fields, its
> four-tier vocabulary, the `permission_memory` table, `get_seen_ids`, and the
> generic shape of `/v1/approvals/*` describe an anticipated design, not a
> running one. Schema and API generality must not be read as a second domain.

> **[DECISION AD-030 e]** **This is a scope and premise clarification only.**
> It settles what Store 3 *is*; it settles nothing about what should happen to
> it.

> **[DECISION AD-030 f]** **D-1, D-4 and D-5 remain open**, and all four
> dispositions stay available for a single-domain store:
>
> - **D-1** -- whether Store 3 is merged into the canonical approval domain,
>   remains separate, is partially retired, or is deleted. **Not decided.**
> - **D-4** -- the disposition of the dead permission-memory subsystem, the
>   tier vocabulary and `get_seen_ids`. **Not decided.**
> - **D-5** -- canonical TTL, action binding, failed-attempt cap, provenance and
>   execution-state semantics. **Not decided.**

> **[DECISION AD-030 g]** **AD-029 continues to apply in full.** Any approval
> path that gates execution requires a server-generated out-of-band credential,
> and `/v1/approvals/{id}/approve` remains recorded as non-conforming. This
> decision narrows what that endpoint approves; it does not soften the
> requirement or authorise a change to it.

> **[DECISION AD-030 h]** **No runtime behaviour changes.** No production code,
> test, endpoint, schema, database, constant, comment or docstring is created,
> altered, renamed or deleted under this decision -- including the two stale
> `ProactiveAgent` comments and every dead API named in the evidence above.
> Correcting them is D-4's business or a separate documentation slice.

### Relationship to existing decisions

- **AD-029** is complemented, not amended. It fixed the security floor; this
  fixes the premise. Its decision g withheld exactly the conclusion recorded
  here, so this is the follow-through rather than a contradiction.
- **AD-013 (wire it or delete it; no third state)** is untouched. This decision
  observes that several Store-3 subsystems are in AD-013's third state; it does
  **not** dispose of any of them.
- **AD-022** and **AD-023** are unaffected -- provenance on this path stays open
  under AD-029 h and D-5.
- **AD-028** and its addenda are unaffected; they concern dependency direction.

### Scope

Documentation only. It records what Store 3's implemented domain is and that a
second one does not exist. No production code, test, endpoint, schema,
configuration, database or Rust change accompanies it, and nothing is renamed
or deleted.

### Non-goals

Choosing merge, separate, partial retirement or deletion for Store 3; deleting
or wiring the permission-memory subsystem, the tier constants or
`get_seen_ids`; changing `/v1/approvals/*`; correcting the two stale
`ProactiveAgent` comments or the store's docstrings; deciding TTL, credential
mechanics, action binding, attempt caps, provenance or execution-state
semantics; correcting `MIGRATION_PLAN` §4.13's two-store count; creating
`policy/store.py` or a `PolicyEngine`.

### Consequences

- D-1 can now be asked accurately: it is a question about one domain, not two.
- AD-029's non-conforming endpoint is understood precisely -- it approves code
  patch application.
- Option "PARTIAL: retire the proactive half" is revealed to have no executable
  subject; what it would retire is dead APIs and naming, which is D-4 plus a
  documentation fix rather than a domain disposition.
- Anyone reading `tools/approval_store.py`'s header, its `ProactiveAgent`
  comments or its tier constants now has a decision record telling them those
  describe an anticipated design, not a running one.

### Evidence references

`tools/approval_store.py:1, 4, 6-8, 26-40, 45, 146, 174-181, 363-382` ·
`agent/execution/approval.py:40-46, 93-96, 122-174, 175-181` ·
`agent/runtime.py:1018, 1048, 1058, 1068, 1128` ·
`cli/agent_run_cmd.py:179, 184, 199, 215, 228, 240` ·
`server/approval_routes.py:1, 24, 41, 49-77` ·
`tests/test_approval_store_characterization.py` ·
`tests/server/test_approval_routes.py` · AD-013, AD-022, AD-023, AD-029

## AD-031 — Retire the dead remembered-permission subsystem in `tools/approval_store.py`

Recorded from the D-4 preflight. It settles the **disposition** of one dead
subsystem and deletes nothing: the removal is a separate, scoped slice. This is
the third of the six §4.13 questions to be answered, after AD-029 (the
credential contract) and AD-030 (Store 3 is one domain).

**The decision is RETIRE, not wire.** The reasoning is historical rather than
aesthetic: this is residue of a feature the repository's owner already decided
to remove, and wiring it back would both re-introduce a deleted product
capability and contradict AD-029 on an execution-gating path.

### Evidence

**[FACT] `permission_memory` is dead.** The table is created unconditionally by
`_create_tables` and is never read or written by any live path. Its four CRUD
methods -- `get_permission`, `set_permission`, `clear_permission`,
`list_permissions` -- have **zero production callers**; the only internal call
is `set_permission` consulting `get_permission`. `PermissionRule` is
constructed solely by those dead methods. `DECISION_ALWAYS_APPROVE`,
`DECISION_ALWAYS_DENY` and `DECISION_ASK` are defined and exported with **zero
production consumers**. Proved empirically as well as statically: a full action
lifecycle -- queue, approve, execute, `expire_stale`, both listings,
`get_seen_ids` -- leaves the table at zero rows
(`tests/test_approval_store_characterization.py`).

**[FACT] `get_seen_ids` is dead and structurally inert.** It has zero
consumers, and it could not work if it had one: it scans each row's `payload`
for `doc_id` and `message_id`, and the only live producer writes a
patch-proposal payload containing neither. For the domain that exists, it can
only ever return an empty set. `set_seen_ids` does not exist.

**[FACT] Nothing outside the module depends on any of it.** No CLI command, no
HTTP route, no README or product document, no example, no configuration key, no
plugin or tool contract. `grandpa.tools.__init__` does not re-export
`ApprovalStore`, `PermissionRule`, or any decision constant. Every occurrence in
`docs/` is AD-029 or AD-030 describing the deadness.

**[FACT] The history is specific.** `4652b6e8` *"[FEAT] Proactive Agents
(#364)"* added `agents/proactive_agent.py` (605 LOC),
`tools/proactive_tools.py` (585 LOC) and `tools/approval_store.py` (404 LOC)
**in one commit** -- so `ProactiveAgent` was a fully implemented feature, and
this store was its store. `c40b58ab` *"refactor(repo): focus Grandpa on local
Windows assistant"* -- the commit AD-001 cites as the owner's own scope
reduction -- **deleted `proactive_agent.py` and `proactive_tools.py`**, and
`approval_store.py` survived it. `12857932` *"feat(agent): add execution engine
v2"*, which is **later** than `c40b58ab`, introduced
`agent/execution/approval.py` and reused the surviving store for patch-proposal
approval.

**[FACT — and a limit on it]** **Whether retaining `approval_store.py` in
`c40b58ab` was intentional or accidental is not recorded anywhere**, and this
decision does not infer it. What the history establishes is that the *consumer*
was removed deliberately; it says nothing about the intent behind the store's
survival.

### The decisions

> **[DECISION AD-031 a]** The **remembered-permission subsystem is RETIRED**:
> `permission_memory`, `get_permission`, `set_permission`, `clear_permission`,
> `list_permissions`, `PermissionRule`, `DECISION_ALWAYS_APPROVE`,
> `DECISION_ALWAYS_DENY`, `DECISION_ASK` and `get_seen_ids`. Its disposition is
> **delete**, not wire.

> **[DECISION AD-031 b]** **Nothing is deleted by this decision.** No
> production code, test, schema, constant, comment or docstring changes here.
> Removal is a separate, scoped and reviewed slice.

> **[DECISION AD-031 c]** **Remembered permissions must not be wired back into
> the product.** Wiring would require inventing all four of: a reusable
> fingerprint scheme (today's key is unique per proposal, so a remembered
> decision could never match twice), remembered-decision semantics, tier/ask
> semantics, and a UI or CLI for managing and revoking remembered permissions.
> None exists.

> **[DECISION AD-031 d]** **Wiring would also conflict with AD-029.** An
> `always_approve` rule that stands in for a human decision on an
> execution-gating path is exactly what AD-029's out-of-band credential
> requirement exists to prevent. That conflict is a reason against wiring, and
> it is recorded so a future proposal has to answer it.

> **[DECISION AD-031 e]** **`ProactiveAgent` must not be recreated** to justify
> this subsystem or anything else. AD-030 c already establishes that no
> executable proactive-action domain exists, and this decision does not create
> a reason to build one.

> **[DECISION AD-031 f]** **The tier vocabulary is NOT retired by this
> decision.** `TIER_MEDIUM` is written by `agent/execution/approval.py:45` and
> the `tier` field is served by `GET /v1/approvals/pending`
> (`server/approval_routes.py:42`), pinned by pre-existing assertions in
> `tests/server/test_approval_routes.py`. Retiring the tiers touches a live
> producer, a live HTTP response field and an existing test, so it is a
> **separate decision and a separate slice**.

> **[DECISION AD-031 g]** **No database migration is authorised, and none is
> required.** Removing the `permission_memory` `CREATE TABLE` statement later
> is behaviour-preserving for everything currently implemented: the two tables
> are independent, with no foreign key, index, trigger or view between them,
> and the module carries no schema-version or migration code at all.
> **`DROP TABLE` against existing `approvals.db` files is explicitly NOT
> authorised**; an orphaned empty table is harmless because nothing reads it.
> Whether to clean it up is left open.

> **[DECISION AD-031 h]** **No public contract is broken.** None was found for
> remembered permissions. The only externally visible residue identified is the
> `tier` field in `/v1/approvals/pending`, which decision f puts outside this
> scope.

> **[DECISION AD-031 i]** **Explicitly still open**, and not narrowed by
> anything here:
>
> - **D-1** -- Store 3's final ownership: merge, remain separate, partial
>   retirement, or deletion.
> - **D-5** -- canonical approval semantics: TTL, action binding,
>   failed-attempt cap, provenance, execution-state tracking.
> - `/v1/approvals/{id}/approve` -- unchanged; still recorded as non-conforming
>   by AD-029 b.
> - Tier-vocabulary retirement.
> - Schema and data migration for deployed `approvals.db` files.
> - Final approval-store unification.
> - Whether any deployed external client reads the `tier` field.

> **[DECISION AD-031 j]** Documentation only. No production behaviour changes.

### Relationship to AD-013

**AD-013 reads "Wire or delete — no third state for security modules", and its
status remains *Recommended*.** Its body in this document is a heading; no
elaboration exists here or in `CURRENT_ARCHITECTURE.md`.

This decision **does not claim AD-013 literally compels it.** AD-013's recorded
scope says *security modules*, and every prior application of it --
`security/subprocess_sandbox.py`, `security/severity_policy.py`, and
`rate_limiter.py` via AD-027 -- was a module under `security/`. The
remembered-permission subsystem is not. What AD-031 does is **complement that
principle** for an approval subsystem outside `security/`, on the same
reasoning AD-027 used: present, unwired and undeleted is the state worth
resolving, and here it resolves on the delete side. Whether AD-013's scope
should be read more broadly is not settled here.

### Scope

Documentation only. It records a disposition. No production code, test,
endpoint, schema, configuration, database or Rust change accompanies it, and
nothing is deleted, renamed or migrated.

### Non-goals

Deleting any symbol, table or docstring; retiring the tier vocabulary;
dropping `permission_memory` from deployed databases; changing
`/v1/approvals/*`; recreating `ProactiveAgent` or any proactive-action feature;
choosing Store 3's ownership; deciding canonical approval semantics; correcting
`MIGRATION_PLAN` §4.13's two-store count; creating `policy/store.py` or a
`PolicyEngine`.

### Consequences

- One of AD-013's third-state occurrences now has a recorded disposition, so a
  future reader finds a decision rather than an undiscovered gap.
- A follow-up slice may remove the listed symbols and the `CREATE TABLE`
  statement. Its cost is known in advance: `TestRememberedPermissionsAreDead`
  (8 tests) plus 9 permission-API, 9 decision-constant, 5 `permission_memory`
  and 1 `get_seen_ids` reference in
  `tests/test_approval_store_characterization.py` would be removed or inverted.
  `tests/server/test_approval_routes.py` is **not** affected, because it
  references only tiers.
- The module's header, its `ProactiveAgent` comments and its class docstrings
  become stale on removal and should be corrected in the same slice.
- D-1 is unaffected: all four dispositions remain available for Store 3.

### Evidence references

`tools/approval_store.py:1-8, 26-28, 37-40, 105-140, 158-183, 297-382, 386-404`
· `agent/execution/approval.py:14, 40-46` · `server/approval_routes.py:42` ·
`tests/test_approval_store_characterization.py` ·
`tests/server/test_approval_routes.py:105-152` · commits `4652b6e8`,
`c40b58ab`, `12857932` · AD-001, AD-013, AD-027, AD-029, AD-030

## AD-032 — Retire the `/v1/approvals/*` route family

Recorded from the D-5 preflight. It settles the disposition of the last of the
§4.13 questions raised by the approval-store audit, and it **deletes nothing**:
the removal is a separate, scoped slice. AD-029 recorded
`POST /v1/approvals/{id}/approve` as non-conforming; this decides that the
non-conformance is resolved by **removal**, not by adding a credential.

**The route family, in full**, all three retired together:

    GET  /v1/approvals/pending
    POST /v1/approvals/{action_id}/approve
    POST /v1/approvals/{action_id}/deny

They live in one 79-line module and are registered as one router, so they are
retired as a unit rather than individually.

### Evidence

**[FACT] The routes have lost both their client and their domain.** They were
added by `c84f1fdd` *"feat: proactive agent approval bell with approve/deny UI
(#370)"* together with their only consumer -- `frontend/src/components/
ApprovalBell.tsx` and `frontend/src/lib/api.ts`. `2cabd560` *"fix: update
Grandpa project improvements"* (2026-07-26) deleted the entire `frontend/`
tree, 105 files including `ApprovalBell.tsx`. Separately, **AD-030** recorded
that Store 3 is the patch-proposal approval domain and that no executable
proactive-action domain exists. The routes' original consumer and their
original domain are both gone; the surviving `"approved via UI"` log message
and the module docstring are the only references left to either.

**[FACT] The approve route is non-conforming with AD-029**, on every count the
credential contract names:

| Property | Present? |
|---|---|
| Out-of-band credential | **No** |
| Action-bound approval credential (digest) | **No** |
| Replay protection | **No** -- `update_status` reports nothing about whether it changed a row |
| Atomic pending-state claim | **No** -- unconditional `UPDATE ... WHERE id = ?`, no `status = 'pending'` clause, no rowcount check |
| Approval TTL enforcement | **No** -- `get_action` applies no expiry filter, and `expire_stale` runs only on the *list* route, so a stale row can be approved by id |
| Requester/approver distinction | **No** -- an id from `GET /v1/approvals/pending` is sufficient |

The routes **are** API-key authenticated by default: `AuthMiddleware` protects
every `/v1/` and `/api/` path, `grandpa serve` generates and persists a key
when none exists, and `check_bind_safety` refuses a non-loopback bind without
one. **Authentication is not the missing property.** What is missing is the one
AD-029 a actually requires -- that the caller who stages an action cannot be
the caller who approves it. Authenticated HTTP access alone is enough to
transition a patch proposal to `approved`.

**[FACT] The route does not execute a patch.** It writes one row and calls no
executor. Patch application is reachable only from `grandpa agent patch apply`
(`cli/agent_run_cmd.py:240`), never over HTTP, and it still requires all three
of: workspace verification (`resolve_and_verify_workspace`), proposal freshness
(`is_proposal_fresh`, per-file hash against `original_hash`), and the
`approved` state (`agent/runtime.py:1068`). The route satisfies one of those
three. **None of these gates changes under this decision.**

**[FACT] The CLI is a complete, supported alternative.**
`grandpa agent patch preview` -> `patch show` -> `patch approve` -> `patch
apply` covers the whole lifecycle. Its approve step also takes only a proposal
id, so the mechanism is the same; what differs is the channel, and local
process access is a narrower trust boundary than a network credential.

**[FACT] Retirement removes no in-repo patch capability.** No production module
and no test calls these routes; the CLI path is untouched by their removal.

### The decisions

> **[DECISION AD-032 a]** The **`/v1/approvals/*` route family is RETIRED** --
> `GET /pending`, `POST /{id}/approve` and `POST /{id}/deny` together. Its
> disposition is **removal**.

> **[DECISION AD-032 b]** **Nothing is deleted by this decision.** No
> production code, test or route changes here. Removal is a separate, scoped
> and reviewed slice.

> **[DECISION AD-032 c]** **AD-029's Store-3 HTTP non-conformance is resolved
> by REMOVAL, not migration.** No credential is added to these routes, and no
> replacement HTTP approval API is authorised by this decision.

> **[DECISION AD-032 d]** **The CLI remains the supported patch approval
> path**: `patch preview` -> `patch show` -> `patch approve` -> `patch apply`.

> **[DECISION AD-032 e]** **Patch application's existing gates are unchanged**
> -- CLI-only invocation, workspace verification, proposal/file-hash freshness,
> and the `approved` state. This decision removes an approval *channel*; it
> removes no gate.

> **[DECISION AD-032 f]** **This is a potentially breaking API change, not
> dead-code cleanup.** No in-repo client remains, but external usage **cannot
> be proven absent**: FastAPI publishes these routes through its runtime
> OpenAPI schema and `/docs`, so they have been discoverable by any
> authenticated client since May 2026. The removal slice must be treated and
> released as a breaking change.

> **[DECISION AD-032 g]** **Retirement removes the only production caller of
> `ApprovalStore.expire_stale`** (`server/approval_routes.py:52`). After
> removal nothing marks stale rows `expired`, though `list_pending` already
> filters on `expires_at` independently. Recorded as a known consequence.
> **No replacement cleanup mechanism is invented or authorised here.**

> **[DECISION AD-032 h]** **Explicitly not decided**, and not narrowed by
> anything above:
>
> - **D-1** -- Store 3's final ownership, and approval-store unification.
> - Tier-vocabulary retirement -- still separate, per AD-031 f, even though
>   these routes are the `tier` field's only live output.
> - Store 3 schema or data migration.
> - External-client compatibility beyond acknowledging the risk in f.
> - Any replacement HTTP approval API.

> **[DECISION AD-032 i]** Documentation only. No production behaviour changes.

### Relationship to existing decisions

- **AD-029** is applied, not amended. Its decision b recorded this endpoint as
  non-conforming; AD-032 c chooses removal as the resolution. The credential
  contract itself is untouched and continues to bind every other approval path.
- **AD-030** supplies the premise: no proactive-action domain exists, so these
  routes govern patch approval rather than what they were designed for.
- **AD-031** is unaffected. Tier retirement stays separate under its decision f.

### Scope

Documentation only. It records a disposition. No production code, test, route,
schema, configuration, database or Rust change accompanies it, and nothing is
deleted or renamed.

### Non-goals

Deleting any route, module or test; adding a credential to these routes;
designing a replacement HTTP approval API; retiring the tier vocabulary;
migrating Store 3's schema or data; choosing Store 3's ownership; inventing a
replacement for `expire_stale`; changing any patch-application gate; changing
`AuthMiddleware` or the server's bind and auth defaults.

### Consequences

- The follow-up slice would remove `server/approval_routes.py` (79 lines), the
  `include_router(approval_router)` registration at
  `server/api_routes.py:2151`, and `tests/server/test_approval_routes.py`
  (29 tests). Its cost is therefore known before it starts.
- The `tier` field's only live consumer is `_serialize` in that module, so
  after removal the tier vocabulary would have no runtime output at all. That
  makes the separate tier decision simpler; it does not make it here.
- `tests/server/test_approval_routes.py` mounts the router on a bare
  `FastAPI()` with no middleware and asserts nothing about authentication, so
  no auth contract is lost with it. Recorded so its removal is not later
  mistaken for lost security coverage.
- After removal, patch approval has exactly one channel, which is the property
  AD-029 wanted and could not get from an uncredentialed HTTP route.

### Evidence references

`server/approval_routes.py:1, 24, 28-32, 49-77` · `server/api_routes.py:2151` ·
`server/auth_middleware.py:40-90, 105-131` · `cli/serve.py:367-387` ·
`tools/approval_store.py` (`get_action`, `update_status`, `expire_stale`) ·
`agent/runtime.py:1034, 1058, 1068, 1078, 1128` ·
`agent/execution/approval.py:122-181` · `cli/agent_run_cmd.py:176-243` ·
`tests/server/test_approval_routes.py` · commits `c84f1fdd`, `2cabd560`,
`c40b58ab`, `12857932` · AD-029, AD-030, AD-031

---

# Part II — Standing decisions

*(Unchanged from the discovery draft except where noted. Full evidence in
`CURRENT_ARCHITECTURE.md` §2–§3.)*

## AD-001 — Windows-first assistant on a retained internal substrate

**[DECISION]** The Windows assistant is the product; the composable-intelligence
platform is infrastructure; the SDK is a secondary surface; A2A is not a product
surface.

**Evidence summary.** 83% of commits are inherited upstream work. Every
post-rebrand commit, roadmap item, persona, and user-facing doc targets the
assistant. `GrandpaConfig`'s 26 sections contain **no** Desktop/Screen/
Automation/Vision/Voice section; `EventType`'s 30+ members contain **zero**
desktop events — the config schema and observability plane model the inherited
platform. Yet that platform is load-bearing: `core.config` (112 importers),
`core.registry` (95), `core.types` (78), `core.events` (47).

**Strengthened by AD-021.** The owner already executed this exact scope
reduction in commit `c40b58ab`, *"refactor(repo): focus Grandpa on local Windows
assistant"*, deleting five capability modules. AD-001 ratifies a decision the
repository has already made.

**Amended by AD-020.** The product definition includes the autonomous
software-development mode (`agent/development/`, `grandpa project|roadmap|sprint`).

## AD-002 — Archive the Rust workspace out of tree

**[DECISION]** Move `rust/` (17 crates, 27,035 LOC) to an archive branch or
separate repository with full history. Remove the `rust` CI job and the
`maturin develop` step. Fix `_rust_bridge.py`'s false contract first.

**Evidence summary.** Since the rebrand: **one** substantive change, 18
insertions in `grandpa-tools/src/builtin/http_tools.rs` (`cde132da`,
2026-07-26). The 17 crates mirror the OpenJarvis platform exactly, with **no**
crate for desktop, voice, screen, vision, automation, or browser. The wheel is
`hatchling`-built and cannot contain a cdylib. All 16 call sites fall back.
`link.exe` is absent on the developer's Windows machine, so the native layer of
a Windows-only product does not build on Windows.

**Now gated on AD-019, not blocked by it.** Q-3 is resolved: archiving is
lawful and safe. Sequence AD-019 → AD-002.

## AD-003 — SDK is a secondary, supported surface
## AD-004 — MCP server gated behind explicit opt-in
## AD-005 — One `IntentDispatcher`
## AD-006 — One `PolicyEngine` — **priority raised by AD-022**
## AD-007 — Collapse `engine/` into `runtime/`
## AD-008 — `agents/` is the agent framework — **re-scoped by AD-020**

`agent/executor.py`, `agent/context.py`, `agent/models.py`, `agent/runtime.py`
absorb into `agents/` to resolve the five colliding type names.
**`agent/development/` is explicitly excluded from this merge and is retained.**

## AD-009 — `planner/` is the assistant planner
## AD-010 — One `MemoryFacade`, four named stores — **needs approval**
## AD-011 — One `browser/` package; redaction at ingress
## AD-012 — Archive `a2a/`, `kernel/`, `templates/`, `daemon/`
## AD-013 — Wire it or delete it; no third state
## AD-014 — One `VoiceSession`
## AD-015 — One event bus; audit becomes a subscriber — **extended by AD-022** to record action origin
## AD-016 — `windows-latest` CI is a hard prerequisite
## AD-017 — Config schema describes the product
## AD-018 — Merge the stabilization branch first

*(Rationale for AD-003 through AD-018 is unchanged; see `CURRENT_ARCHITECTURE.md`
§8 for the per-subsystem evidence and `MIGRATION_PLAN.md` for sequencing.)*

---

# Part III — Question ledger

## Resolved

| ID | Question | Answer | Decision |
|---|---|---|---|
| **Q-3** | Do the inherited components carry attribution/licensing obligations? | **Yes.** Hard fork of Apache-2.0 upstream (83% of history, 36 authors). §4(a) and §4(d) satisfied; **§4(b) and §4(c) not**. Upstream copyright line was deleted at `ad316476`. No NOTICE ever existed, so nothing was lost there. ffmpeg is LGPL-3 but subprocess-invoked → mere aggregation, licence text already shipped. **Fix is <1 hour. Archiving is lawful and safe.** | **AD-019** |
| **Q-4** | Is `agent/development/` product, personal tool, or inherited scope? | **Product.** Owner-authored 2026-08-01…04 (newest code in the repo), not present upstream, 23 import sites, 3 CLI groups with top-level imports, 6 test files including `test_final_acceptance.py`, 4 doc pages, and live state modified today. **RETAIN.** | **AD-020** |
| **Q-5** | Are the 7 orphaned databases safe to delete? | **Audited live, read-only.** All are residue from the owner's own 2026-06-01 feature burst, removed by `c40b58ab`. Five contain no user data (2 demo rows, 5 simulation rows, 0 rows, 10 blocked test rows, 2 sync cursors). Two do: `autonomous_workflows.db` (46 rows, all dry-run) and `mobile_integration.db` (**credential-shaped**, though all `paired=0, trusted=0`). Per-DB dispositions assigned. **Nothing deleted.** | **AD-021** |
| **Q-7** | Was the Rust workspace ever built successfully after the rebrand? | **No evidence it was.** One 18-line commit, no build artifacts, no performance data, absent from the wheel, and `link.exe` missing on the dev machine. AD-002 stands. | **AD-002** |
| **Q-10** | Should agent-/skill-originated actions require approval at a lower risk threshold than user-typed ones? | **No.** Policy is provenance-agnostic and `ActionOrigin` is audit-only: origin changes no risk tier and no approval requirement, and may never lower either. Every enforcement point was traced and none consumes it — `classify_risk` ignores it by documented design, the approval expression omits it, the digest excludes it, and the approval token is random. The only rule ever proposed (AD-022's `direct`-versus-`agent` example) was a *relaxation* landing on the value that is also the unknown-origin fallback, and is superseded. Pinned executably across all six values by Q-10E. | **AD-023**; Q-10E (`tests/test_action_origin_invariant.py`) |

## Still open

| ID | Question | Blocks | Needed by |
|---|---|---|---|
| **Q-0** | Does `ARCHITECTURE_BASELINE.md` exist outside git? | Confidence in AD-001/AD-002 | Now |
| **Q-1** | Is Grandpa meant to be embedded (`import grandpa`) or only run (`grandpa chat`)? | AD-003; SDK stability contract | Phase 3 |
| **Q-2** | Is third-party extensibility via the MCP **server** a product goal? README says no; code says yes. | AD-004 | Phase 3 |
| **Q-3a** | Is the upstream OpenJarvis repository still public and still Apache-2.0? | Wording of the NOTICE file | Phase 0 |
| **Q-6** | Wiring `rate_limiter` / `injection_scanner` changes behaviour. Acceptable, at what thresholds, and what happens on a flag — log, warn, or block? | AD-013, Phase 1.2 | Phase 1 |
| **Q-8** | Is PyPI publishing wanted? The name `grandpa` belongs to an unrelated party. | Release automation, `self-update` | Phase 1 |
| **Q-9** | What is in `wip/floating-bubble-final` (2 unmerged commits)? | Possibly a 7th UI surface | Phase 5 |

## Decisions deliberately not taken

| Non-decision | Why left open |
|---|---|
| Splitting into `grandpa-assistant` + `grandpa-platform` | Depends entirely on Q-1 |
| Adopting real embeddings for memory retrieval | Product-quality decision. AD-010 only requires the *naming* stop overstating what exists. |
| Adding a Dockerfile | A Windows-only assistant may legitimately not want one |
| Purging vendored ffmpeg from history | A history rewrite with its own risk profile, independent of the architecture — and **not** required for LGPL compliance, since the build is subprocess-invoked and its licence text ships |
| The specific risk-tier table in `PolicyEngine` | AD-006 fixes the *mechanism*; the tiers are a security decision to make with the table in front of you |
| Whether to relicense Grandpa-era code | Possible under Apache-2.0 for the derivative portion, but AD-019 must land first and it is not an architecture question |
