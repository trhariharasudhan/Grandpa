# Grandpa Feature Inventory

Commit: `7371e3573a34d42f274f19856488e30a0756f0db` (identical content on `main` and on the
audit worktree branch `claude/grandpa-feature-audit-d130c5`)
Date: 2026-09-10
Python: 3.11.14 (`D:\Grandpa\.venv`, the venv with Grandpa installed; the machine's bare
`python` is 3.12.10 and does **not** have Grandpa importable)
OS: Windows 11 Home Single Language 10.0.26200

> **Status annotation, 2026-09-11.** The audit below describes the code at `7371e357` and is
> left as written. §6 now opens with a status table. The commits since then:
>
> - `bacffe0b`: findings 1, 7 and 6. For 6 the premise was corrected: the chat path was a
>   dead end, not a bypass.
> - `b6376c14`: findings 2, 4, 14 and 27. It also removed the false scroll messages in 10,
>   and the phantom agent names and `emergency_stop_placeholder` in 28. Its commit message
>   says it fixes 10, but the other browser stubs remain, so 10 stays OPEN.
> - `9485cb8f`: hardening for 1 and 7. NUL stdin on Windows had counted as a TTY.
> - `c0f5ab47`: `scripts/verify_confirmation_enforcement.py`, an end-to-end probe for 1 and 7.
> - `881c5c9a`: findings 16 and 21. It also removed 16 of the 19 keys in 26, and in 28 the
>   duplicate `models` group and most §3.1 modules.
> - `20d02f6b`: the rest of 26. `intelligence.top_p` and `repetition_penalty` now reach Ollama.
>   `grandpa_voice.character_voice` was kept because
>   `voice_runtime/scripts/run_service.py` reads it.
> - `24b320e4`: synced the Rust `grandpa-core` config with the keys removed for 26.
>
> Found after the audit and fixed:
>
> - `6105e9e3`: `agents ask` ticks failed because builtin agents were never loaded.
> - `e07853dc`: ten agent CLI commands exited 0 on failure.
> - `6d0a6380`: the voice processor's own "yes" block is dead code. A spoken "yes" still
>   works through `local_actions`. This is pinned by a test; the code was not changed.

## 0. How this audit was run (and one correction to the brief)

`python -m grandpa --help` **does not work**, for two separate reasons:

1. `src/grandpa/__main__.py` does not exist. `python -m grandpa` fails with
   `No module named grandpa.__main__; 'grandpa' is a package and cannot be directly executed`.
   (`src/grandpa/cli/__main__.py` does exist, so `python -m grandpa.cli` works — the
   `startup` command already registers `python.exe -m grandpa.cli start`, visible in
   `grandpa startup status` output.)
2. The bare `python` on PATH (3.12.10) has no `grandpa` installed at all.

Per the brief, all CLI invocations in this report were therefore run as:

```
PYTHONPATH=<worktree>/src  D:/Grandpa/.venv/Scripts/python.exe -c "from grandpa.cli import main; main()" <args>
```

`PYTHONPATH` was verified to shadow the editable install so that the worktree's source —
not `D:\Grandpa\src` — was the code under test. The two are at the same commit and the main
checkout is clean.

**Side effects caused by this audit (disclosure).** Tracing the chat dispatch chain
required calling the real handlers, which perform real side effects. The following actually
happened on this machine: Notepad and VS Code were launched, the Downloads folder was opened
in Explorer, three screenshots were written to `~/.grandpa/screenshots/`, a note named
`ideas` was created (twice — see finding 28), a reminder `call mom` was written to
`~/.grandpa/scheduler.db`, memories ("favorite color is blue", "birthday is may 1") were
written to the memory store, and a file `C:\Users\ASUS\Downloads\clipboard` was created by
the file-assistant handler (finding 17). No source file was modified. Only
`docs/audit/FEATURE-INVENTORY.md` was written.

---

## 1. Test Suite Result

```
4726 passed, 70 skipped, 3 xfailed, 247 warnings in 770.42s (0:12:50)
```

| Metric | Value |
|---|---|
| passed | 4726 |
| failed | **0** |
| errors | **0** |
| skipped | 70 |
| xfailed | 3 |
| runtime | 770.42 s (12 m 50 s) |

There are **no failing tests**. Every finding below is invisible to this suite.

### 1.1 Every skip, with reason

| Count | Test | Skip reason | Hides a real hole? |
|---|---|---|---|
| 1 | `tests/server/test_optional_research_router.py:33` | "Research dependencies are installed in this environment." | **YES — the reason is false.** There is no `/api/research` route at all (`POST /api/research` → 404). The test asserts 503 and skips on anything else, so a 404 from a route that was never written reads as "feature present". See finding 2. |
| 5 | `tests/skills/test_integration_live.py` | "live skill integration tests require a running inference engine and installed user skills" | **YES.** Ollama *is* running on this box; the real blocker is that zero skills are installed and `grandpa skill list` can never find any (finding 5). |
| 4 | `tests/cli/test_voice_cmd.py:381,398`, `tests/cli/test_voice_operator_cmd.py:13,23` | "requires microphone/audio hardware; set `GRANDPA_RUN_MICROPHONE_TESTS=1`" | Partly. The mic hardware is present and `grandpa voice diagnose` passes; the end-to-end voice loop is untested on a machine where it could be tested. |
| 8 | `tests/memory/test_retrieval_quality.py:41` | `could not import 'grandpa.tools.storage.bm25': No module named 'grandpa_rust'` | Yes — BM25 retrieval quality is entirely unverified because the Rust extension is not built. |
| 9 | `tests/memory/test_storage_suite.py:22` | same (`grandpa_rust` missing) | Same. |
| 4 | `tests/core/test_rust_bridge.py` | "grandpa_rust extension is not built" | Yes — the whole Rust bridge is untested. |
| 1 | `tests/security/test_setup_security.py:45` | "Rust extension not compiled" | Yes. |
| 2 | `tests/memory/test_storage_suite.py:99,107` | "Rust BM25Memory PyO3 bindings do not expose delete()/clear()" | Yes — a known API gap, permanently skipped rather than tracked. |
| 2 | `tests/memory/test_storage_suite.py:175,183` | "HybridMemory sub-backend BM25 lacks delete()/clear()" | Same gap, one layer up. |
| 3 | `tests/memory/test_storage_suite.py:39` | `faiss is required for FAISSMemory` | Optional extra not installed. |
| 3 | `tests/memory/test_storage_suite.py:45` | `PyTorch is required for the ColBERT memory backend` | Optional extra not installed. |
| 1 | `tests/memory/test_bm25.py:7` | `No module named 'rank_bm25'` | Optional extra. |
| 1 | `tests/memory/test_colbert.py:7` | `No module named 'colbert'` | Optional extra. |
| 1 | `tests/memory/test_embeddings.py:7` | `No module named 'sentence_transformers'` | Optional extra. |
| 1 | `tests/memory/test_faiss.py:7` | `No module named 'faiss'` | Optional extra. |
| 1 | `tests/connectors/test_embedding_store.py:12` | "torch required for embedding tests" | Optional extra. |
| 2 | `tests/connectors/test_retriever.py:228,282` | "torch required for embedding tests" | Optional extra. |
| 1 | `tests/cli/test_vault_cmd.py:41` | `No module named 'cryptography'` | **Yes.** `grandpa vault set/get` is untested because its crypto dependency is not installed by default. |
| 7 | `tests/security/test_signing.py:12` | "cryptography not installed" | Yes — artifact signing is entirely unverified. |
| 6 | `tests/security/test_file_permissions.py:22,32,40,54,64,75` | "POSIX chmod mode-bit assertions are not meaningful on Windows." | **Yes, for a Windows-first product.** File-permission hardening has no Windows-side equivalent test; on the target OS these assertions simply do not run. |
| 1 | `tests/core/test_credentials.py` | "POSIX chmod mode assertions are not reliable on Windows" | Same — credential-file permission hardening is unverified on the target OS. |
| 3 | `tests/kernel/test_file_copy_migration.py:437`, `test_file_create_folder_migration.py:342`, `test_file_properties_migration.py:96` | "symlinks are unavailable: `[WinError 1314] A required privilege is not held`" | **Yes.** These are the *symlink-escape* security tests. On an unprivileged Windows account — the normal case — the tests proving path-traversal-via-symlink is blocked do not run. |
| 2 | `tests/hardware/test_hardware_profiles.py:96,101` | "Requires macOS" / "Requires Linux" | Legitimate. |
| 1 | `tests/tools/test_shell_exec.py:210` | "POSIX shell variable syntax" | Legitimate. |

### 1.2 The 3 xfails

All three are the same parametrised strict xfail in `tests/test_browser_redaction.py:200-211`
— a deliberately-strict xfail documenting a browser redaction case that is not yet handled,
written so it "fails loudly once that lands". This is the healthiest pattern in the suite.

---

## 2. Feature Table

The command surface is **37 command groups / 297 leaf commands**. The three real entry
points for natural-language capability are `grandpa chat`, `grandpa voice`, and
`grandpa jarvis`. Most subsystems are only reachable through the `chat` dispatch chain at
`src/grandpa/cli/chat_cmd.py:1702-1941`, which tries handlers in this fixed order:

