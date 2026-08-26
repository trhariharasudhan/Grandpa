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
   carry `origin ∈ {user, skill, agent, api, scheduler}`, and the policy table
   should be able to require approval based on origin — e.g. a `MEDIUM` action
   from `user` may proceed while the same action from `agent` requires approval.
   `security/taint.py` already exists and is unused; this is its natural home.
3. **The audit trail must record origin.** Today it cannot distinguish a
   user-typed action from a model-selected one.
4. **`config.skills.enabled` is a security-relevant setting** and should be
   documented as one.

**[RECOMMENDATION]** Add origin-tagging to Phase 4 alongside `PolicyEngine`. It
is a small addition at design time and expensive to retrofit.

**[OPEN QUESTION] Q-10 (new).** Should agent- and skill-originated actions
require approval at a *lower* risk threshold than user-typed ones? This is a
policy decision, not an architecture one, but the architecture must support it.

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
| **Q-10** | **(new)** Should agent-/skill-originated actions require approval at a lower risk threshold than user-typed ones? | Policy table design in Phase 4 | Phase 4 |

## Decisions deliberately not taken

| Non-decision | Why left open |
|---|---|
| Splitting into `grandpa-assistant` + `grandpa-platform` | Depends entirely on Q-1 |
| Adopting real embeddings for memory retrieval | Product-quality decision. AD-010 only requires the *naming* stop overstating what exists. |
| Adding a Dockerfile | A Windows-only assistant may legitimately not want one |
| Purging vendored ffmpeg from history | A history rewrite with its own risk profile, independent of the architecture — and **not** required for LGPL compliance, since the build is subprocess-invoked and its licence text ships |
| The specific risk-tier table in `PolicyEngine` | AD-006 fixes the *mechanism*; the tiers are a security decision to make with the table in front of you |
| Whether to relicense Grandpa-era code | Possible under Apache-2.0 for the derivative portion, but AD-019 must land first and it is not an architecture question |
