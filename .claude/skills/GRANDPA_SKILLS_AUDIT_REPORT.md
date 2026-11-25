# GRANDPA Repository Audit and Claude Skills Report

- **Repository:** `trhariharasudhan/Grandpa` (public), default branch `main`
- **Baseline audited:** `fde2164` – "fix(odin): voice notebook fits a free Colab session" (2026-11-24)
- **Audit date:** 2026-11-25, in a Linux cloud container (Python 3.13, uv 0.11)
- **Method:** directory inventory, reading module docstrings and key implementations, grep-based
  dependency/caller checks, running the CLI with a throwaway `GRANDPA_HOME`, running ruff and the full
  deterministic pytest suite, and reading GitHub Actions results through the API.
- **Tag legend:** **[VERIFIED]** = checked against code or a command in this audit; **[DOC]** = taken from
  the repo's own documents and not re-run here; **[UNKNOWN]** = could not be determined.

Secrets: no `.env` file is tracked, `configs/grandpa/config.toml` contains no credentials, and no key or
token was copied into this report or the skills. [VERIFIED]

---

## 1. Summary

GRANDPA (product name *Grandpa*, model-family codename *Odin*) is a large, actively developed,
Windows-first local assistant: ~167k lines of Python, ~123k lines of tests, 60 CLI commands, a 174-action
catalogue behind one executor, local Ollama models, a voice stack with wake word and several TTS
backends, screen OCR/UIA, workflows, plugins, MCP, a FastAPI server, phone pairing and a Raspberry Pi
home-server mode. [VERIFIED]

Its strongest property is **safety engineering**: one action door with risk tiers, confirmation that
refuses when nobody can be asked, deny-by-default extensions, encrypted credentials, and a test harness
that physically prevents tests from actuating the machine or writing outside a sandbox.

Its weakest property is **structural fragmentation** inherited from an earlier platform codebase
(OpenJarvis/IPW): duplicate frameworks (two agent systems, several planners, two memory systems, two
"kernel" packages), heavy import cycles, ~1,000 `except Exception` sites, and documentation that lags
the code in several places.

Ten Claude Code skills were created under `.claude/skills/` (1 master + 4 essential + 5 recommended), all
validated by a script included in the set.

**Overall project score: 7.0 / 10** (details in §11).

---

## 2. Phase 1 – Repository inventory

### 2.1 Areas inspected (22)

| # | Area | Path(s) | Inspected how |
|---|---|---|---|
| 1 | Root config & docs | `README.md`, `pyproject.toml`, `uv.lock`, `CONTRIBUTING.md`, `CHANGELOG.md`, `AUDIT.md`, `implementation_plan.md`, `piper_pilot_plan.md`, `mkdocs.yml`, `.gitignore`, `.dockerignore`, `.pre-commit-config.yaml`, `grandpa.cmd` | read |
| 2 | Claude config | `.claude/settings.json`, `scripts/hooks/*.py` | read |
| 3 | CI/CD | `.github/workflows/*.yml`, Actions run history | read + API |
| 4 | CLI | `src/grandpa/cli/` (86 files) | registration parsed; `--help` run for 20 commands |
| 5 | Action layer | `src/grandpa/action_layer/` | read in depth; catalogue enumerated |
| 6 | Legacy policy / phrase routing | `pc_control.py`, `desktop/kernel/`, `local/`, `router/`, `jarvis/` | read outlines/docstrings |
| 7 | Desktop actuation | `desktop/control/`, `automation/`, `apps/`, `files/`, `windows_*.py` | docstrings + catalogue bindings |
| 8 | Browser | `browser_control.py`, `browser/`, `browser_awareness/`, `browser_intelligence/` | docstrings |
| 9 | Screen / vision | `screen/`, `vision/`, `screen_awareness.py`, `desktop_context.py` | docstrings + CLI help |
| 10 | Voice / speech | `voice/`, `speech/`, `voice_service/`, `voice_runtime/`, `ui/lipsync.py` | docstrings, engine selection code, CLI help |
| 11 | UI | `ui/` (bubble, tk view, avatar web) | docstrings |
| 12 | Models | `runtime/`, `engine/`, `intelligence/`, `models/` pkg, repo `models/Modelfile.*`, `scripts/odin/`, `notebooks/` | read |
| 13 | Memory / knowledge | `memory_context.py`, `memory/`, `knowledge/`, `connectors/`, `tools/storage/` | read + caller checks |
| 14 | Agents / planning | `agents/`, `agent/`, `planner/`, `workflow/`, `kernel/`, `skills/`, `skill_builder/` | docstrings + prior audits |
| 15 | Workflows / scheduler | `workflow/`, `scheduler/`, `task_scheduler.py`, `reminders.py`, `scheduler_daemon.py` | read |
| 16 | Plugins / MCP | `plugins/`, repo `plugins/hello/`, `mcp/` | read |
| 17 | Server / devices | `server/`, `devices/` | read; route counts |
| 18 | Security | `security/`, `security_safety.py`, `local_action_approvals.py` | read; caller checks |
| 19 | Config | `core/config.py` (32 config classes), `configs/grandpa/`, ~100 `GRANDPA_*` env vars | read |
| 20 | Tests | `tests/` (527 files), guards, `pyproject` markers | read + full run |
| 21 | Rust | `rust/` (17 crates), `_rust_bridge.py` | inventory only |
| 22 | Docs | `docs/` (architecture, audit, user guides, manual QA) | headings + targeted reads |

