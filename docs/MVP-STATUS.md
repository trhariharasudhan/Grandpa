# MVP status

The state of the nine MVP items on 2026-10-07, at commit `a18177c1` plus the
branch this document is written on. No scores, no plan — what is there, what is
not, and what someone else would walk into.

Every claim below was checked by running something. Where a claim could not be
checked without a live microphone, a running daemon or a second machine, it says
so instead of asserting. Where re-checking disagreed with
[`docs/audit/FEATURE-INVENTORY.md`](audit/FEATURE-INVENTORY.md), the disagreement
is recorded in [§3](#3-open-findings-from-the-inventory) rather than quietly
resolved — that document is dated 2026-09-23 and a fortnight of work has landed
since.

## How this was verified

```
pytest -q                                     7799 passed, 88 skipped,
                                              3 xfailed, 0 failed (21m08s)
python scripts/run_e2e.py                     66 passed, 0 failed (240s)
scripts/verify_confirmation_enforcement.py    5 PASS, 0 FAIL, 1 SKIP
grandpa --help                                50 listed; 52 in cli.commands
grandpa doctor                                read in full
grandpa skill list / jarvis / reminders list / memory --help / status
python -m grandpa  and  python -m grandpa.cli
ollama list                                   15 models
load_config() and load_voice_assistant_config() read field by field
grandpa.action_layer.catalogue.CATALOGUE       167 ActionSpec entries
grandpa.cli.slash_commands.SLASH_COMMANDS      36 entries, `implemented` flag read
```

Test counts by area, from one collection pass:

| area | tests | area | tests | area | tests |
|---|---|---|---|---|---|
| action_layer | 1844 | kernel | 150 | learning | 99 |
| security | 641 | ui | 143 | engine | 66 |
| cli | 623 | core | 138 | sdk | 58 |
| tools | 600 | speech | 136 | desktop | 53 |
| skills | 316 | mcp | 127 | traces | 52 |
| agents | 300 | memory | 125 | runtime | 47 |
| voice | 208 | server | 115 | hardware | 47 |

---

## 1. What each item does today

### Core

Config loads into a `GrandpaConfig` of 28 sections. `GRANDPA_HOME` is honoured
for every stateful path — verified by pointing it at a scratch directory and
seeing `memory.db` and `audit.db` follow. 138 core tests plus 150 kernel tests.

**Unfinished behind it:** `grandpa doctor` reports `Config file: Not found …
Run 'Grandpa init'` on a home that has never been initialised, which is correct
but means a fresh checkout answers questions from defaults rather than from a
config.

### AI engine

`engine.default = "ollama"`, and doctor reports it **Reachable**. Embedding model
and vision model both report Ready. `intelligence` carries temperature 0.7,
top_k 40, top_p 0.9, repetition_penalty 1.08, max_tokens 1024.

**Unfinished behind it:** the native (GGUF) engine is configured-but-absent —
doctor lists `Engine: native → Not configured`, `Native GGUF models → No GGUF
files found`. That is an optional second engine, not a broken one.

### Local LLM

Ollama holds 15 models. The configured default `grandpa-brain:latest` is
**present** (5.2 GB) and doctor's tick for it is accurate — checked against the
full `ollama list`, because the first screen of it does not include the model and
reading only that screen would have produced a false finding here.

Also present: `grandpa-mini`, `-light`, `-fast`, `-classic`, `-general`,
`-heavy`, `-guard`, `-eyes`, plus `qwen2.5:0.5b`, `qwen`, `gemma3:4b`.

**Unfinished behind it:** `intelligence.fallback_model` is empty, so there is no
second choice if the default is missing. `intelligence.provider` is `"local"`
with `preferred_engine` empty.

### Tools

600 tool tests. `tools.mcp.enabled = True`, browser headless, sqlite storage.

**Unfinished behind it:** MCP is enabled in config and has 127 tests, but there
is **no `mcp` command** in the CLI — confirmed by checking `cli.commands`. The
capability exists and cannot be driven from the terminal.

### Windows agent

The action layer is the largest single area of the project: **167 catalogued
actions** across named domains, 1844 tests. `volume_*` (6 actions),
`brightness_get/set`, `clipboard_clear/history/inspect/read/write`,
`system_lock/shutdown/restart`, `screen_describe`, window and app actions are all
catalogued with real implementations bound through `Binding.REQUEST_ACTION`.

**Unfinished behind it:** `process_kill` is not catalogued at all (only
`active_process` and `list_processes`). Whether a spoken or typed *phrase*
reaches the catalogued brightness and clipboard actions was **not verified
here** — the catalogue entry and the implementation path were, the phrase
resolver was not.

### Memory

sqlite backend, `memory.db` under `GRANDPA_HOME`, chunk size 512 / overlap 64,
context top-k 5, max 2048 tokens. Doctor reports `Memory database ready`.
`grandpa memory` exposes a working command group. 125 tests.

Recall is now measured rather than assumed — `grandpa memory recall-test`,
half a second against a throwaway database:

| Questions | recall@1 | recall@3 | MRR |
| --- | --- | --- | --- |
| direct wording (12) | 100% | 100% | 100% |
| paraphrased (12) | 25% | 33% | 33% |

**Unfinished behind it:** `context_min_score` is 0.0, so retrieval applies no
relevance floor — every top-k hit is eligible regardless of score. That is
the same defect the recall numbers show from the other side: the FTS query is
OR-joined with no stopword filtering, so "what vehicle do I drive" matches
every fact containing "I" and returns *a* fact rather than none. Memory never
says it does not know.

### CLI

`cli.commands` holds 52 entries; `grandpa --help` prints 50 of them (`_bootstrap` is internal and `agent` is hidden). 623 tests. 36 slash commands
inside the interactive surface, of which the module's own `implemented` flag
marks **35 as implemented** and one (`/tasks`) as "Planned / Partially
available".

**Known broken:** `python -m grandpa` fails with *"No module named
grandpa.__main__"* — there is no `src/grandpa/__main__.py`.
`python -m grandpa.cli --version` works and prints `Grandpa, version 1.0.1`.

`grandpa jarvis` is the sharpest edge in the CLI: see §1 of
[§4](#4-what-someone-else-hits-first).

### Voice

Push-to-talk works end to end and is the recommended path: the key is the only
gate, with the detector configured to refuse nothing. STT is faster-whisper
`base.en`; doctor reports `Voice runtime backend Ready … faster_whisper; output:
pyttsx3`. `grandpa voice accuracy-test` measures word error rate against fixed
phrases. 208 voice + 136 speech tests.

**Known broken / unfinished:**

- **Two TTS defaults disagree.** `load_config().tts.backend` is `"kokoro"`;
  `load_voice_assistant_config().tts_engine` resolves to `"pyttsx3"`, which is
  also what doctor reports. Both were read in the same process. Which one is
  authoritative is not settled by the code.
- Transcription accuracy on this machine is the standing open question that
  `accuracy-test` exists to answer, and it has not been answered: the two live
  runs attempted so far were both abandoned at the first phrase. base.en versus
  small.en is **unsettled**.
- `grandpa_voice.character_voice` is read only by
  `voice_runtime/scripts/run_service.py`, outside `src/`.

### Desktop UI

`grandpa bubble` — a borderless, always-on-top tkinter window that never takes
focus, with a global hold-to-talk key, a text box, a reply pane and a status
line. The toolkit is injected, so 143 UI tests run without opening a window, a
microphone or a speaker. The hold path is verified end to end through
`PushToTalkSession.record_while_held` and the real stop event:
`recording → transcribing → thinking → idle`.

**Known broken / unfinished:**

- **Nothing in the bubble has been confirmed by eye.** Every claim about it
  rests on injected-toolkit tests and the manual QA document
  (`docs/testing/desktop-ui-manual-qa.md`), which has not been walked through on
  a real screen. The two bugs reported from it so far — a space typed into the
  text box, and a header that read "hold SPACE" after the default became F9 —
  were both invisible to the suite at the time.
- The F9 default carries one untested cost: on a laptop whose F-row defaults to
  media keys, F9 may need `Fn`, and the probe would never see it. `--key f8` and
  `--key shift` are the documented fallbacks.

---

## 2. State of the test suite

**7799 passed, 88 skipped, 3 xfailed, 0 failed** in 21m08s, with 66
deselected (the `e2e` marker, run separately).

Three guards are armed by default and are part of why the counts mean anything:

- **actuation guard** — default-deny over catalogued implementations and
  low-level primitives, including the audio arm.
- **write guard** — nothing writes outside the test's own scratch space without
  `@pytest.mark.real_writes`.
- **host-state guard** — the foreground window and the action cooldown are
  pinned, so the suite no longer reads the developer's desktop.

A commit is refused unless a full pytest run passed against exactly that tree,
so the last pytest invocation before a commit must be the whole suite.

The e2e suite runs separately and is currently **66 passed, 0 failed, 0 skipped
in 240s**.

**Known flake, not a failure:** that same suite intermittently reports two
`subprocess.TimeoutExpired` failures in `test_downloads_*`. It did so on the
previous run, which took 1145s against 306s for the one before it, with DNS
failing throughout; all nine downloads tests passed in isolation in 29s. The
240s run above passed those two tests with no change made to them, which is what
settles this as host I/O variance -- measured earlier in this project as a
105× swing on identical work -- rather than a defect in the tests. The timeouts
have deliberately not been raised.

---

## 3. Open findings from the inventory

The inventory closed 11 and deferred 2 of its 28, leaving 14 open. Re-checked
today:

| # | Finding | Checked today |
|---|---|---|
| 5 | `skill list` never finds the 43 skills | **No longer reproduces.** It lists **18** bundled skills (`backup-files` … `web-summarize`). The figure 43 is not reproducible either: there is no `skills/` tree at the repository root. |
| 8 | Volume/brightness/clipboard/process control have no entry point | **Partly closed, as the inventory already noted.** All are catalogued with real implementations; `process_kill` is still absent entirely. Phrase reachability not verified. |
| 9 | `grandpa jarvis` understands one command | **Confirmed, and it is exact.** 0 of 8 ordinary phrases routed. |
| 11 | Reminders never fire on a default install | **Confirmed, mechanism found, fixed.** `scheduler.enabled` is False by default *and* the tick marked anything more than 10 minutes overdue `failed` without delivering it. So a reminder arrived only if `run-due` ran inside a ten-minute window. Late reminders are now delivered with their lateness in the text. |
| 12 | One-shot reminders become daily | **Not reproduced.** One-shot and recurring are separate stores and the routing was fixed earlier; what was still broken was that `cancel` and `clear --all` only ever acted on the one-shot store, so a recurring reminder could be listed and never cancelled by anything. Both now act on both. |
| 13 | Planner invents application names | **Not verified.** |
| 15 | `python -m grandpa` does not work | **Confirmed.** No `src/grandpa/__main__.py`. |
| 17 | `file_assistant` misroutes clipboard requests | **Not verified.** |
| 20 | Symlink-escape tests skip on Windows | **Not verified.** The full run skips 88 tests; the inventory lists each skip and its reason in its own §1.1, and those reasons were not re-read one by one here. |
| 22 | MCP has no CLI surface | **Confirmed.** No `mcp` command, while `tools.mcp.enabled` is `True` and 127 MCP tests pass. |
| 23 | Ten slash commands do nothing | **No longer reproduces.** 35 of 36 are flagged `implemented`; only `/tasks` is marked planned. |
| 24 | Default TTS needs an unstartable sidecar | **Changed, not closed.** The voice path resolves `pyttsx3` and doctor reports it Ready; `config.tts.backend` is still `kokoro`. The two disagree. Whether audio reaches a speaker was not verified -- the audio guard forbids opening one. |
| 25 | Browser page reading needs a foreground browser | **Not verified.** |
| 28 | Assorted smaller defects | **Not verified** individually. |

Deferred, unchanged: **18** six parallel desktop-control stacks, **19** the
`desktop/kernel/*` circular layer.

Also still open from [`docs/audit/DEFERRED.md`](audit/DEFERRED.md):
`security/subprocess_sandbox.py` is imported by nothing while `shell_exec` and
`code_interpreter` call `subprocess.run` directly; `intelligence.top_p` and
`repetition_penalty` are declared but not sent to Ollama; and
`web_search/duckduckgo.py` monkey-patches two methods of `ddgs` 9.11.4 at runtime
to stop result text being glued together, with a test that skips itself once
upstream is fixed.

---

## 4. What someone else hits first

In the order they would actually hit it.

1. **Running the test suite against the wrong source tree.** The venv's
   installed `grandpa` resolves to `D:\Grandpa\src` — the main checkout — so in a
   worktree, `pytest` silently tests the *other* tree unless `PYTHONPATH` points
   at this one. Nothing warns.

2. **Setting `GRANDPA_HOME` before running pytest.** It looks like the careful
   thing to do and it breaks 154 tests, because the suite sets up its own home
   and the write guard then refuses the path. Observed today, exactly that count.
   `GRANDPA_HOME` is for *probes*, never for pytest.

3. **Asking memory something in your own words.** Direct recall is 100% and
   paraphrased recall is 25%, and the failure is silent — it returns the
   nearest keyword match, not nothing. `grandpa memory recall-test` is the
   measurement.

4. **`grandpa jarvis`.** It is advertised in `--help` as "Route Jarvis-style safe
   local commands", accepts any phrase, and answers *"I don't know how to route
   that Jarvis command yet"* to all of: open notepad, set volume to 30, lock the
   screen, what is the time, take a screenshot, scroll down, close the window,
   mute the volume. The suggestion it offers reveals the one phrase it does
   understand: *"open my Grandpa project in VS Code"*. Meanwhile 167 of those
   actions are catalogued and reachable elsewhere.

5. **Deciding which TTS default is real.** `kokoro` in core config, `pyttsx3` on
   the voice path.

6. **`python -m grandpa`**, which is the obvious way to run a Python package and
   is the one that does not work.

7. **Six desktop-control stacks.** Four of the *routes* into them were removed,
   so the action layer is the way in; the stacks are still six, and a change to
   desktop behaviour has to establish which one is live.

8. **Nothing in the bubble has been seen working by a human.** Both bugs
   reported against it were in the class the suite could not see — a rendered
   string and a focus interaction. `docs/testing/desktop-ui-manual-qa.md` is
   fifteen checks and is unwalked.

9. **The commit guard.** A commit is refused unless the last pytest invocation
   was a full run against that exact tree. Discovering this mid-commit, after a
   targeted run, costs a 25-minute round trip.