`notes → downloads → web_search → memory → calendar → gmail → browser_awareness → browser → desktop.automation → local_actions → file_assistant → task_scheduler → datetime → LLM fallback`

Evidence marked "probe" comes from replaying that exact chain against literal user phrases.

### 2.1 Conversation and inference

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Interactive text chat | `grandpa chat` | WORKING | `cli/chat_cmd.py:1236`; ran `printf 'what time is it\nexit\n' \| … chat` → banner + "It is 7:04 PM." + clean exit | `tests/cli/` chat tests pass | — |
| One-shot ask | `grandpa ask` | WORKING | `cli/ask.py:586`; ran `ask --no-stream "Reply with exactly the word PONG…"` → `PONG` | passing | — |
| Local LLM via Ollama | `ask`/`chat` → `engine/ollama.py` | WORKING | `curl localhost:11434/api/tags` → `grandpa-mini:latest` (qwen2.5:0.5b); real generation confirmed above | passing | — |
| Research mode | `grandpa ask --research` | **BROKEN** | `cli/ask.py:54` imports `grandpa.agents.research_loop`, **which does not exist** (`ls src/grandpa/agents/` — no such file; the only reference in the repo is this import). Ran it: unhandled `ModuleNotFoundError` traceback shown to the user. | none | The entire module. Also unguarded — the user gets a raw traceback. |
| Research HTTP route | `POST /api/research` | **BROKEN** | Route does not exist; `TestClient(create_app(...)).post('/api/research')` → 404, and `[r.path for r in app.routes if 'research' in r.path]` → `[]`. Test at `tests/server/test_optional_research_router.py:33` skips instead of failing. | skip-hidden | The route. |
| Slash commands in chat | `/…` in `grandpa chat` | PARTIAL | `cli/slash_commands.py`; 36 commands registered, **10 have `routing="help"`** — they print help and perform no action: `/mode /tasks /desktop /system /coding /git /github /voice /order /automation` | passing (they test that help prints) | Real handlers for 10 of 36 visible commands. |
| Identity / persona prompt | `prompt/identity.py`, `prompt/builder.py` | WORKING | `cli/chat_cmd.py:1647`; deterministic identity answers at `voice/assistant.py:89-106` | passing | — |

### 2.2 Voice

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Voice assistant loop | `grandpa voice` (bare group, `invoke_without_command=True`) | PARTIAL | `cli/voice_cmd.py:37,89,118-142` → `voice/cli_session.py:152` → `voice/assistant.py:60`. `grandpa voice diagnose` → 13 input devices, faster-whisper `base` int8, pyttsx3 ready — 20 checks, all PASS/WARN. | **skipped** (`tests/cli/test_voice_cmd.py:381,398`) | End-to-end loop never exercised. Command coverage is limited by the same NL parsers as chat (§2.4). |
| Voice diagnostics | `grandpa voice doctor/diagnose/devices/microphone-test/set-device/test` | WORKING | ran `voice diagnose`: all checks PASS/WARN, no errors | passing | — |
| Wake word | `grandpa voice --wake-word` | UNKNOWN | `voice/wake_word.py`, `voice/cli_session.py:215-268` exist and are wired; not exercised — would require speaking into the mic, which this audit did not do | unit tests pass | Real-hardware verification. |
| Voice operator mode | `grandpa voice-operator` | UNKNOWN | `cli/voice_operator_cmd.py` → `voice/operator.py:823-852`; not run (needs mic) | **skipped** (`tests/cli/test_voice_operator_cmd.py:13,23`) | Real-hardware verification. |
| Speak text | `grandpa speak` | PARTIAL | `cli/speak_cmd.py:22` → `voice/speech_output.py`. `speak --dry-run hello` → "Speech output queued safely." Non-dry-run not executed (would make noise). | passing | Audible output unverified in this audit. |
| Cloned / "grandpa_voice" TTS | config `tts.backend = grandpa_voice` (default) | PARTIAL | `voice diagnose` → `WARN cloned voice service: Unavailable at http://127.0.0.1:8765; pyttsx3 fallback remains available (URLError)`. The service is `voice_service/service.py:25` but **no `grandpa` command starts it** — the only launchers are out-of-band: `voice_runtime/scripts/start_service.ps1`, `run_service.py`. | 1 test file | A CLI command to start/stop the sidecar. The default backend silently degrades to pyttsx3. |
| Jarvis voice one-shot | `grandpa jarvis --voice` | PARTIAL | `cli/jarvis_cmd.py:43-60` — real STT capture, but routes into the router in §2.3 which understands one intent | passing | See below. |

### 2.3 Jarvis routing

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Jarvis command routing | `grandpa jarvis "<text>"` | **PARTIAL, near-empty** | `jarvis/intent_router.py:38-95`. The router recognises **exactly one intent**: "open `<project>` in vscode" (`_parse_open_project` at `:99-104`; `APP_ALIASES` at `:30-35` maps only VS Code). Verified: `jarvis --dry-run "open my Grandpa project in vscode"` → routed; `"shut down the computer"`, `"delete my downloads folder"`, `"turn up the volume"` → all exit 1 with *"I don't know how to route that Jarvis command yet. Try: open my Grandpa project in VS Code"*. | passing | Everything except opening a project in VS Code. `pc_control` behind it supports ~60 action types (`pc_control.py:54-131`); the Jarvis router can emit exactly one (`open_app`). |

### 2.4 Local system control

Reached from `chat`/`voice` via `desktop/automation.py` then `local_actions.py`.
"probe" = literal phrase run through the real dispatch chain.

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Open an app | chat "open notepad" / "open vs code" | WORKING | probe → `desktop` handler `[handled] Notepad opened.` / `VS Code opened.`; both really launched. `desktop/automation.py`, `apps/launcher.py` | passing | — |
| App inventory / scan | `grandpa apps scan/list/find/running/search` | WORKING | `apps find notepad` → real WindowsApps path; `apps running --limit 3` → live process list | passing | — |
| Lock PC | chat "lock the computer" | WORKING | probe → `[handled] PC locked.`; `desktop/automation.py:234-259` → `pc_control` `system_lock` (LOW risk, `pc_control.py:90`) | passing | — |
| Shutdown / restart / sleep | chat "shut down the computer" | **BROKEN (dead-end approval)** | probe → `[needs_confirmation] Approval required before running system_shutdown on shutdown.` plus console line `Approval code: A20A89C0 (expires in 300s)`. Follow-up "yes": `local_actions.handle_local_action('yes')` → *"There is no pending local action to approve."*; `handle_desktop_command('yes')` → no match. `chat_cmd.py:1865` calls `handle_desktop_command(text)` **without** the `confirm=` callback the function accepts (`desktop/automation.py:324-335`). | passing (tests approve programmatically, never through a CLI) | Any way for a terminal user to redeem the approval code. Redemption exists only at `pc_control.approve_local_action` (`pc_control.py:342`), exposed **only** over HTTP (`/api/local-action/{id}/approve`). No CLI command anywhere calls it. |
| Empty recycle bin | chat "empty the recycle bin" | **BROKEN (same dead end)** | probe → `[needs_confirmation]` + approval code; unredeemable | passing | Same as above. |
| Close an app | chat "close notepad" | PARTIAL | probe → `[error] Notepad did not close. It may be waiting for a save prompt.` — real attempt, honest failure report | passing | — |
| Window list / focus / min / max | chat "list open windows" | WORKING | probe → real window titles (Claude, Notepad, Media Player, Chrome, cmd); `local_actions.py:1818-1830` → `windows_window_control.py` | passing | — |
| Volume: mute / unmute / set N | chat "mute" / "set volume to 50" | PARTIAL | Parser at `desktop/automation.py:222-232` accepts only the literal strings `mute`, `mute sound`, `mute volume`, `unmute…`, and `(set )?volume( to)? N(%)` | passing | Broader phrasing. |
| Volume: up / down | *none* | **ORPHANED** | `volume_up`/`volume_down` are declared LOW-risk actions (`pc_control.py:59-60`) and safe automations (`desktop_automation.py:58-64`), but **no parser anywhere emits them**. Probe "turn up the volume" → no handler claimed it → falls through to the LLM. Grep for producers finds only the risk tables and a key-map, never a caller. | none | Any NL or CLI route to volume up/down. |
| Brightness get / set | *none* | **ORPHANED** | `brightness_get`/`brightness_set` at `pc_control.py:64-65`; `grep -rn brightness src` outside `pc_control.py` and `desktop/control/` returns **zero** hits. Probe "set brightness to 50" → no handler. | none | Everything above the action constant. |
| Clipboard read / write / history | *none from chat* | **ORPHANED** | `clipboard_read/write/clear/inspect/history` at `pc_control.py:66-70`; probe "what is in my clipboard" → no handler. Only reachable as the runtime skill `desktop.clipboard_history`, which is itself unreachable (§2.10). | none end-to-end | An NL parser or CLI command. |
| List / kill processes | chat "kill chrome" | **ORPHANED / absent** | Probe → no handler. `local_actions.py:1067-1068` maps only the literal phrases "list processes"/"show running processes". There is **no kill-process action at all** in `pc_control.py`'s tables. `security/subprocess_sandbox.py:62 kill_process_tree` exists but only reaps the sandbox's own children. | n/a | Process termination is not implemented, despite being implied by "local system control". |
| Screenshot | chat "take a screenshot" | WORKING | probe → `[handled] Screenshot saved to C:\Users\ASUS\.grandpa\screenshots\screen-20260910-185329.png` (file really written) | passing | — |
| Software install | chat "install python" | **ORPHANED / absent** | Probe → no handler. No install action exists in any risk table. | n/a | Not implemented. |
| Registry / system settings change | *none* | **ORPHANED / absent** | No registry-write action exists in any risk table. `desktop/control/registry.py` is an app-profile registry, not the Windows registry. | n/a | Not implemented (arguably correct — but the stated product scope implies otherwise). |