### 2.2 Scale [VERIFIED]

| Measure | Value |
|---|---|
| Python source files / lines | 688 / ~167,400 |
| Test files / lines | 527 `test_*.py` / ~123,000 |
| Tests collected (deterministic markers) | 9,723 |
| Rust files / lines / crates | 124 / ~27,000 / 17 |
| Registered CLI commands | 60 |
| HTTP route decorators | ~188 |
| Catalogued actions | 174 (112 LOW, 51 MEDIUM, 11 HIGH; 35 require confirmation) |
| Distinct SQLite filenames in source | 32 |
| `GRANDPA_*` environment variables | ~100 |
| `except Exception` sites | ~1,005 |
| Duplicate top-level class names | 35 |
| Commits on `main` (fetched depth) | 542 in the last 400-commit window; very active (14 PRs on 2026-11-15 to 11-24) |

### 2.3 Existing Claude configuration

- `.claude/settings.json` with three hooks: `block_escaped_heredoc.py` and `require_sandboxed_probe.py`
  (PreToolUse on Bash) and `require_pushed_commits.py` (Stop). [VERIFIED]
- **Existing Claude Skills discovered: 0.** No `SKILL.md` anywhere in the tree before this work. [VERIFIED]
- No `CLAUDE.md`. [VERIFIED]
- Note: `src/grandpa/skills/` and `skills/data/*.toml` (18 TOML "skills") are the **product's** runtime skills,
  not Claude skills. The new Claude skills are all prefixed `grandpa-` and documented as distinct.

---

## 3. Phase 2 – Technical architecture

### 3.1 Identity and origin

The tree is a rebrand (2026-05-23) of an inherited composable-intelligence platform (OpenJarvis, derived
from IPW). The platform layer (`core/`, `agents/`, `tools/`, `engine/`, `security/`, `telemetry/`, `traces/`,
`skills/`, `workflow/`, `mcp/`, `rust/`) is substrate; the Windows assistant was built on top, partly as
flat modules. [DOC: `docs/architecture/CURRENT_ARCHITECTURE.md` §2.3, consistent with code fingerprints]

### 3.2 Layer map

```
ENTRY      grandpa chat/ask · voice/voice-operator/jarvis · bubble/avatar · FastAPI · phones · triggers
ROUTING    deterministic phrase handlers (local/, cli/_*_route.py) → model tool loop (action_layer/loop.py)
           or agents/ + tools/ (agent mode)
POLICY     action_layer.executor.execute: lookup → validate → confirm → call → audit
           (risk tiers mirrored from pc_control; plugin__*/mcp__* dynamic actions)
ACTUATION  desktop/control, automation, apps, files, browser*, screen, vision, notes, downloads,
           gmail, calendar, web_search, reminders, task_scheduler
MODELS     engine/ (shim) → runtime/ (OllamaBackendAdapter, NativeAdapter) → Ollama :11434
STATE      GRANDPA_HOME (~/.grandpa): ~32 SQLite DBs, JSONL audit log, secrets/, plugins/, workflows/
```

### 3.3 Major modules (17)

| Module | Purpose | Location | Inputs → Outputs | Status | Known limitations |
|---|---|---|---|---|---|
| CLI | all user commands | `cli/` | argv → console/actions | Implemented | `chat_cmd.py` 2.3k lines; duplicated post-response side effects |
| Action layer | single execution door | `action_layer/` | `ActionRequest` → `ActionResult` + audit | Implemented | catalogue file 3.2k lines |
| Legacy policy | risk tables, staged approvals, emergency stop | `pc_control.py`, `desktop/kernel/` | requests → approvals | Implemented (legacy) | heaviest import cycle `pc_control`↔`desktop` |
| Phrase router | allowlisted phrases | `local/` | user text → action | Implemented | regex/keyword based |
| Desktop control | Windows services | `desktop/control/`, `automation/` | service requests → OS effects | Implemented (Windows) | Linux paths degrade |
| Browser | visible-browser control | `browser*` | actions → page/tab effects | Partial | form fill/download excluded |
| Screen/vision | capture, OCR, UIA, VLM | `screen/`, `vision/` | pixels/UIA → text/descriptions | Implemented | duplicated with `screen_awareness.py` |
| Voice | capture, STT, wake, TTS | `voice/`, `speech/`, `voice_service/` | audio ↔ text | Implemented | two TTS selection paths |
| UI | bubble, avatar | `ui/` | events → window | Implemented | Windows/pywebview |
| Models | Ollama runtime, Odin roles | `runtime/`, `engine/`, `intelligence/` | prompts → completions | Implemented | engine/runtime duplication |
| Memory | personal + V1 + RAG | `memory_context.py`, `memory/`, `knowledge/`, `connectors/`, `tools/storage/` | facts/docs → recall | Implemented, fragmented | `memory.db` two writers |
| Agents/planning | agent frameworks, planners | `agents/`, `agent/`, `planner/`, `kernel/` | goals → plans | Partial | duplicated frameworks |
| Workflows | YAML routines + triggers | `workflow/` | YAML → action runs | Implemented | also an older TOML graph loader |
| Scheduler/reminders | reminders, routines | `reminders.py`, `task_scheduler.py`, `scheduler/` | schedules → delivery | Implemented | daemon off by default |
| Extensions | plugins, MCP | `plugins/`, `mcp/` | manifests → dynamic actions | Implemented | plugins in-process |
| Server/devices | HTTP API, phones, headless | `server/`, `devices/` | HTTP → actions/chat | Implemented | large inherited `/v1` surface |
| Security | secrets, SSRF, guardrails | `security/` | – | Mixed | some modules orphaned |

