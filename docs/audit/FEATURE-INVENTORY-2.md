# Grandpa Feature Inventory — second audit

Commit: `6b8f4a22` (`main`, immediately after Phase 1 merged)
Date: 2026-09-23
Python: 3.11.9 (`D:\Grandpa\.venv`)
OS: Windows 11 Home Single Language 10.0.26200

This is a fresh audit, not an update. The first audit's findings were re-derived
rather than carried forward, because the first audit called several things
WORKING that the e2e suite later proved were not — it called handlers directly
instead of running the CLI.

## 0. Method, and what is different this time

**Everything below that says WORKING was produced by running the CLI**, not by
importing a handler. The invocation is the same one the first audit used:

```
PYTHONPATH=<worktree>/src  D:/Grandpa/.venv/Scripts/python.exe \
    -c "from grandpa.cli import main; main()" <args>
```

**No side effects on the real machine.** The first audit disclosed that tracing
the chat chain launched Notepad and VS Code, wrote three screenshots, created a
note and a reminder in the user's own stores, and left a file in Downloads. This
audit ran every probe with `HOME`, `USERPROFILE` and `GRANDPA_HOME` pointed at a
throwaway directory — the same sandbox `tests/e2e/harness.py` uses — so a
command that writes wrote there. Nothing outside those sandboxes was created,
modified or deleted. No source file was changed; only this document was written.

Three instruments exist now that did not before, and this audit uses all three:

| Instrument | What it is | What it is worth here |
|---|---|---|
| `tests/e2e` (55 tests) | the real CLI as a subprocess in a sandbox, asserting on real effects | the only evidence that accepts "the feature works" |
| `scripts/verify_confirmation_enforcement.py` (6 probes) | end-to-end confirmation checks | proves refusals are real, not described |
| `tests/actuation_guard.py` + `tests/write_guard.py` | default-deny for actuation and for the filesystem | a probe that gets refused is evidence, not an obstacle |

**UNKNOWN is used where the evidence did not settle it.** A guess is not.

---

## 1. Test numbers, and what the three suites actually cover

| Suite | Collected | Covers |
|---|---|---|
| `python -m pytest -q` | **7039** (7094 − 55 deselected) | unit and integration, 403 test files across 35 directories. `tests/security/` is **584** of them |
| `python scripts/run_e2e.py` | **55** | the real CLI in a sandbox: 9 files, mostly confirmation behaviour and store round-trips |
| `scripts/verify_confirmation_enforcement.py` | 6 probes | non-interactive tool confirmation, `--yes`, agents, and chat synthetic input |

### 1.1 What e2e does *not* cover — this is finding N3

Of the **50 top-level CLI commands**, **21 are named anywhere in `tests/e2e`** and
**29 are not**:

> agent, apps, browser, doctor, gmail, init, launcher, operators, plan, profile,
> projects, quickstart, registry, restart, roadmap, scan, screen, self-update,
> serve, skill, speak, sprint, start, startup, stop, tray, vault, vision,
> voice-operator

That is not 29 broken features. It is 29 features whose only evidence is unit
tests that mock what the CLI does for real — which is precisely the class of
evidence the first audit was wrong about.

The e2e suite is also heavily weighted: of 55 tests, **20 are about
confirmation** (`test_confirmations`, `test_browser_confirmation`,
`test_deferred_consent`, `test_known_defects`). Phase 1's subject is well
covered. The rest of the product is thinly covered.

---

## 2. Feature table

Status vocabulary: **WORKING** (ran it, it did the thing), **PARTIAL** (ran it,
it did some of the thing), **PLACEHOLDER** (ran it, it reported success without
doing anything), **BROKEN**, **UNKNOWN**.

### 2.1 Verified by running the CLI in a sandbox