### 2.5 Screen awareness and vision

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Monitor / window enumeration | `grandpa screen monitors/windows/active` | WORKING | ran all three; `screen active` → real foreground window + `Size: 1550 x 878` | passing | — |
| Screen capture | `grandpa screen capture`, `vision screenshot` | WORKING | `screen/capture.py`; screenshot files written during probes | passing | — |
| OCR read | `grandpa screen read`, `vision read` | WORKING | `vision read` returned real on-screen text | passing | — |
| Screen describe | `grandpa screen describe`, chat "what is on my screen" | WORKING | probe → `Active window: … / Screenshot: … / Visible UI: 0 buttons, 0 fields, 26 labels` | passing | — |
| UI element graph (UIA) | `grandpa vision inspect/graph/controls/buttons/find/highlight` | WORKING | `vision inspect` → `Elements: 611 (UIA=ready, OCR=ready)`; `vision controls` listed real controls | passing | — |
| Screen diagnostics | `grandpa screen diagnose --json` | WORKING | ran, exit 0 | passing | — |

### 2.6 Safe automation (synthetic input)

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Locate a control by text | `grandpa automation locate <text>` | WORKING | ran `automation locate ok` → *"Found … at (627, 568) with 84% confidence"* — real OCR/UIA match on the live screen | passing | — |
| Click / type / press / scroll / focus / move | `grandpa automation click\|type\|press\|scroll\|focus\|move` | WORKING | `cli/automation_cmd.py:15-34` — plans, prints, then requires `click.confirm("Continue?", default=False)` unless `--yes`; enforced at `automation/service.py:123` | passing | — |
| Automation session REPL | `grandpa automation session` | WORKING | ran; started and stopped cleanly | passing | — |
| Typing / pressing / scrolling via chat | chat "type hello", "press enter", "scroll down" | PARTIAL | `local_actions.py:1115-1224` → `desktop_automation.execute_automation` (`local_actions.py:1805-1813`) | passing | Hardcoded literal phrases only; **no confirm callback is passed from chat**, so `_CONFIRM_REQUIRED_ACTIONS` (`desktop_automation.py:37-45`) is bypassed — finding 6. |
| "Click the highlighted button" | chat | **STUB** | `local_actions.py:1216-1224` returns `status="handled"` with the message *"Clicking highlighted buttons is not enabled yet."* — a stub reported to the user as a handled action | passing | The implementation. |
| Emergency stop | — | PARTIAL | `pc_control.py:50,460,485` is a real global kill switch; `desktop_automation.py:154 emergency_stop_placeholder` is a separate, named-as-placeholder stub also exported in `__all__` (`:381`) | passing | Remove or implement the placeholder. |

### 2.7 Browser

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Read the visible page (title/URL/DOM) | `grandpa browser page/analyze/extract/debug` | PARTIAL | Real UIA implementation (`browser_control.py:193-274`, `:790 _extract_uia_dom_context`). **But `_find_visible_browser_window` (`:683-731`) only inspects the *foreground* window** and explicitly refuses to substitute a background browser (comment at `:700-701`). Running `browser debug` from a terminal always reports `Browser Detected: None` — verified with 7 Edge processes running. | passing (with injected contexts) | Any way to use this from a terminal. It can only work when invoked by voice while a browser is in front. |
| Session history / context | `grandpa browser history/context` | WORKING | `browser_intelligence/session_memory.py:11,34-53` persists to `~/.grandpa/browser_session_state.json`; ran → 286 verified pages, real prior FastAPI visits | passing | — |
| Open URL / search / new tab | chat "open google.com", "search youtube for X" | WORKING | `browser_control.py:484-524` → real `webbrowser.open()`. Probe "open google.com" → `[handled] google.com opened.` | passing | — |
| Click / back / forward / reload / focus-search | *no entry point* | **STUB** | `browser_control.py:530-545`: these actions **always** return `requires_confirmation`, and nothing in the repository ever completes them. Probe "click the sign in button", "go back in the browser" → no handler claims them at all. | passing (asserts the confirmation string) | The actual implementations. |
| Scroll the page | — | **BROKEN** | `"scroll"` is not handled by `execute_browser_action` at all → falls to the catch-all at `browser_control.py:545` (*"That browser action is not supported yet."*). Yet `browser_intelligence/navigator.py:82-88` returns `message=f"Scrolled page towards heading '{target_val}'."` and `:111-117` returns *"Scrolled 5 times, heading … not yet visible."* — **both report a scroll that never happened.** | none for the false message | Implementation, or honest reporting. |
| Form fill / download | — | **STUB** | `browser_control.py:436-475` — always `requires_confirmation`, never completed | passing | Implementation. |
| Research mode | `grandpa browser research <topic>` | PARTIAL | `browser_intelligence/research_mode.py`; depends on `SmartNavigator` scroll/click (which do nothing) and on `read_current_browser_page` (which needs a foreground browser) | passing | Real navigation. |
| Compare / verify / summarize | `grandpa browser compare/verify/summarize` | PARTIAL | `browser_intelligence/{comparison_engine,source_verifier,summarizer}.py` — real logic, but all consume `read_current_browser_page()`, unavailable from a terminal | passing | Same foreground constraint. |
| Raw-HTML page read | `read_current_browser_page(html_content=…)` | PARTIAL | `browser_intelligence/page_reader.py:260` hardcodes `url = "https://localhost/page"` for every HTML input, so domain-trust verification of HTML-sourced pages is meaningless | passing | Real URL propagation. |

### 2.8 Files, downloads, notes

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Find files | chat "find files named report" | WORKING | probe → `[handled] No matching files found.` (real search) | passing | — |
| Rename / move | chat "rename X to Y", "move X to documents" | WORKING | probe → `[error] I could not find test.txt.` (real lookup, honest failure) | passing | — |
| Create a file | chat "create a file called test.txt on my desktop" | **ORPHANED** | Probe → **no handler claimed it**; falls to the LLM. `file_create` is a declared LOW-risk action (`pc_control.py:77`) and `files/executor.py` implements creation, but no NL parser routes to it. | passing at unit level | An NL route. |
| Delete a file | chat "delete test.txt from my desktop" | PARTIAL (safe) | probe → `local_actions` `[blocked] I blocked this action for safety.`; `file_delete` is HIGH risk (`pc_control.py:116`), `file_permanent_delete` is BLOCKED (`:123`) | passing | A working approved-delete path (blocked by the same dead-end approval flow). |
| "copy this to clipboard" | chat | **BROKEN** | Probe → `file_assistant` `[handled] File copied to C:\Users\ASUS\Downloads\clipboard.` It read a clipboard request as a file copy and **created a junk file**. Reproduced on this machine. | none | Intent disambiguation; this misfire writes to disk. |
| Downloads: list/recent/today/large/incomplete/duplicates/search/info | `grandpa downloads …` | WORKING | all ran with real data (e.g. `OllamaSetup.exe — installer, 1.2 GB … [unsafe to open]`) | passing | — |
| Downloads: latest | `grandpa downloads latest` | PARTIAL | ran → *"Opened download: WhatsApp Ptt … .ogg"* — a read-sounding command that **opens a file** with no prompt | passing | A less surprising name, or a prompt. |
| Downloads: organize / delete / archive | `grandpa downloads organize\|delete\|archive` | WORKING | `cli/downloads_cmd.py:52,61,72`; verified `downloads delete <x>` without `--yes` → interactive `Delete 0 downloads (0 B)? [y/N]`. Path confinement at `downloads/safety.py:27-46`. | passing | — |
| Notes: create/list/search/append/pin/rename/archive/restore/open | `grandpa notes …` | WORKING | ran; chat probe "create a note called ideas" → `[handled] Note created` | passing | — |
| Notes: delete | `grandpa notes delete` | WORKING | verified prompt `Delete note "…"? [y/N]` without `--yes` | passing | — |
| Note de-duplication | — | PARTIAL | `notes list` shows two entries both named `ideas` with different timestamps — creating a note by an existing name duplicates it rather than erroring or appending | passing | Uniqueness handling. |
| `notes/search.py` | — | **ORPHANED** | Imported by nothing in `src/` (every module checked). `cli/notes_cmd.py` search uses a different path. | n/a | — |