Dependency direction and the 23 package-level cycles are documented in
`docs/architecture/CURRENT_ARCHITECTURE.md` §6 [DOC]; the `pc_control`↔`desktop` and `cli`↔`voice` cycles
are still visible in imports at this commit (module docstring of `desktop/__init__.py` says so). [VERIFIED]

### 3.4 Lifecycle highlights [VERIFIED]

- Console script `grandpa = grandpa.cli:main`; commands are lazy-loaded so `grandpa --help` stays cheap.
- State root: `GRANDPA_HOME` (default `~/.grandpa`); `core.config.DEFAULT_CONFIG_DIR` is evaluated **at import**,
  so the env var must be set before importing `grandpa` (the reason for the sandbox hook).
- Chat: deterministic handlers first, then the action-layer tool loop by default (`[tools] chat_tool_loop`).
- Scheduler is off by default; reminders are delivered late rather than lost.
- Server: API key generated and stored in the secret store on first `grandpa serve`.

---

## 4. Capability matrix (implemented / partial / planned / experimental / missing)

The maintained matrix is `.claude/skills/grandpa-master-orchestrator/references/capability-status.md`.
Summary:

| Status | Capabilities |
|---|---|
| **Implemented** | text chat; model tool use; deterministic phrase commands; risk/confirmation/audit; Windows app/window/volume/brightness/power; synthetic input (always confirmed); files; process kill; screen capture/OCR/describe; UIA read & click; screen privacy; push-to-talk; wake word (needs model); local STT; TTS (pyttsx3/Piper/Tamil/Kokoro/F5 service/ElevenLabs opt-in); bubble & avatar; Odin roles/setup/eval; personal memory; Memory V1; reminders; routines; YAML workflows & triggers; plugins; MCP stdio servers; Gmail/Calendar (optional extras); web search; API server; phone pairing & remote approvals; headless node; encrypted credentials |
| **Partial** | visible-browser control (form fill/download excluded); hands-free VAD; document RAG/knowledge; autonomous agents/planning (goal understanding rated BROKEN in `docs/audit/CAPABILITY-MAP.md`) |
| **Experimental** | Odin-1 LoRA fine-tune; own cloned-voice training (Piper/RVC/F5 tooling) |
| **Orphaned / registered but unused** | prompt-injection scanner; `grandpa-guard` safety model role |
| **Optional / inherited** | Rust workspace (Python fallbacks everywhere) |
| **Planned (vision only)** | hardware/IoT/home automation, robotics |
| **Missing (and should stay so)** | voice-identity authentication |

---

## 5. Phase 3 – Skill requirement discovery

### 5.1 Evaluation criteria

Each candidate was scored on: (1) exists in repo, (2) complexity, (3) development frequency (recent PRs),
(4) independent workflows, (5) specialised knowledge, (6) overlap with another skill, (7) context savings,
(8) accuracy gain for Claude.

### 5.2 Candidate evaluation