| Feature | Command | Status | Evidence |
|---|---|---|---|
| Notes | `notes list` | WORKING | `exit=0`, "No notes found." in a clean sandbox; e2e covers create/append/list/search/delete |
| Reminders (store) | `reminders list` | WORKING | `exit=0`; e2e `test_reminders_add_persists_a_future_reminder_that_list_shows` |
| Memory | `memory list` | WORKING | `exit=0`; e2e `test_memory_remember_stores_a_row_that_search_returns` |
| Downloads | `downloads recent` | WORKING | `exit=0`; e2e covers recent/search/delete |
| Scheduler (store) | `scheduler list` | WORKING | `exit=0`; e2e `test_scheduler_create_list_cancel_round_trip_through_the_store` |
| Telemetry | `telemetry stats` | WORKING | `exit=0`, renders an empty overview |
| Doctor | `doctor` | WORKING | `exit=0`, renders the full dashboard |
| Projects | `projects list` | WORKING | `exit=0`, lists the registered project |
| Operators | `operators list` | WORKING | `exit=0`, lists 3 built-in operators |
| Tools | `tool list` | WORKING | `exit=0`, renders the registered tool table |
| Vault | `vault list` | WORKING | `exit=0`, "Vault is empty." |
| Config | `config show` | WORKING | `exit=0` |
| Registry | `registry list/show` | WORKING | `exit=0` |
| Plan | `plan --help` | UNKNOWN | the group exists with 5 subcommands; not executed (needs a model) |
| Roadmap | `roadmap --help` | UNKNOWN | 7 subcommands exist; not executed |
| Screen / Vision | `screen --help`, `vision --help` | UNKNOWN | groups exist; every subcommand reads the live screen, so a sandbox cannot settle them |
| **Apps** | `apps list` | **PARTIAL** | `exit=0` but: *"The application cache is missing or outdated. Run `grandpa apps refresh`."* A first-run user gets no list |
| **Skills** | `skill list` | **BROKEN** | `exit=0`, "No skills installed." — with **18 manifests shipped** in `src/grandpa/skills/data/`. Finding N1 |
| **Jarvis** | `jarvis "what time is it"` | **BROKEN** | `exit=1`, *"I don't know how to route that Jarvis command yet… Try: open my Grandpa project in VS Code"*. Same for "open notepad" |

### 2.2 Chat slash commands

36 are declared in `cli/slash_commands.py` and `validate_command_registry()`
returns no problems. Six were run through `chat` with piped input; all six
produced output and exited 0. But two of the six answer with text instead of
behaviour:

* `/mode` → *"Mode switching is a safe placeholder for now."*
* `/git` → *"Git commit and push actions require explicit user approval."* —
  informational, not a git action.

`/help`, `/doctor`, `/permissions` and `/compact` did real work. The first
audit's "ten slash commands do nothing" is **not** what I observed; what I
observed is that at least one is a self-described placeholder. The other 30 were
not individually exercised — **UNKNOWN**, and that is finding N3 again.

---

## 3. Decides-from-content: the Phase 1 pattern, searched for everywhere

Phase 1's dominant defect was **something that decides what may happen taking
its answer from content, from a default nobody set, or from a path nobody
checked**. Four shapes were searched across all 620 modules.

### 3.1 Shape A — a name from data selects the code that runs

40 sites use `getattr`/`import_module`/`eval`/`exec` with a non-literal. Almost
all are framework plumbing where the name comes from the codebase, not from a
caller. **Four take the name from data that a caller or a store supplies:**

| Site | What it dispatches on | Verdict |
|---|---|---|
| `browser_awareness/analyzer.py:27` | `getattr(self, f"_handle_{action.action}", None)` | Bounded: `action.action` comes from a parsed enum-like set, and a miss returns `None`. **Safe, but it is the shape** |
| `gmail/automation.py:170` | `getattr(self.client, action.action, None)` | Same shape against a network client. A new action name reaches any attribute of the client object |
| `projects/service.py:231` | `getattr(daemon_cmd, action, None)` | Same shape against a command module |
| `agents/rlm_repl.py:120` | `importlib.import_module(mod_name)` from REPL input | Bounded by an import allowlist; `repl` is confirmation-gated since Phase 1 |

**None is currently exploitable** — each is bounded by an allowlist, an enum, or
a `None` default. All four are one careless addition away from the `_pc_action`
hole, and none has a test pinning the bound.

### 3.2 Shape B — a decision value read from the thing being judged

Only **four** hits, all in `agent/development/`:
`models.py:71`, `roadmap_generator.py:643`, `:678`, `sprint.py:49` — each
`risk_level=data.get("risk_level", ...)` read out of stored JSON.

**It gates nothing.** `agent/development/planner.py:118-127` computes a
`risk_level` and the only consumer is a string in a work-package summary
(`planner.py:232`). So this is a *third* risk vocabulary that decides nothing,
alongside the catalogue's tiers and the planner's own Low/Medium/High. Finding
N5.

That Phase 1's fixes hold is visible here: the search finds **no** site where a
risk, an approval flag or a permission that *does* gate something is read from
the payload.