### 2.9 Memory and knowledge

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Remember / recall in chat | chat "remember that…", "what is my favorite color" | WORKING | `memory_context.handle_memory_command`, wired at `cli/chat_cmd.py:1763`. Verified round trip: stored "my favorite color is blue", then "what is my favorite color" → *"Your favorite color is blue."* | passing | — |
| Memory CLI | `grandpa memory list/show/search/recent/relevant/explain/stats/projects/preferences/remember/update/delete/clear` | WORKING | all ran with real data (32 local memories, topic clustering) | passing | — |
| Memory index | `grandpa memory index <path>` | UNKNOWN | `cli/memory_cmd.py` → `tools/storage/*`. Not exercised (would write an index). The default BM25 backend needs `grandpa_rust`, which is **not built** on this machine. | **skipped** (17 tests) | Verification; the Rust extension. |
| Semantic / FAISS / ColBERT / BM25 backends | `memory search --backend …` | UNKNOWN | `tools/storage/{bm25,faiss_backend,colbert_backend,dense,hybrid}.py`; `faiss`, `torch`, `rank_bm25`, `sentence_transformers`, `grandpa_rust` are all absent | **skipped** (19 tests) | Optional deps and/or a compiled Rust extension. Nothing verifies these on a default install. |
| Knowledge engine v1 storage | `knowledge/storage.py` | PARTIAL | `knowledge/storage.py:131-134` writes `embeddings_placeholder = {"status": "not_built", "reason": "Knowledge v1 uses deterministic keyword retrieval; embeddings are planned."}` for every document — the column exists, real vectors do not | 1 test file | Real embeddings in the v1 store. |
| Knowledge engine v2 embeddings | `knowledge/embeddings.py` | PARTIAL (honest) | `knowledge/embeddings.py:15-17,40` — Ollama `nomic-embed-text` first, deterministic-hash fallback with an explicit `true_semantic: bool` flag. Honest about degradation. | 1 test file | Only reachable via runtime skills and the HTTP API — no CLI. |
| Memory recovery | `memory_recovery.py` | UNKNOWN | imported by `chat_cmd`, `memory/store.py`, `memory_context.py`; not exercised here | 1 test file | — |

### 2.10 Skills and tools

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Skills CLI (filesystem skills) | `grandpa skill list/info/run/remove` | **BROKEN in practice** | `cli/skill_cmd.py:16-27` searches only `./skills` and `~/.grandpa/skills/`. Neither exists and **the repo ships no skills**. Ran `skill list` → *"No skills installed."* | 5 live tests **skipped** | Any shipped skill, or a bridge to the runtime registry below. |
| Runtime skill registry (43 skills) | *no CLI* | **ORPHANED** | `skills/registry/defaults.py` (1272 lines) registers **43 real skills** across browser/desktop/memory/knowledge/coding/vision/planner/automation — verified by calling `ensure_default_skills_registered(); list_skills()` → 43 entries including `desktop.keyboard_type`, `browser.download_plan`, `knowledge.semantic_search`. **`grandpa skill list` cannot see any of them** — it uses `SkillManager`, an entirely separate system. The registry is reached only from `agents/goal_mode.py:21`, `agents/runtime.py:11`, `mcp/bridge.py:11`, `planner/engine.py:326`, `router/skill_router.py:135`, `services/skill_service.py` and `local_actions.py:2009`. | ~4 test files | A CLI (or chat) surface. 1272 lines of working code the product cannot expose. |
| Empty skill sub-packages | — | **STUB** | `skills/{automation,browser,communication,desktop,memory,system,vision}/__init__.py` are each **exactly one line** — a docstring, no code. E.g. `skills/desktop/__init__.py` is `"""Runtime skill wrappers for desktop and PC-control capabilities."""` and nothing else. (`skills/security/` does not exist at all.) | none | Everything. Delete or implement. |
| Tool registry / list / inspect | `grandpa tool list/inspect` | WORKING | ran → 30 registered tools | passing | — |
| Tool execution (agent loop) | `ask --tools …`, `agents ask` | WORKING | Verified directly: `ToolExecutor([shell_exec], interactive=True, confirm_callback=lambda p: True).execute(...)` → `success=True`, stdout `AUDIT_B` | passing | — |
| Tool confirmation default | `ToolExecutor` | WORKING (safe default) | `tools/_stubs.py:209-221` — with no callback, a `requires_confirmation` tool is **refused**. Verified: `success=False`, *"requires confirmation but no confirmation callback is available."* | passing | — |
| Tools never registered | — | **ORPHANED** | `tools/__init__.py:11-34 _BUILTINS` omits `browser`, `browser_axtree`, `knowledge_search`, `knowledge_sql`, `scan_chunks`, so those modules are never imported, their `@ToolRegistry.register` decorators never run, and the tools are never dispatchable. | some unit tests | Registration. |
| Skill builder | `skill_builder/` | UNKNOWN | Reached only from `services/skill_service.py` and the HTTP API; no CLI | some tests | A CLI surface. |

### 2.11 Web, mail, calendar

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Web search (CLI + chat) | `grandpa search web/news/official/recent`, chat "search the web for X" | **BROKEN out of the box** | `web_search/client.py:36,44` supports only `brave`/`bing`/`serper`, all API-key-gated. Ran `search status` → *"Web search is not configured. Set BRAVE_SEARCH_API_KEY."* Probe "search the web for fastapi" → `[not_configured]`. | passing | A keyless provider — even though one already ships (next row). |
| Web search (agent tool) | `ask --tools web_search` | WORKING | `tools/web_search.py:118-123` uses `ddgs` (DuckDuckGo, **no key**; `ddgs>=9.11.4` is a *hard* dependency at `pyproject.toml:28`). Verified live: real FastAPI results returned. | passing | Nothing — but the CLI reaches the *other*, broken implementation. |
| Gmail | `grandpa gmail setup/status/inbox/unread/read/search/labels/summarize/disconnect` | UNKNOWN (not configured) | ran `gmail status` → *"Gmail is not configured. Place OAuth client secret at …\gmail_client_secret.json."* Clean and honest. Optional `[gmail]` extra. | unit tests pass | Credentials; cannot verify without them. Note it is **read-only** — there is no send command, so "sending messages" is not a capability here. |
| Calendar | `grandpa calendar setup/status/today/…/create/update/delete` | UNKNOWN (not configured) | `calendar status` → same clean message. `calendar/safety.py:29 requires_confirmation` gates create/update/delete and the CLI has `--yes` on all three. | unit tests pass | Credentials. |

### 2.12 Reminders, routines, scheduling

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Reminders CLI | `grandpa reminders add/create/list/cancel/clear/run-due` | PARTIAL | `reminders.py:21` → `~/.grandpa/reminders.db`. Ran `reminders list --all`: one reminder, `drink water`, status **`failed`**. | passing | See delivery, below. |
| Reminder delivery | `reminders run-due`, server daemon | **BROKEN** | `reminders.py:70-102 WindowsToastNotifier` requires `winotify`, which is **not installed** (`importlib.util.find_spec('winotify')` → `None`) and is only in the optional `windows-notifications` extra (`pyproject.toml:90`). This matches the `failed` reminder in the live DB. | passing (the notifier is mocked) | A default-installed notification backend, or a visible fallback. |
| Reminder scheduling loop | — | PARTIAL | `scheduler_daemon.BackgroundSchedulerDaemon` is instantiated **only** at `server/app.py:108-111`. If the user never runs `grandpa serve`/`grandpa start`, no reminder ever fires. Nothing else calls `run_due`. | passing | A standalone reminder daemon, or docs saying the server is required. |
| Reminders via chat | chat "remind me to call mom at 5pm" | PARTIAL (wrong semantics) | Probe → `[handled] Reminder set: call mom (daily at 17:00).` The user asked for **one** reminder and got a **daily recurring** one. `task_scheduler.py:660-675` has only `minutely`/`hourly`/`daily:HH:MM` — there is no one-shot branch. It also writes to `~/.grandpa/scheduler.db` (`task_scheduler.py:21`), a **different database** from `reminders.db`, so `grandpa reminders list` will never show it. | passing | One-shot reminders; a single store. |
| Routines | chat "run my work setup routine" | PARTIAL | `task_scheduler.py:490-503`; a `work setup` routine is auto-created on demand | passing | Only allowlisted `open X` steps (`SAFE_ROUTINE_ACTIONS`). |
| Scheduler CLI | `grandpa scheduler create/list/logs/pause/resume/cancel/run-task/start` | PARTIAL | `scheduler list` → *"No scheduled tasks found."* This is a **third** scheduler (`scheduler/scheduler.py`, `scheduler/store.py`) driving agent tasks, unrelated to the two above. | passing | — |
| `scheduler/tools.py` | — | **ORPHANED** | Imported by nothing in `src/`. | n/a | — |