| Candidate area | Exists | Freq. (recent PRs) | Distinct workflows | Decision |
|---|---|---|---|---|
| Architecture & coordination | yes | – | routing, rules | **Master skill** (`grandpa-master-orchestrator`) |
| Tool execution / computer control / OS integration / automation | yes, central | very high | add action, debug tool calls | **Essential** – merged into `grandpa-action-layer` (one executor serves all) |
| Testing & QA + debugging | yes, very rich infra | every PR | scope, guards, CI, commit guard | **Essential** (`grandpa-testing-qa`; debugging folded in) |
| Security & permissions | yes, many boundaries | high (C4, D1–D4, E1, G1, G2) | review lens | **Essential** (`grandpa-security-governance`) |
| Voice / STT / TTS | yes, largest recent area | very high (B1–B6, H1, VOICE) | diagnose, tune, add backend | **Essential** (`grandpa-voice-pipeline`) |
| Ollama / local LLM / model engineering | yes | high (O2, O3, #11, #21) | eval, roles, fine-tune data | **Recommended** (`grandpa-local-models`) |
| Memory / database engineering | yes, high risk | medium (#22) | recall measure, migrations | **Recommended** (`grandpa-memory-knowledge`; DB engineering folded in) |
| Vision / multimodal | yes | high (C1–C4) | privacy-first perception | **Recommended** (`grandpa-screen-vision`) |
| Automation engineering (workflows, plugins, MCP, scheduler) | yes | high (F1–F3, G1, G2) | create/validate/trigger, plugin, MCP | **Recommended** (`grandpa-workflows-extensions`) |
| API & integration engineering | yes | medium (P2, D-series) | endpoint pattern, headless | **Recommended** (`grandpa-api-server`) |
| Frontend / UI (bubble, avatar web) | yes, small | medium (A1–A7) | manual-QA heavy | **Optional – not created**; orchestrator + `docs/testing/avatar-manual-qa.md` suffice |
| Agent orchestration / planning | yes, duplicated | low recently | consolidation | **Optional – not created**; would encode a structure the owner may retire (see MIGRATION_PLAN) |
| Performance optimisation | scattered | low | – | **Not created**; folded into models (keep_alive, tool tiering) and testing |
| Documentation engineering | yes | medium | – | **Not created**; maintenance rules in the master index |
| Release & deployment | yes (release gate, autotag, docker) | low | – | **Not created**; folded into testing-qa and api-server |
| Rust workspace | inherited | ~none | – | **Should NOT be created** (optional, Python fallbacks) |
| Hardware / IoT | no | – | – | **Future** (create when code exists) |
| Robotics | no | – | – | **Future** |
| Developer workflow automation | hooks exist | – | – | **Not created**; covered by governance + testing |

### 5.3 Proposed skill specifications

Common to all: trigger is the `description` (keywords a developer would say); outputs are code changes +
tests + an honest report; every skill depends on the orchestrator's rules and ends with testing-qa.

| Skill | Priority | Purpose / problems solved | Responsibilities | Key modules | Expected workflows | Depends on | Justification |
|---|---|---|---|---|---|---|---|
| `grandpa-master-orchestrator` | Master | Claude otherwise starts from a 167k-line tree with stale architecture docs | map, rules, routing, capability truth, skill maintenance | whole repo | orient → route → verify | – | prevents wrong-layer edits and unsafe probes |
| `grandpa-action-layer` | Essential | new actions break tier mirroring, import isolation or confirmation | catalogue, `_CALLS`, tiers, domains, tool loop | `action_layer/`, `pc_control.py`, `desktop/control/`, `local/` | add action; debug tool call | security, testing | the hub every feature passes through |
| `grandpa-testing-qa` | Essential | guards, markers and commit guard are non-obvious; tests can damage the machine | scope selection, guards, CI parity, probes | `tests/`, `scripts/commit_verification.py`, CI | which tests → run → report | – | highest leverage for correctness and safety |
| `grandpa-security-governance` | Essential | many boundaries, easy to weaken one while fixing another | boundary review, hard constraints | `security/`, `server/auth_middleware.py`, `devices/`, `plugins/`, `mcp/`, `screen/privacy.py` | five-question review | action-layer | the product actuates a real PC |
| `grandpa-voice-pipeline` | Essential | voice bugs have many look-alike causes; thresholds were tuned from measurements | diagnose, PTT/VAD/wake, STT, TTS backends | `voice/`, `speech/`, `ui/lipsync.py` | diagnose → stage fix; add backend | action-layer, models | most active area |
| `grandpa-local-models` | Recommended | model changes made by taste instead of eval | roles, Modelfiles, eval, runtime | `intelligence/`, `runtime/`, `models/` | roles/setup/eval; fine-tune data | testing | stable Odin role contract |
| `grandpa-memory-knowledge` | Recommended | multiple stores; live user data | store map, recall measurement, safe migration | `memory_context.py`, `memory/`, `knowledge/`, `tools/storage/` | trace store → measure → migrate safely | models, security | highest data-loss risk |
| `grandpa-screen-vision` | Recommended | privacy gate must precede every capture | capture/OCR/UIA/VLM layers | `screen/`, `vision/` | layer-specific fix | action-layer, security | sensitive perception |
| `grandpa-workflows-extensions` | Recommended | four extension mechanisms with different trust rules | choose mechanism, formats, triggers, reminders | `workflow/`, `plugins/`, `mcp/`, `reminders.py` | validate → dry run → trigger | action-layer, security | user-facing automation |
| `grandpa-api-server` | Recommended | HTTP is a second door with its own auth and headless filter | endpoint pattern, auth, devices, headless | `server/`, `cli/serve.py` | add route + 401/headless tests | action-layer, security | remote-surface safety |

---

## 6. Phase 4 – Skill ecosystem architecture

- **A. Master:** `grandpa-master-orchestrator` – map, shared rules, routing table, capability status, validator.
- **B. Specialists:** nine domain skills, each with a short SKILL.md (47–81 lines) and at most one reference file.
- **C. Supporting knowledge:** `references/*.md` (architecture map, capability status, governance, routing,
  catalogue guide, test infrastructure, boundaries, voice map, Odin roles, memory stores, extension formats)
  and three scripts.

Progressive disclosure: descriptions are always visible to Claude; SKILL.md loads on use; references load
only when a step needs them; scripts are executed, not read.

Conflict avoidance: rules are stated once (orchestrator `governance.md`); specialists restate only the rules
they enforce. Overlaps are resolved by an explicit owner table in `references/skill-routing.md`.

### 6.1 Dependency map

```
                     grandpa-master-orchestrator
                               │
  ┌──────────────┬─────────────┼──────────────┬────────────────┬────────────────────┐
  ▼              ▼             ▼              ▼                ▼                    ▼
action-layer  voice-pipeline screen-vision memory-knowledge local-models  workflows-extensions
  │   ▲ (all actuation goes through the action layer) ▲
  ▼
security-governance ◄── api-server
  │
  ▼
testing-qa (final step of every skill)
```

---

## 7. Phase 5 – Files created

```
.claude/skills/
├── GRANDPA_SKILLS_MASTER_INDEX.md
├── GRANDPA_SKILLS_AUDIT_REPORT.md
├── grandpa-master-orchestrator/
│   ├── SKILL.md
│   ├── references/{architecture-map,capability-status,governance,skill-routing}.md
│   └── scripts/validate_skills.py
├── grandpa-action-layer/
│   ├── SKILL.md
│   ├── references/catalogue-guide.md
│   └── scripts/catalogue_report.py
├── grandpa-testing-qa/
│   ├── SKILL.md
│   ├── references/test-infrastructure.md
│   └── scripts/which_tests.py
├── grandpa-security-governance/{SKILL.md, references/boundaries.md}
├── grandpa-voice-pipeline/{SKILL.md, references/voice-architecture.md}
├── grandpa-local-models/{SKILL.md, references/odin-models.md}
├── grandpa-memory-knowledge/{SKILL.md, references/memory-stores.md}
├── grandpa-screen-vision/SKILL.md
├── grandpa-workflows-extensions/{SKILL.md, references/formats.md}
└── grandpa-api-server/SKILL.md
```

Outside `.claude/skills/`, only `.gitignore` changed: it ignored everything under `.claude/` except
`settings.json`, so `!.claude/skills/` was added to let the skills travel with the repository (the same
reason the file gives for the hooks). No source code was changed.

---

## 8. Phase 7 – Skill validation report

| Check | Method | Result |
|---|---|---|
| Folder naming, `SKILL.md` present | `validate_skills.py` | 10/10 pass |
| YAML frontmatter valid, on line 1 | PyYAML `safe_load` | 10/10 pass |
| Required metadata (`name`, `description`), portable keys only | script | pass (only `name`, `description` used, so the skills also upload to claude.ai) |
| Name = folder, kebab-case, ≤64 chars, no reserved words | script | pass |
| Description 40–1024 chars, no angle brackets, includes trigger keywords | script + review | pass |
| SKILL.md < 500 lines (official guidance) | script | pass (47–101 lines) |
| Relative links resolve | script | pass |
| Scripts compile | `py_compile` | pass; `ruff check` and `ruff format` clean |
| Scripts work | executed | `catalogue_report.py --summary` → 174 actions; `which_tests.py` mappings match the commit guard; validator → PASSED |
| No secret-like strings | regex scan | pass |
| Index ↔ folders consistent | script | pass |
| Technical accuracy | every path/command/count re-checked against `fde2164` during writing | pass, with unknowns marked |
| Duplicates / contradictions | manual review; rules centralised in `governance.md` | none found |
| Official format | compared with code.claude.com/docs/en/skills (fetched 2026-11-25): project skills in `.claude/skills/<name>/SKILL.md`, description drives triggering, keep SKILL.md under 500 lines, reference supporting files with relative links | conforms |

Not validated: real-world triggering accuracy (needs usage in Claude Code sessions), and behaviour of the
skills' commands on Windows (run here on Linux).

---

## 9. Findings

### 9.1 What works well

1. **One action door** with typed requests, honest error codes, audit, and "no callback = no consent". [VERIFIED]
2. **Test harness that protects the machine** (actuation, write and host-state guards; sandbox; verification
   plugin; commit guard) – rare and excellent. [VERIFIED]
3. **Deny-by-default extensions** (plugins pinned by fingerprint, MCP allow-lists, device path allow-list,
   headless 404 filter). [VERIFIED]
4. **Credentials at rest** via DPAPI/keyring with honest reporting of weak fallback. [VERIFIED]
5. **Measurement culture** – recall@k, word error rate, timing tables, `grandpa oops` context capture. [VERIFIED]
6. **Docstrings explain why**, often with the incident behind a rule. [VERIFIED]
7. Windows CI job runs the full deterministic suite; main is green for CI. [VERIFIED]

### 9.2 Bugs and risks (verified)

| # | Severity | Finding | Evidence |
|---|---|---|---|
| B1 | High | `autotag.yml` dispatches `desktop.yml`, which does not exist; "Auto-tag on main push" fails on every push (HTTP 422) after tagging and dispatching PyPI publish | Actions log of run on `fde2164`; `.github/workflows/` has no `desktop.yml` |
| B2 | Medium | Every push to `main` creates a `vX.Y.Z.devN` tag and dispatches `pypi-publish.yml`; confirm that publishing a dev build per push is intended | `autotag.yml` |
| B3 | Medium | `memory.db` has two independent writers/schemas (`memory/store.py` `memories`; `tools/storage/sqlite.py` `documents`) | both default to `DEFAULT_CONFIG_DIR / "memory.db"` |
| B4 | Medium | Several voice paths use `Path.home()/".Grandpa"` instead of `GRANDPA_HOME` (`speech/tamil_tts.py`, ElevenLabs cache, wake model default) – escapes the sandbox and differs from `~/.grandpa` on case-sensitive systems (the Linux headless node) | `rg '\.Grandpa' src` |
| B5 | Medium | Two TTS selection paths (`voice/speech_output.py` vs `ui/lipsync.py`) with different backend orders; ElevenLabs/Tamil only reachable through the avatar path | code |
| B6 | Low | `[speech] backend` comment advertises `openai`/`deepgram`; only `faster-whisper` is registered | `core/config.py`, `speech/` |
| B7 | Low | `cli/_tool_loop.py` docstring says the loop is "deliberately not wired into chat"; chat uses it by default since PR #16 | `cli/chat_cmd.py:1530` |
| B8 | Low | Odin dataset README says `"actions_covered": 167`; catalogue now has 174 actions | `scripts/odin/README.md` |
| B9 | Low (privacy) | `voice_runtime/diagnostics/user_path_before_ffmpeg.txt` is a tracked PATH dump containing a local Windows user path | file content (not reproduced) |
| B10 | Medium (test infra) | Full-suite run on Linux ends in an INTERNALERROR: `tests/verification_plugin.py` writes `runtime/verification/` at session end while a write guard is still armed (last test: `tests/voice/test_accuracy_confidence.py::test_the_report_states_what_the_sample_can_settle`), so pytest prints no summary and the commit guard gets no record. Reproduced twice; not seen in Windows CI | full-suite runs in this audit |
| B11 | Medium (test infra) | Order-dependent leak: a patched `importlib.import_module` from `tests/jarvis/test_voice_input.py` breaks ~2,775 later tests in a full Linux run | §9.7 |
| B12 | Low (dev UX) | Running pytest with `GRANDPA_HOME` exported (as the probe rules recommend for scripts) yields thousands of spurious guard errors; `tests/conftest.py` only `setdefault`s it | §9.7 |
| B13 | Medium | `pyproject.toml` declares `requires-python >= 3.10` and ruff targets `py310`, but `ui/bubble.py`, `ui/avatar_states.py` and `voice/cli_session.py` import `enum.StrEnum` (3.11+). CI runs 3.12 and the installer 3.11, so nothing tests 3.10 | `grep -rn "import StrEnum" src/grandpa`; `.github/workflows/ci.yml` `python-version: "3.12"` |
| B14 | Low | `scripts/oauth_all.py` (inherited) runs Google, Strava and Spotify OAuth and writes to `~/.grandpa/connectors` at import time, ignoring `GRANDPA_HOME`; Grandpa has no Strava or Spotify integration | `scripts/oauth_all.py` lines 1–25 |
| B15 | Low | Version base in `pyproject.toml` is `1.0.1` while tags go up to `v1.0.3`; autotag derives dev versions from the base | `git tag`, `.github/workflows/autotag.yml` |

### 9.3 Security issues

| # | Severity | Finding |
|---|---|---|
| S1 | High | No prompt-injection defence on untrusted text (screen OCR, web pages, mail bodies, MCP tool output) reaching the model; `security/injection_scanner.py` has no product caller. Mitigated (not solved) by confirmation on risky actions. |
| S2 | Medium | Two approval systems (inline callbacks vs staged codes in `pc_control`) – two policies to keep in sync. |
| S3 | Medium | The inherited `tools/shell_exec.py` (`shell=True`, confirmation required) remains reachable through the agents/tools path, outside the action catalogue that excludes `shell_run`. |
| S4 | Medium | `grandpa-guard` is registered as a "safety classifier for actions" but nothing calls it – risk of over-trusting it from docs. |
| S5 | Low | `file_move`/`file_rename`/`file_copy` are MEDIUM without confirmation; verify overwrite handling for model-initiated calls. |
| S6 | Low | ElevenLabs sends reply text to the cloud when a key is set (documented, opt-in). |

### 9.4 Architecture review

- Duplicate frameworks: `agent/` vs `agents/`; `planner/`, `agent/execution`, `workflow/`, `kernel/` planners;
  `memory_context` vs `memory/`; `screen_awareness.py` vs `screen/`; `engine/` vs `runtime/`; two `kernel` packages.
- 35 duplicate class names; heavy cycles (`pc_control`↔`desktop`, `cli`↔`voice`).
- Positive trend: the action layer (Oct–Nov 2026) is steadily replacing the legacy dispatch chains; voice operator
  and jarvis now route through it.

### 9.5 Code quality review

- `ruff check src tests`: **All checks passed**. [VERIFIED]
- Very large files (`action_layer/catalogue.py` 3.2k, `chat_cmd.py` 2.3k, `pc_control.py` 2k, `memory_context.py` 1.5k).
- ~1,005 broad `except Exception` handlers – often deliberate for resilience, but they hide bugs; prefer narrow
  exceptions in new code.
- Documentation drift: `docs/architecture/*` (Aug 2026) still names `local_actions.py`, `a2a/`, `oj_sk_` keys –
  all since changed; CONTRIBUTING excludes cloud providers/training pipelines that now exist; CONTRIBUTING and
  README disagree on the starter model.

### 9.6 Test coverage review

- 527 test files, 9,723 deterministic tests collected; CI Linux job runs an 18-file subset with
  `--cov-fail-under=20`; the Windows job runs the full deterministic suite and is green on `main`. [VERIFIED]
- Packages without their own `tests/<pkg>/` (notes, screen, vision, browser, gmail, calendar, downloads, files,
  apps) rely on flat `tests/test_*.py`; the commit guard therefore demands the full suite for them.
- Linux container run (Python 3.13, CI extras): see §9.7.

### 9.7 Full-suite run in this audit (Linux)

Command (CI extras installed, `GRANDPA_HOME` **unset**):
`uv run python -m pytest -q --timeout 120 -m "not live and not cloud and not microphone and not e2e" --junitxml=…`

| Outcome | Count |
|---|---|
| passed | 6,030 |
| failed | 703 |
| errors | 2,948 |
| skipped | 58 |
| total test cases | 9,739 |

How to read this (verified from the JUnit XML):

- **2,775 of the 2,948 errors are one cascade**, not 2,775 bugs: from some point in the run every package
  import fails with `ModuleNotFoundError` raised by `fake_import_module` in
  `tests/jarvis/test_voice_input.py` (it patches `importlib.import_module` globally via
  `monkeypatch.setattr(voice_input.importlib, "import_module", …)`). Running `tests/jarvis/test_voice_input.py`
  together with `tests/kernel` alone passes (162 passed), so the leak is order-dependent within the full run.
  Patching the module's own reference (or using `sys.modules` injection) would remove the global side effect.
- Most remaining failures are Windows-only paths on Linux (`pyautogui` halted, `PermissionError: denied` from
  OS-specific code), registry double-registration after the cascade, and guard refusals on teardown.
- The session then crashes in `tests/verification_plugin.py` (`pytest_sessionfinish` → `write_record` →
  `runtime/verification/` refused by a write guard left armed by the last test), so pytest prints no summary and
  exits 1 (B10).
- **The authoritative result is the Windows CI job, which is green on `fde2164`.** This Linux run is useful for
  isolation bugs, not as a product verdict.
- An earlier attempt with `GRANDPA_HOME` exported produced thousands of extra `ActuationDenied` errors, because
  `tests/conftest.py` rebinds `DEFAULT_CONFIG_DIR` to its own test home but only *defaults* `GRANDPA_HOME`. The
  testing skill now warns about this.

---

## 10. Missing features (relative to the GRANDPA vision)

1. Prompt-injection handling for untrusted perceived text (Critical for an assistant that reads screens and mail).
2. A consulted safety model or policy for model-initiated MEDIUM actions (guard role exists, unused).
3. A single memory facade with one owner per database.
4. Speaker-independent strong authentication for remote control beyond device tokens (e.g. per-device scopes) –
   *not* voice biometrics.
5. Hardware / IoT / home automation integration (no code yet).
6. Robotics (no code yet).
7. A `.env.example` / single reference of the ~100 `GRANDPA_*` variables.

---

## 11. Score

| Dimension | Score /10 |
|---|---|
| Functionality breadth | 8.5 |
| Safety & security design | 8.0 |
| Test infrastructure | 8.5 |
| Architecture / modularity | 5.0 |
| Code quality & maintainability | 6.5 |
| Documentation accuracy | 6.0 |
| CI/CD health | 6.5 |
| **Overall** | **7.0** |

---

## 12. Priority fix list

**Critical**
1. Decide and implement a prompt-injection policy for screen/web/mail/MCP text (wire or replace `injection_scanner.py`), with tests (S1).

**High**
2. Fix `autotag.yml` (remove the `desktop.yml` dispatch or add the workflow) and confirm per-push PyPI dev publishing is intended (B1, B2).
3. Give `memory.db` a single owner: move the RAG `documents` store to its own file with a backup-first migration (B3).
4. Route all voice/model paths through `GRANDPA_HOME` instead of `~/.Grandpa` (B4).
5. Decide the fate of `tools/shell_exec.py` on the agents path (S3).

**Medium**
6. Unify TTS backend selection (one ordered resolver used by CLI voice, bubble and avatar) (B5).
7. Either wire `grandpa-guard` into a clear decision point or mark it experimental in docs (S4).
8. Retire one approval mechanism or document precisely when each applies (S2).
9. Refresh `docs/architecture/*` and CONTRIBUTING to match the action-layer era (B7 and §9.5).
10. Fix the test-isolation issues seen on Linux: the session-end `verification_plugin` crash (B10), the global
    `importlib.import_module` patch leak (B11), and make `tests/conftest.py` override or reject a pre-set
    `GRANDPA_HOME` (B12).

11. Settle the Python floor: raise `requires-python` to 3.11, or add a `StrEnum` fallback and a 3.10 CI job (B13).

**Low**
12. Remove the tracked PATH dump (B9) and the stale STT backend comment (B6); regenerate the Odin dataset (B8).
13. Retire or fix `scripts/oauth_all.py` (B14) and align the version base with the tags before the next release (B15).
14. Add `.env.example`-style reference documentation for `GRANDPA_*` variables.

---

## 13. Roadmap

1. **Now (1–2 weeks):** items 1–4 above; adopt these skills; run `validate_skills.py` in CI (optional).
2. **Next (1 month):** memory consolidation; TTS resolver; doc refresh; engine→runtime import migration.
3. **Then (2–3 months):** retire `agent/` vs `agents/` duplication per `MIGRATION_PLAN.md`; split `catalogue.py` by
   domain; break `pc_control`↔`desktop` cycle.
4. **Future skills:** `grandpa-agents-planner` once one planner is chosen; `grandpa-avatar-ui` if the avatar grows;
   `grandpa-home-automation` / `grandpa-hardware` when IoT/robotics code exists; `grandpa-release` if releases get
   more frequent than the gate covers.

---

## 14. Installation and usage

See `GRANDPA_SKILLS_MASTER_INDEX.md` → *Installation*. In short: merge the branch; Claude Code picks up
`.claude/skills/*/SKILL.md` automatically inside the repo; invoke with `/grandpa-master-orchestrator` (or any skill
name) or just describe the task. Validate with
`python .claude/skills/grandpa-master-orchestrator/scripts/validate_skills.py`.

---

## 15. Next prompt to give Claude

> Use `/grandpa-master-orchestrator` and `/grandpa-security-governance`. Fix the autotag workflow (it dispatches a
> missing `desktop.yml`), then design a prompt-injection policy for text that comes from the screen, web pages,
> mail and MCP tools before it reaches the model. Start read-only, propose the design with the files you will touch
> and the tests that will prove it, and wait for my go-ahead before changing security behaviour.

---

## 16. Expansion to 19 skills (2026-11-25)

Captain supplied a 50-item candidate list for a "complete development skill
library" covering the whole lifecycle. Each candidate was evaluated for an
independent responsibility, overlap, and whether the work exists in this repo
now or only in a future phase.

**Decision (Captain chose the proposal):** 19 skills now, 2 named for later.

- **Kept (10):** the original set. `grandpa-dev-orchestrator` was renamed
  `grandpa-master-orchestrator` and now holds the shared project knowledge
  (`references/project-vision.md`, `references/roadmap.md` added).
- **Added (9):** `grandpa-product-planning`, `grandpa-architecture-design`,
  `grandpa-research-prototyping`, `grandpa-python-engineering`,
  `grandpa-agent-engineering`, `grandpa-desktop-ui`,
  `grandpa-external-integrations`, `grandpa-debugging-performance`,
  `grandpa-devops-release`. Each is grounded in real code and documents
  (paths cited inside each skill).
- **Future (2, not created):** `grandpa-smart-home-iot`,
  `grandpa-hardware-robotics`. No code exists for these areas; a skill now would
  be generic advice that Claude could not verify.
- **Not separate skills:** code review (Claude Code's built-in `/code-review`
  plus the security and testing skills), documentation (a step inside every
  skill, PRD/SRS in product planning), localization (agent and voice skills),
  backup and recovery (memory skill), accessibility (desktop UI).

Why not 50: Claude picks a skill by matching the request to each skill's
description. Many near-identical descriptions (voice, speech recognition,
speech synthesis, wake word, audio) make it choose wrongly or load several,
which costs tokens and gives conflicting guidance. The full mapping from each
candidate to its owner is in `GRANDPA_SKILLS_MASTER_INDEX.md`.

New findings recorded while writing the new skills: B13, B14, B15 (§9.2).
Validation: `validate_skills.py` → `PASSED: 19 skills validated`.