**How far that goes.** It is a pattern search over single statements. A decision
assembled across several — read into a local on one line, passed through a
helper, used in a branch three functions away — would not be caught, and
`_pc_action`'s original hole *would* have been caught only because it happened
to be one expression. So this is evidence that the obvious form is gone, not
proof that the shape is. A dataflow check, or an `origin` field that the audit
record carries end to end (see §7, N-open), is what would settle it.

### 3.3 Shape C — a default that permits when unconfigured

The two that mattered (`file_read`/`file_write` `allowed_dirs`) are fixed. What
the scan finds now is a different, larger thing: **five subsystems ship
disabled**, and one of them is the security mechanism.

| Config | Default | Consequence |
|---|---|---|
| `CapabilitiesConfig.enabled` | **False** | RBAC is off, `capability_policy` is `None`, and every `required_capabilities` declaration on every tool is inert. **Fails open.** Finding N2 |
| `SchedulerConfig.enabled` | False | `system/builder.py:401` returns early, so nothing runs due reminders on a default install |
| `WorkflowConfig.enabled` | False | — |
| `SessionConfig.enabled` | False | — |
| `OperatorsConfig.enabled` | False | `operators list` shows three operators that never run |

The rest of the shape-C hits are `or []` on display strings — benign.

### 3.4 Shape D — a path built from caller content

No hits that reach a write. `file_write`, `file_read` and `text_to_speech` are
bounded as of Phase 1; `skill_manage` is confirmation-gated.

### 3.5 The one Phase 1 introduced

**All 18 bundled skill manifests are refused by Phase 1's own provenance gate.**
`SkillManager.discover()` will not load a manifest that does not declare
`provenance`, and none of the 18 in `src/grandpa/skills/data/` declares it —
though `TRUSTED_PROVENANCE` contains `"bundled"` precisely for them. Verified by
pointing `discover()` at that directory: 18 on disk, **0 loaded, 18 skipped**.

It changes nothing a user sees *today*, because those manifests were already
unreachable (finding N1: the directory is not on the search path). But it means
fixing N1 would not work. Finding N4.

---

## 4. First audit's 14 open findings, re-checked

| # | Finding | Now | Evidence |
|---|---|---|---|
| 5 | `skill list` never finds the skills | **STILL OPEN** | 18 manifests in `skills/data/`; `_get_skill_paths()` (`cli/skill_cmd.py:17-24`) returns only `./skills` and `~/.grandpa/skills/`. `skill list` → "No skills installed." |
| 8 | Volume/brightness/clipboard/process have no entry point | **MOSTLY CLOSED** | Two different entry paths, checked separately. Through `handle_local_action`: `list processes`, `what process is active` and `clipboard history` all route (`handled`). Through chat's desktop route (`DesktopParser`): `set volume to 30` → `volume_set`, `mute` → `volume_mute`. **Brightness reaches neither** — `set brightness to 50` and `increase brightness` are `no_match` in both. `kill notepad` is `no_match` and `process_kill` is not catalogued |
| 9 | `jarvis` understands one command | **STILL OPEN** | Ran it: two different phrases both refused, with the same hint naming the single supported intent |
| 11 | Reminders never fire on a default install | **STILL OPEN**, cause identified | `SchedulerConfig.enabled = False` (`config.py:713`) → `system/builder.py:401` returns before constructing the scheduler |
| 12 | One-shot reminders become daily | **STILL OPEN**, documented in-source | `task_scheduler.py:411` states it: *"remind me to X at 5pm" is read … as `daily:17:00` — a reminder that repeats every day, not once* |
| 13 | Planner invents application names | UNKNOWN | Not re-derived; needs a model-backed run |
| 15 | `python -m grandpa` does not work | **STILL OPEN** | `src/grandpa/__main__.py` still absent |
| 17 | `file_assistant` misroutes clipboard requests | **NOT REPRODUCED** | `clipboard history` and `inspect clipboard` route to `clipboard_history`/`clipboard_inspect` under `pc_control`. `copy this` and `what is in my clipboard` are `no_match`, so they fall through to the assistant rather than to the file handler. The reported symptom — a file named `clipboard` created in Downloads — did not recur. Whether the exact original phrase still does is UNKNOWN |
| 20 | Symlink-escape tests skip on Windows | **STILL OPEN** | 3 `pytest.skip("symlinks are unavailable")` sites in `tests/kernel/` |
| 22 | MCP has no CLI surface | **STILL OPEN** | No `mcp` in the 50 commands; no `cli/mcp_cmd.py` |
| 23 | Ten slash commands do nothing | **RE-CHARACTERISED** | 36 declared, registry validates clean, 6 sampled all responded. At least `/mode` is a self-described placeholder. "Do nothing" is not what I observed; "some answer with text instead of behaviour" is |
| 24 | Default TTS needs an unstartable sidecar | **CHANGED, still not usable** | Default `tts.backend` is now `kokoro` (in-process, `pip install kokoro`), not the f5 sidecar. But `import kokoro` → `ModuleNotFoundError` in this venv, so the default backend is still unavailable out of the box |
| 25 | Browser page reading needs a foreground browser | **STILL OPEN, now deliberate** | `browser_control.py:645-648` says so explicitly: *"The active title is authoritative. Never substitute an unrelated background browser."* It is a safety decision now, not an accident |
| 28 | Assorted smaller defects | **PARTLY OPEN** | Three tool modules (`browser_axtree`, `knowledge_sql`, `scan_chunks`) each declare `@ToolRegistry.register` but are absent from `_BUILTINS`, so they never load. The first audit said five; it is three |