### 2.13 Agents, planning, autonomous development

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| Agent management | `grandpa agents list/create/info/delete/start/stop/pause/resume/status/logs/messages/tasks/templates/watch/trace/errors/learning/recover/search/launch/daemon` | WORKING | all read commands ran; `agents status` showed a real registered agent ("My Assistant") | passing | — |
| Ask an agent | `grandpa agents ask <id> <msg>` | WORKING but **unsafe by default** | `cli/agent_cmd.py:640-668` — `--yes/--no-yes` defaults to **`True`**, installing `executor._confirm_callback = lambda _prompt: True` (`:664`). Finding 7. | passing | — |
| Builtin agents | `--agent simple\|orchestrator\|native_react\|react\|rlm\|operative\|monitor_operative` | WORKING | `agents/__init__.py:38-48` dynamic registration verified: `AgentRegistry.keys()` → all 7. (`_BUILTINS` also lists `react` and `monitor`, which are **not files** — silently swallowed by the `ImportError` handler at `:46-47`.) | passing | Remove the two phantom names. |
| Agent Runtime V1 | `grandpa agent run/preview/inspect/diagnose/validate/status/report/trace/rollback/cancel` | PARTIAL | `agent preview "add a docstring to src/grandpa/profile.py"` → the entire plan is *"1. Process general goal: add a docstring to src/grandpa/profile.py [Tool: planner]"* — a literal echo of the goal, not a decomposition. `agent trace` → *"Recommended next action: proceed with task 'None'"*. | passing | Real decomposition for goals outside the template catalog. |
| Agent patch review | `grandpa agent patch preview/show/approve/reject/apply` | WORKING (by design) | `agent/execution/approval.py:51-160` rejects placeholder/fabricated proposals; `patch_builder.py:60-79` rejects comment-only/empty diffs. `agent patch preview` → *"No pending patch proposals."* | passing | Not exercised end-to-end here. |
| Planner | `grandpa plan create/preview/execute/list/show/status/graph/trace/pause/resume/retry/cancel/clarify/dump` | PARTIAL, with a real bug | Templates work: `plan preview "open chrome and search for fastapi"` → 4 correct steps. **Off-template it silently mis-parses**: `plan preview "open notepad and type hello"` → one step, *"Open Notepad And Type Hello"*, because `_single_step` (`planner/decomposer.py:480-489`) matches `open ([\w .+-]+)` greedily and sets `app = "notepad and type hello"`. Risk is reported **"Low"** and the plan is executable. | passing | Reject or re-plan unmatched goals instead of inventing an app name. |
| Local-model planner | `plan create --local-model` | UNKNOWN | `planner/decomposer.py:353-440` — a real Ollama JSON planner; not exercised | passing | Verification. |
| Sprint runner | `grandpa sprint start/preview/status/report/validate/pause/resume/cancel/checkpoint` | PARTIAL | `sprint preview` → *"Sprint preview created successfully."*; `sprint validate` → *"All validation checks passed."*; `sprint status` → *"No active sprint found."* `sprint start` requires `--approve` or an interactive prompt (`cli/sprint_cmd.py:75-84`). | passing | Not exercised end-to-end. |
| Project / roadmap | `grandpa project …`, `grandpa roadmap …` | WORKING (as a tracker) | `roadmap show/milestones/tasks/validate/graph` all returned real persisted roadmap data; `roadmap validate` → *"No circular dependencies, orphan tasks, or invalid references."* | passing | — |
| Dev projects | `grandpa projects discover/register/list/show/start/stop/restart/test/logs/open/status/unregister` | WORKING | `projects list --json` → `[]` (none registered); destructive ops carry `--yes` | passing | — |
| Goal mode | `agents/goal_mode.py` | UNKNOWN | reachable via the HTTP API (`/v1/agent/goals`) and `agents` internals; no direct CLI | some tests | A CLI surface. |

### 2.14 Server, daemon, integration surfaces

| Feature | Entry point | Status | Evidence (file:line) | Test coverage | What's missing |
|---|---|---|---|---|---|
| API server | `grandpa serve` / `grandpa start` | WORKING | `create_app()` builds **179 routes**; `grandpa status` → *"Server is not running."* correctly | passing | — |
| Approval REST API | `/api/local-action/{id}/approve`, `/v1/approvals/{id}/approve` | WORKING | `server/approval_routes.py:58`, `server/routes.py:1279` | passing | It is the **only** approval redemption path in the product (finding 3). |
| Auth middleware | `serve --no-auth`, `--allow-insecure-bind` | UNKNOWN | `server/auth_middleware.py`; the insecure options are opt-in flags and explicit | passing | Not exercised here. |
| MCP server/client/bridge | *no CLI* | **ORPHANED from the CLI** | `mcp/server.py`, `mcp/bridge.py`. `mcp.bridge` is imported only by `mcp/__init__.py` and has **zero** test files. MCP is reachable only via `system/builder.py` and the HTTP `/v1/mcp` routes. There is no `grandpa mcp` command. | 12 test files (server/client) | A CLI surface for a headline integration. |
| A2A (agent-to-agent) | *nothing* | **ORPHANED** | `a2a/{client,server,protocol,tool}.py` — the only importers of any `a2a` module are **other `a2a` modules**. `config.a2a.enabled` exists and is read nowhere outside `core/config.py`. | 1 test file | Any consumer at all. |
| Operators | `grandpa operators list/install/activate/deactivate/pause/resume/run/info/logs` | PARTIAL | `operators list` returns an empty table; the manifests dir defaults to `~/.grandpa/operators` (`core/config.py:711`) and nothing ships. `config.operators.auto_activate` is read by nothing. | some tests | Any shipped operator. |
| Workflows | `grandpa workflow list/run/status` | **BROKEN — fake** | `cli/workflow_cmd.py:20,46` import `discover_workflows` from `grandpa.workflow.loader`, **which does not define it** (`loader.py:84`: `__all__ = ["load_workflow"]`). Verified: `ImportError: cannot import name 'discover_workflows'`. Both commands catch `ImportError` and print *"No workflows found."* / *"Workflow system not available."*, so `workflow list` can **never** list anything. `workflow run` at `:52-56` prints *"Workflow 'X' started."* then *"Note: Full workflow execution requires a running system."* — it **never executes anything**, and the source comment at `:53` says so: `# Full execution would need a GrandpaSystem — just report for now`. `workflow status` (`:63-67`) is a hardcoded string. | **zero** tests for `workflow/loader.py` | `discover_workflows`; actual execution. `workflow/engine.py` (a real graph executor) is unreachable from the CLI. |
| Windows startup | `grandpa startup enable/disable/status` | WORKING | `startup status` → real registered command `…python.exe -m grandpa.cli start` | passing | — |
| System tray | `grandpa tray` | UNKNOWN | `tray.py` → `cli/tray_cmd.py`; not run (spawns a GUI) | 1 test file | Verification. |
| Doctor | `grandpa doctor --json` | WORKING | ran, exit 0, structured output | passing | — |
| Config | `grandpa config show loaded/json/toml/hardware`, `config set` | WORKING | all ran; `config show hardware` → *"Recommended Model: grandpa-mini:latest"* | passing | 19 dead keys — see §5 / finding 26. |
| Vault | `grandpa vault set/get/list/remove` | UNKNOWN | `vault list` → *"Vault is empty."*; the write path needs `cryptography`, **not installed** | **skipped** (`tests/cli/test_vault_cmd.py:41`) | The dependency, or a documented fallback. |
| Telemetry | `grandpa telemetry stats/export/clear` | WORKING | `telemetry stats` → real table | passing | — |
| Models | `grandpa model\|models list/info/pull/remove/status` | PARTIAL | read commands ran (`model status --json` OK). `models` is an exact alias group for `model` — two registrations at `cli/__init__.py:200-207`. `pull` not exercised (downloads). | passing | — |
| Privacy scan | `grandpa scan --quick --json` | WORKING | ran, exit 0 | passing | — |
| Self-update | `grandpa self-update --check` | WORKING | ran → *"Upgrade command: cd … && git pull && uv sync"* | passing | — |
| Registry inspection | `grandpa registry list/show` | WORKING | ran → real registry table | passing | — |
| Profile | `grandpa profile edit/reset` | WORKING | `profile.py` reached from `chat_cmd`, `launcher`, `interactive_tui`, `profile_cmd` | 3 test files | — |
| Quickstart / init / launcher | `grandpa quickstart/init/launcher` | UNKNOWN | these mutate the user's config; deliberately not run in a read-only audit | passing | Verification. |

---

## 3. Orphaned and Dead Code

Method: a full AST import graph over all 617 modules under `src/grandpa/`, plus a scan for
dynamic module-path strings, then per-module importer lookup. Dynamic registries
(`tools/__init__.py:_BUILTINS`, `agents/__init__.py:_BUILTINS`) were resolved manually, so
registered-by-string tools and agents are **not** listed here as orphans.

### 3.1 Modules imported by nothing in `src/`

| Module | Note |
|---|---|
| `grandpa/a2a/{__init__,client,server,protocol,tool}.py` | Entire subsystem; only `a2a` imports `a2a`. `config.a2a.enabled` is read nowhere. |
| `grandpa/notes/search.py` | Superseded by the search path in `cli/notes_cmd.py`. |
| `grandpa/scheduler/tools.py` | No importer. |
| `grandpa/security/rate_limiter.py` | No importer. |
| `grandpa/security/severity_policy.py` | No importer. |
| `grandpa/security/subprocess_sandbox.py` | No importer — the sandbox is never used by `shell_exec`, `code_interpreter`, or `repl`. |
| `grandpa/server/session_store.py` | No importer. |
| `grandpa/sessions/compression.py` | No importer, though `config.compression.*` keys exist. |
| `grandpa/daemon/session_expiry.py` | No importer. |
| `grandpa/engine/_network.py` | No importer. |
| `grandpa/connectors/{attachment_store,chunker}.py` | No importer. |
| `grandpa/templates/agent_templates.py` | Only its own package `__init__`. |
| `grandpa/tools/templates/loader.py` | Only its own package `__init__`. |
| `grandpa/learning/routing/{learned_router,heuristic_policy,heuristic_reward,_utils}.py` | Only `learning/__init__.py`; nothing imports `grandpa.learning`. |
| `grandpa/mcp/bridge.py` | Only `mcp/__init__.py`; zero tests. |
| `grandpa/voice_service/{service,post_processing}.py` | The :8765 TTS sidecar; no `grandpa` command starts it. |
| `grandpa/speech/{tts,kokoro_tts,grandpa_voice_tts,local_voice/*}.py` | The `grandpa.speech.*` stack is disjoint from `grandpa.voice.*`, which is what the CLI actually uses. |

### 3.2 Empty packages (docstring only, zero code)

`skills/automation/__init__.py`, `skills/browser/__init__.py`,
`skills/communication/__init__.py`, `skills/desktop/__init__.py`,
`skills/memory/__init__.py`, `skills/system/__init__.py`, `skills/vision/__init__.py`
— each is **1 line**: a docstring describing capabilities the package does not contain.

### 3.3 Reachable only from the HTTP server (never from CLI or voice)

`advanced_ai.py`, `office_productivity.py`, `developer_assistant.py`, `security_safety.py`
— each imported **only** by `server/routes.py`, and each with **zero test files**.
`production_audit.py` is imported only by `server/api_routes.py`.
`services/{browser,desktop,vision,workflow}_service.py` are reachable only through
`services/registry.py` from the server.

### 3.4 Circular facade layer

`desktop/kernel/{approvals,audits,requests,risk,emergency,execution}.py` are pure
delegating shims that import **private** functions back out of `pc_control`
(`desktop/kernel/approvals.py:9-17` → `pc_control._create_pending`,
`pc_control._approve_local_action_impl`), while `pc_control.py:252,343,433,460,496,515`
imports those same shims. A half-finished extraction that adds indirection and nothing else.

### 3.5 Registered but not dispatchable

- Tool modules absent from `tools/__init__.py:_BUILTINS`, so their `@ToolRegistry.register`
  never executes: `tools/browser.py`, `tools/browser_axtree.py`, `tools/knowledge_search.py`,
  `tools/knowledge_sql.py`, `tools/scan_chunks.py`.
- `agents/__init__.py:_BUILTINS` lists `"react"` and `"monitor"`; neither
  `agents/react.py` nor `agents/monitor.py` exists. Both failures are swallowed at `:46-47`.
- All **43 runtime skills** in `skills/registry/defaults.py` — registered, executable, and
  unreachable from any CLI command (§4.6).

---

## 4. Duplicate Implementations

### 4.1 Desktop / PC control — **six** stacks

| # | Implementation | Reached at runtime by |
|---|---|---|
| 1 | `pc_control.py` (1542 lines) — risk tiers, approvals, audit log, emergency stop | `jarvis` CLI, `automation` CLI, `desktop/automation.py`, `browser/executor.py`, `skills/registry/defaults.py`, `agents/goal_mode.py` |
| 2 | `local_actions.py` (2203 lines) — its own NL parser, its own pending-approval store | **`chat` and `voice`** (`chat_cmd.py:1886`, `voice/assistant.py:243`) |
| 3 | `desktop/automation.py` — a third NL parser, delegating to (1) | **`chat` and `voice`**, tried *before* (2) (`chat_cmd.py:1865`) |
| 4 | `desktop_automation.py` — a pyautogui allowlist with its own permission tiers | only via (2), at `local_actions.py:1806` |
| 5 | `automation/` (Screen Automation V2) — its own confirmation-token pipeline | **`grandpa automation` CLI only** |
| 6 | `desktop/control/*` + `desktop/kernel/*` — a module-per-domain layer re-importing (1)'s privates | (1) itself, circularly |

**Which one is actually reached:** for a chat or voice user it is (3), then (2), then (4) —
never (5), and (1) only indirectly through (3). The approval model differs in each: (1) uses
expiring approval codes in `pc_control_approvals.db`, (2) uses an in-process `_PENDING`
resolvable by saying "yes", (5) uses confirmation tokens. **They do not interoperate** —
proven at §2.4, where (3)/(1) issues a code and (2)'s "yes" handler replies *"There is no
pending local action to approve."*

### 4.2 Approval / confirmation — **four** mechanisms

`pc_control` approval codes · `local_actions.approve_pending_action` (say "yes") ·
`automation/service.py` confirmation tokens · `tools/_stubs.py` `confirm_callback`.
Only the last has a safe default. The first has no CLI redemption path at all.

### 4.3 Browser — **four** stacks

`browser_control.py` (UIA + `webbrowser`, the only one that acts) · `browser/`
(agent/executor/parser) · `browser_awareness/` (capture/analyzer) · `browser_intelligence/`
(page_reader/navigator/summarizer — what the `browser` CLI uses). Chat tries
`browser_awareness` then `browser`; the CLI uses `browser_intelligence`; all three
eventually funnel into `browser_control`.

### 4.4 Web search — **two**, and the CLI reaches the broken one

`web_search/` (Brave/Bing/Serper, key required, **not configured**) — used by
`grandpa search` and chat. `tools/web_search.py` (DuckDuckGo via `ddgs`, keyless, a hard
dependency, **verified working**) — reachable only inside the agent tool loop.

### 4.5 Reminders / scheduling — **five**

`reminders.py` (`~/.grandpa/reminders.db`, CLI `reminders`) · `task_scheduler.py`
(`~/.grandpa/scheduler.db`, chat "remind me") · `scheduler/` (agent tasks, CLI `scheduler`)
· `agents/scheduler.py` · `planner/scheduler.py`. The first two both store "reminders" and
**never see each other's data**.

### 4.6 Skills — **two**

`skills/manager.py` + `skills/loader.py` (filesystem manifests) — what `grandpa skill` uses,
finds nothing. `skills/registry/` (43 runtime skills) — real, working, no CLI.

### 4.7 Agents — **three** trees

`agents/` (registry agents: simple/react/rlm/operative — reached by `ask --agent`) ·
`agent/` (Agent Runtime V1 — reached by `grandpa agent`) · `agent/development/`
(roadmap/sprint engine — reached by `grandpa project`/`sprint`).

### 4.8 Memory / retrieval — **four**

`memory/` + `memory_context.py` (chat memory, working) · `knowledge/` (v1 placeholder
storage + v2 embeddings) · `connectors/` (chunker/embedding_store/retriever) ·
`tools/storage/` (bm25/faiss/colbert/dense/hybrid). Only the first is reachable from chat.

### 4.9 Intent routing — **three**

`router/intent_router.py` + `router/skill_router.py` · `jarvis/intent_router.py` ·
`actions/router.py`. `local_actions.py:357,1050` consults the first and third; `jarvis` uses
only the second.

### 4.10 Command aliases

`grandpa model` and `grandpa models` are registered as two separate groups over the same
module (`cli/__init__.py:200-207`), with duplicated `list/info/pull/remove/status` leaves —
10 commands where 5 would do.

---

## 5. Unsafe Destructive Paths

### 5.1 Reachable **without** any confirmation

| Path | Evidence | Severity |
|---|---|---|
| **`grandpa ask --tools shell_exec …` executes arbitrary shell commands with no prompt and no opt-out.** `cli/ask.py:413-414` hardcodes `agent_kwargs["interactive"] = True; agent_kwargs["confirm_callback"] = lambda prompt: True`. There is **no flag** to require confirmation. | Proven: `ToolExecutor([shell_exec], interactive=True, confirm_callback=lambda p: True)` → `success=True`, command executed. The safe default (`tools/_stubs.py:209-219`) is deliberately overridden. Same exposure for `file_write`, `apply_patch`, `git_commit`, `code_interpreter`, `repl`, `db_query`. | **Highest** |
| **`grandpa agents ask <id> "<msg>"` auto-approves by default.** `cli/agent_cmd.py:642-664`: `--yes/--no-yes` defaults to `True` → `executor._confirm_callback = lambda _prompt: True`. | Same tool set. The user must know to pass `--no-yes`. | **High** |
| **Synthetic keyboard/mouse from chat bypasses its own confirmation tier.** `desktop_automation.py:37-45` marks `click`, `type`, `press`, `hotkey` as `_CONFIRM_REQUIRED_ACTIONS`, enforced only when a `confirm_callback` is supplied. `local_actions.py:1806-1808` calls `execute_automation(result.target)` with **no callback**, and `chat_cmd.py:1886` calls `handle_local_action` with none either. So chat "type &lt;text&gt;" / "press enter" / "paste" / "switch window" send real input unprompted. | `pc_control.py:143-150` documents exactly why this matters: *"`keyboard_hotkey` opens a launcher and `keyboard_type` fills it in, which reaches exactly the capability `script_run`/`shell_run` are BLOCKED to prevent."* That reasoning is enforced on `pc_control`'s path and bypassed on `local_actions`'. | **High** |
| `grandpa downloads latest` opens a file with no prompt from a read-sounding command. | Ran it: *"Opened download: WhatsApp Ptt … .ogg"*. `downloads/safety.py:is_safe_to_open` gates dangerous extensions, so blast radius is bounded. | Low |
| `file_assistant` created `C:\Users\ASUS\Downloads\clipboard` from the phrase "copy this to clipboard". | Reproduced. Writes a file the user never asked for. | Low |