Also still true, and **not** what finding 28 claimed was fixed: `model` and
`models` both remain as separate top-level groups.

---

## 5. Orphaned code

**5 modules** of 620 are imported by nothing else in `src` and referenced by no
string:

| Module | Note |
|---|---|
| `cli/_chat_banner.py` | 1 KB |
| `security/subprocess_sandbox.py` | 4.5 KB — a sandbox nothing uses |
| `tools/browser_axtree.py` | registers a tool that never loads |
| `tools/knowledge_sql.py` | registers a tool that never loads |
| `tools/scan_chunks.py` | registers a tool that never loads |

This is much smaller than the first audit's list; `881c5c9a` removed most of it.

## 6. Duplicate implementations

The six desktop stacks (first audit finding 18) are still six directories:
`automation/`, `desktop/`, `pc_control.py`, `screen_awareness.py`, `vision/`,
`windows_window_control.py`. What changed in Phase 1 is the *routes into* them —
chat, voice operator, the desktop runtime skills and agent_plan now all enter
through `action_layer.executor`. The duplication is now behind one door rather
than five.

---

## 7. Findings, ranked

| # | Finding | Severity | Evidence |
|---|---|---|---|
| **N1** | **18 shipped skills are unreachable.** `skill list` reports "No skills installed" on a clean install because the bundled directory is not on the search path | **High** — the entire skills library is dead weight | `cli/skill_cmd.py:17-24` vs `skills/data/*.toml` |
| **N2** | **RBAC fails open and is off by default.** Every `required_capabilities` on every tool is inert | **High** — a declared control that does nothing is worse than none, because it reads as protection | `config.py:624`, `tools/_stubs.py:154` |
| **N3** | **29 of 50 CLI commands have no e2e coverage**, including `serve`, `skill`, `vault`, `scan`, `screen` and `vision` | **High** — this is the exact gap that made the first audit wrong | §1.1 |
| **N4** | **Phase 1's provenance gate refuses all 18 bundled manifests**, which `TRUSTED_PROVENANCE` has a `"bundled"` value for | **Medium** — latent; blocks the fix for N1 | §3.5, verified |
| **N5** | **A third risk vocabulary that gates nothing** in `agent/development/`, read from stored JSON | **Medium** — the shape that produced Phase 1's worst hole, currently harmless | §3.2 |
| **N6** | **Four `getattr`-from-data dispatch sites** with no test pinning their bounds | **Medium** | §3.1 |
| **N7** | **Four subsystems ship disabled** (scheduler, workflow, session, operators), and `operators list` advertises three operators that cannot run | **Medium** | §3.3 |
| **N8** | `apps list` tells a first-run user to run `apps refresh` instead of doing it | **Low** | ran it |
| **N11** | **Brightness has no entry point at all** — catalogued, but `no_match` through both the local router and the chat desktop parser | **Low** | §4, finding 8 |
| **N9** | Three tool modules register tools that never load | **Low** | §5 |
| **N10** | `model` and `models` are still two groups | **Low** | `--help` |

---

## 8. What this audit could not settle

* Everything needing a live model (`plan`, `roadmap`, `sprint`, `project`,
  `agent`), because a sandboxed run has no Ollama guarantee.
* `screen`, `vision` and `voice-operator`, which read the live screen or
  microphone — a sandbox cannot make those deterministic, and running them for
  real would change the machine, which this audit does not do.
* 30 of the 36 slash commands.
* First-audit findings 13 and 17, which need a model-backed chat run.

These are marked UNKNOWN above rather than guessed.