### 5.2 Confirmed **safe** (enforcement verified on the live path)

- `grandpa automation click|type|press|scroll` — `cli/automation_cmd.py:31-34`,
  `click.confirm(..., default=False)`, `--yes` opt-in; enforced at `automation/service.py:123`.
- `grandpa downloads delete|archive|organize` — verified interactive `[y/N]` without `--yes`;
  path-confined by `downloads/safety.py:27-46`.
- `grandpa notes delete`, `projects stop|restart|unregister`, `reminders clear`,
  `telemetry clear`, `profile reset`, `skill remove`, `calendar create|update|delete` — all
  carry `--yes` and prompt otherwise (verified for `notes delete` and `downloads delete`).
- `sprint start` requires `--approve` or an interactive prompt (`cli/sprint_cmd.py:75-84`).
- Tool execution *outside* `ask`/`agents ask` — `tools/_stubs.py:209-219` refuses by default.
- `chat`'s own agent tool loop prompts properly (`cli/chat_cmd.py:1342-1351`) — unlike `ask`.
- `file_permanent_delete`, `script_run`, `shell_run`, `browser_submit_form`,
  `browser_extract_password`, `browser_purchase` are hard-BLOCKED at `pc_control.py:123-130`.
- `jarvis/intent_router.py:47,185-191` blocks anything resembling shell execution.

### 5.3 Destructive but **unreachable** (broken, not dangerous)

Shutdown, restart, sleep and empty-recycle-bin all issue an approval code that **no CLI
command can redeem** (§2.4, finding 3). They are safe by accident, not by design.

---

## 6. Findings, ranked

Status as of 2026-09-11: 10 FIXED, 16 OPEN, 2 DEFERRED. The findings themselves are unchanged
below.

| # | Finding | Status | Closed by / note |
|---|---------|--------|------------------|
| 1 | `ask --tools` auto-approves tools | FIXED | `bacffe0b`, `9485cb8f` |
| 2 | `ask --research` crashes | FIXED | `b6376c14` (flag removed) |
| 3 | HIGH-risk approval flow is a dead end | OPEN | No CLI command redeems approval codes yet |
| 4 | `grandpa workflow` is fake | FIXED | `b6376c14` (CLI group removed; `workflow/engine.py` kept) |
| 5 | `skill list` never finds the 43 skills | OPEN | |
| 6 | Synthetic input skips its confirmation tier | FIXED | `bacffe0b` (premise corrected: dead end, not bypass) |
| 7 | `agents ask` auto-approves by default | FIXED | `bacffe0b`, `9485cb8f` |
| 8 | Volume/brightness/clipboard/process control have no entry point | OPEN | |
| 9 | `grandpa jarvis` understands one command | OPEN | |
| 10 | Browser control stubs report success | OPEN | Partly: false scroll messages removed in `b6376c14`; click/back/forward/reload/focus_search/form_fill/download remain stubs |
| 11 | Reminders never fire on a default install | OPEN | |
| 12 | One-shot reminders become daily | OPEN | |
| 13 | Planner invents application names | OPEN | |
| 14 | `grandpa search` unusable without a key | FIXED | `b6376c14` (keyless DuckDuckGo default) |
| 15 | `python -m grandpa` does not work | OPEN | |
| 16 | Seven empty skill sub-packages | FIXED | `881c5c9a` |
| 17 | `file_assistant` misroutes clipboard requests | OPEN | |
| 18 | Six parallel desktop-control stacks | DEFERRED | Consolidation batch |
| 19 | `desktop/kernel/*` circular layer | DEFERRED | Consolidation batch |
| 20 | Symlink-escape tests skip on Windows | OPEN | |
| 21 | `a2a` imported by nothing | FIXED | `881c5c9a` |
| 22 | MCP has no CLI surface | OPEN | |
| 23 | Ten slash commands do nothing | OPEN | |
| 24 | Default TTS needs an unstartable sidecar | OPEN | |
| 25 | Browser page reading needs a foreground browser | OPEN | |
| 26 | Nineteen config keys never read | FIXED | `881c5c9a` removed 16; `20d02f6b` wired `top_p`/`repetition_penalty`; `24b320e4` Rust sync; `character_voice` is read |
| 27 | Stub reported as a handled action | FIXED | `b6376c14` |
| 28 | Assorted smaller defects | OPEN | Partly: agent names and placeholder (`b6376c14`), `models` alias and most §3.1 modules (`881c5c9a`); five unimported tool modules, `page_reader` URL, `embeddings_placeholder`, duplicate notes remain |

1. **`grandpa ask --tools <any tool>` hardcodes unconditional tool auto-approval.**
   `src/grandpa/cli/ask.py:413-414` sets `confirm_callback = lambda prompt: True` with no
   flag to disable it, so a single non-interactive command can run arbitrary shell commands,
   write and patch files, and commit to git. The framework's own safe default (refuse when
   non-interactive, `tools/_stubs.py:209-219`) is deliberately overridden, and `chat` — the
   more interactive surface — does prompt. A user reading "safe automation with approvals"
   has no reason to expect this. **Effort: S.**

2. **`grandpa ask --research` is dead code that crashes with a raw traceback.**
   `src/grandpa/cli/ask.py:54` imports `grandpa.agents.research_loop`, which does not exist
   anywhere in the repository. Every invocation ends in an unhandled `ModuleNotFoundError`.
   The matching HTTP route `/api/research` also does not exist (404), and the test meant to
   catch that (`tests/server/test_optional_research_router.py:33`) skips with the false
   message *"Research dependencies are installed in this environment."* A documented,
   flag-advertised feature is entirely absent while the test suite reports green.
   **Effort: L.**

3. **The approval flow for every HIGH-risk desktop action is a dead end.**
   Chat/voice "shut down the computer" → *"Approval required … Approval code: A20A89C0
   (expires in 300s)"*, and **no CLI command anywhere redeems an approval code**.
   `pc_control.approve_local_action` (`pc_control.py:342`) is exposed only over HTTP. Saying
   "yes" hits a different pending store and answers *"There is no pending local action to
   approve."* (verified). `chat_cmd.py:1865` also drops the `confirm=` callback that
   `handle_desktop_command` accepts. Users see a security ritual that cannot be completed;
   shutdown/restart/sleep/empty-recycle-bin are therefore unusable. **Effort: M.**

4. **`grandpa workflow` is fake.** `cli/workflow_cmd.py:20,46` import `discover_workflows`
   from `grandpa.workflow.loader`, which does not define it (`loader.py:84`:
   `__all__ = ["load_workflow"]`) — verified `ImportError`. Both commands swallow it and
   print "No workflows found." `workflow run` then prints *"Workflow 'X' started."* while
   executing nothing; the source comment at `:53` says *"Full execution would need a
   GrandpaSystem — just report for now."* `workflow status` is a hardcoded string. There
   are **zero tests** for `workflow/loader.py`. A real graph executor exists in
   `workflow/engine.py` and is unreachable from the CLI. **Effort: M.**

5. **`grandpa skill list` can never find the 43 skills the product actually has.**
   The CLI uses `SkillManager` over `./skills` and `~/.grandpa/skills/`
   (`cli/skill_cmd.py:16-27`); the repo ships nothing there, so it always prints
   *"No skills installed."* Meanwhile `skills/registry/defaults.py` (1272 lines) registers
   43 working runtime skills — verified by direct call — reachable only from internal agent
   and HTTP paths. Two skill systems, and the user-facing one is empty. The live integration
   tests are skipped with a reason blaming a missing inference engine that is in fact
   running. **Effort: M.**

6. **Synthetic keyboard and mouse input from chat bypasses its own confirmation tier.**
   `desktop_automation.py:37-45` classifies `type`/`press`/`hotkey`/`click` as requiring
   confirmation, but `local_actions.py:1806` invokes `execute_automation()` with no
   `confirm_callback` and `chat_cmd.py:1886` supplies none. `pc_control.py:143-150`
   explicitly documents that synthetic input is equivalent to arbitrary code execution —
   that reasoning is enforced on one path and skipped on the one chat uses. **Effort: S.**

7. **`grandpa agents ask` auto-approves tool execution by default.**
   `cli/agent_cmd.py:642-644` — `--yes` defaults to `True`. The help text is honest ("suits
   non-interactive CLI use") but the default is the unsafe one, and it grants `shell_exec`.
   **Effort: S.**

8. **Volume up/down, brightness, clipboard, and process control are declared but have no
   entry point.** `volume_up`/`volume_down` (`pc_control.py:59-60`,
   `desktop_automation.py:58-64`), `brightness_get`/`brightness_set` (`pc_control.py:64-65`)
   and `clipboard_read/write/clear/inspect/history` (`:66-70`) are all in the risk tables
   with no producer anywhere. Verified probes: "turn up the volume", "set brightness to 50",
   "what is in my clipboard", "kill chrome" → **no handler claims any of them**; they fall
   through to the LLM, which will answer conversationally as if it had acted. Process
   termination does not exist at all. These are core "local system control" promises.
   **Effort: M.**

9. **`grandpa jarvis` understands exactly one command.** `jarvis/intent_router.py:38-95`
   routes only "open `<project>` in vscode" (`APP_ALIASES` at `:30-35` contains VS Code and
   nothing else). Everything else exits 1 with *"Try: open my Grandpa project in VS Code"*.
   The command is advertised as "Route Jarvis-style safe local commands" and sits behind
   `jarvis --voice`, a flagship voice path. **Effort: L.**

10. **Browser control beyond "open a URL" is a stub that reports success.**
    `browser_control.py:530-545` — `click`, `back`, `forward`, `reload`, `focus_search`,
    `form_fill`, `download` **always** return `requires_confirmation` and nothing in the
    repository ever completes them. `"scroll"` is not handled at all. Worse,
    `browser_intelligence/navigator.py:82-88` and `:111-117` return *"Scrolled page towards
    heading X"* and *"Scrolled 5 times…"* — messages asserting an action that provably did
    not occur. **Effort: L.**

11. **Reminders never fire on a default install, and there are two disconnected reminder
    stores.** Delivery needs `winotify` (`reminders.py:86-102`), which is only in the
    optional `windows-notifications` extra and is not installed — matching the live reminder
    in `reminders.db` with status `failed`. The polling loop exists only inside the FastAPI
    process (`server/app.py:108-111`), so nothing fires unless the user runs `grandpa serve`.
    Separately, chat "remind me…" writes to `scheduler.db` (`task_scheduler.py:21`), which
    `grandpa reminders list` never reads. **Effort: M.**

12. **Chat reminders silently convert one-shot requests into daily recurring ones.**
    `task_scheduler.py:660-675` supports only `minutely`, `hourly`, and `daily:HH:MM`.
    Verified: "remind me to call mom at 5pm" → *"Reminder set: call mom (daily at 17:00)."*
    The user gets a permanent daily alarm they did not ask for and were not told about.
    **Effort: S.**

13. **The planner invents application names from unmatched goals and rates them Low risk.**
    `planner/decomposer.py:480-489` — `_single_step` matches `open ([\w .+-]+)` greedily.
    Verified: `plan preview "open notepad and type hello"` produces one step, *"Open Notepad
    And Type Hello"*, with `app = "notepad and type hello"` and Risk: Low. `plan execute`
    would run that. Unmatched goals should be rejected, not mangled. **Effort: S.**

14. **`grandpa search` is unusable out of the box while a working search already ships.**
    `web_search/client.py:36,44` supports only Brave/Bing/Serper, all key-gated →
    *"Web search is not configured. Set BRAVE_SEARCH_API_KEY."* Meanwhile
    `tools/web_search.py:118-123` uses `ddgs` — keyless, a **hard** dependency
    (`pyproject.toml:28`), and verified working live. The CLI reaches the broken one.
    **Effort: S.**

15. **`python -m grandpa` does not work.** `src/grandpa/__main__.py` does not exist, so the
    canonical module invocation fails with *"'grandpa' is a package and cannot be directly
    executed"*. This matters concretely because `grandpa.exe` is Device-Guard-blocked on
    this machine, making the module form the only fallback — and it is broken.
    (`python -m grandpa.cli` does work, and `grandpa startup` already registers that form.)
    **Effort: S.**

16. **Seven skill sub-packages are one-line docstrings describing capabilities that do not
    exist.** `skills/{automation,browser,communication,desktop,memory,system,vision}/__init__.py`
    each contain a single docstring such as *"Runtime skill wrappers for desktop and
    PC-control capabilities."* and no code. They inflate the apparent surface of the
    codebase and mislead anyone reading the tree. **Effort: S.**

17. **`file_assistant` misroutes clipboard requests into file copies.** Verified: chat
    "copy this to clipboard" → *"File copied to `C:\Users\ASUS\Downloads\clipboard`."* — a
    junk file was created on disk. **Effort: S.**

18. **Six parallel desktop-control stacks with four non-interoperating approval models.**
    See §4.1-4.2. `pc_control.py` (1542 lines) and `local_actions.py` (2203 lines) are two
    complete implementations of the same feature, both live, invoked in sequence from chat,
    with separate pending-approval stores that cannot resolve each other's requests — which
    is the direct cause of finding 3. **Effort: L.**

19. **`desktop/kernel/*` is a circular no-op layer.** `desktop/kernel/approvals.py:9-17`
    imports `pc_control`'s **private** `_create_pending` / `_approve_local_action_impl`,
    while `pc_control.py:252,343,433,460,496,515` imports those shims back. Pure indirection
    from an abandoned extraction. **Effort: S.**

20. **The symlink-escape security tests never run on the target OS.**
    `tests/kernel/test_file_copy_migration.py:437`,
    `test_file_create_folder_migration.py:342`, `test_file_properties_migration.py:96` skip
    with `[WinError 1314] A required privilege is not held by the client`. Combined with the
    seven POSIX-only `chmod` skips (`tests/security/test_file_permissions.py`,
    `tests/core/test_credentials.py`), the file-sandbox and credential-permission guarantees
    of a Windows-first assistant are unverified on Windows. **Effort: M.**

21. **The `a2a` subsystem is imported by nothing.** `a2a/{client,server,protocol,tool}.py`
    are referenced only by each other; `config.a2a.enabled` is read nowhere outside
    `core/config.py`. Dead weight with a config knob that implies it works. **Effort: S.**

22. **MCP has no CLI surface.** `mcp/server.py`, `mcp/client.py`, `mcp/bridge.py` are
    reachable only via `system/builder.py` and `/v1/mcp` HTTP routes; `mcp/bridge.py` has
    zero tests. There is no `grandpa mcp` command. **Effort: M.**

23. **Ten of thirty-six chat slash commands do nothing.** `cli/slash_commands.py` — `/mode`,
    `/tasks`, `/desktop`, `/system`, `/coding`, `/git`, `/github`, `/voice`, `/order`,
    `/automation` all have `routing="help"` and only print text. `:104` and `:308` describe
    themselves as *"a safe placeholder"*. They are visible in the command picker.
    **Effort: M.**

24. **The default TTS backend requires a sidecar no `grandpa` command can start.**
    `config.tts.backend` defaults to `grandpa_voice`, which needs the service at
    `127.0.0.1:8765` (`voice_service/service.py:25`). Nothing in `src/` or `scripts/` starts
    it — only `voice_runtime/scripts/start_service.ps1`, outside the package. Every install
    therefore silently degrades to pyttsx3 (`voice diagnose` WARN confirms). **Effort: S.**

25. **Browser page reading can only work when a browser is the foreground window.**
    `browser_control.py:683-731` inspects only the foreground window and deliberately
    refuses to fall back to a background browser (comment at `:700-701`). A user typing
    `grandpa browser page` in a terminal makes the terminal foreground, so it always reports
    `unavailable` — verified with 7 Edge processes running. The whole `browser_intelligence`
    CLI group is unusable from a terminal. **Effort: M.**

26. **Nineteen config keys are defined and never read.**
    `intelligence.{checkpoint_path,top_p,repetition_penalty,stop_sequences}`,
    `tools.browser.{timeout_ms,viewport_width,viewport_height}`, `agent.objective`,
    `telemetry.{gpu_metrics,gpu_poll_interval_ms,warmup_samples,steady_state_window,steady_state_threshold}`,
    `operators.auto_activate`, `grandpa_voice.{character_voice,runtime_python,model_cache}`,
    `memory_files.nudge_interval`, `skills.auto_discover`.
    Note `intelligence.top_p` and `repetition_penalty` — users will reasonably expect
    sampling knobs to affect generation; they do not. **Effort: S.**

27. **`local_actions.py:1216-1224` reports a stub as a completed action.**
    "click the highlighted button" returns `status="handled"` with the message *"Clicking
    highlighted buttons is not enabled yet."* A `handled` status for a non-action will read
    as success to any programmatic consumer. **Effort: S.**

28. **Assorted smaller defects.** `agents/__init__.py:11-19 _BUILTINS` names two modules
    that do not exist (`react`, `monitor`), silently swallowed at `:46-47`. Five tool modules
    are never imported so their registrations never run
    (`tools/{browser,browser_axtree,knowledge_search,knowledge_sql,scan_chunks}.py`).
    `page_reader.py:260` hardcodes `url = "https://localhost/page"` for all HTML input,
    voiding domain verification. `knowledge/storage.py:131-134` writes an
    `embeddings_placeholder` record for every document. `desktop_automation.py:154` exports
    `emergency_stop_placeholder` in `__all__`. `grandpa model` and `grandpa models` are
    duplicate alias groups (`cli/__init__.py:200-207`). Creating a note with an existing
    name silently duplicates it (`notes list` shows two `ideas` entries). Seventeen
    unimported modules are listed in §3.1. **Effort: S each.**
