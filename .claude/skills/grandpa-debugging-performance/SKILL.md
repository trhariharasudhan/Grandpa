---
name: grandpa-debugging-performance
description: Find the root cause of Grandpa bugs, hangs and slowness, and make it faster without breaking it - reproduce in a sandboxed GRANDPA_HOME, collect evidence with grandpa doctor --json, grandpa oops, the stall watchdog (GRANDPA_STALL_TIMEOUT), telemetry, traces and --verbose logs, then fix with a regression test. Covers Ollama cold-start and prompt-cache cost, keep_alive, CLI import time, avatar GPU/RAM budget, and measuring on the Ryzen 5 7520U / 16 GB target machine. Use for any "it doesn't work", "it hangs", "it's slow", "uses too much RAM/CPU", or a failing test whose cause is unclear.
---

# GRANDPA debugging and performance

Rule zero: **find the cause, then fix it.** "Flaky", "timing" and "works on my
machine" are symptoms. This repo's history shows that most hard bugs were a
measurement nobody had taken (README "When something breaks").

## Step 1 – Reproduce safely

```bash
export GRANDPA_HOME=$(mktemp -d)     # PowerShell: $env:GRANDPA_HOME = (New-Item -ItemType Directory "$env:TEMP\gp-$(Get-Random)").FullName
uv run grandpa doctor --json         # readiness: config, Ollama, models, mic, OCR, launcher ...
uv run grandpa --verbose <command>   # DEBUG logging + rotating cli.log under GRANDPA_HOME
```

Never debug against Captain's real `~/.grandpa` unless he asks; copy what you
need into the sandbox. For pytest, do **not** export `GRANDPA_HOME`; the test
conftest owns it (`grandpa-testing-qa`).

## Step 2 – Collect evidence

| Tool | Use it for | Where |
|---|---|---|
| `grandpa doctor --json` | environment and dependency readiness; each item ends with the exact fix | `cli/doctor_cmd.py` |
| `grandpa oops "what happened"` | records the note plus last command, last error, voice capture numbers, models, `scheduler.enabled`, version and platform. `--list`, `--export --to <file>` for one file to hand over | `diagnostics/oops.py`, files under `GRANDPA_HOME/diagnostics/` (redacted) |
| `GRANDPA_STALL_TIMEOUT=<seconds>` | a command that hangs: dumps every thread's stack when the process stops making progress. Default 0 = off | `diagnostics/stall.py`, armed in `cli/__init__.py` |
| `grandpa telemetry stats --top N` / `export` | per-model request counts, latency, tokens (SQLite, local) | `telemetry/`, `cli/telemetry_cmd.py` |
| traces | recorded agent interactions | `traces/` |
| action audit | what the executor ran, with origin and outcome | `action_layer.executor.audit_log_path()` (JSONL) |
| `scripts/burnin_daily_use.py` | daily-use burn-in pack (`--timeout`, `--skip-workflow-stress`) | `burnin.py` |

Voice problems: the four numbers that settle "it didn't hear me" are
`speech_window_rms`, `noise_floor`, `max_chunk_rms` and voiced seconds (all in
`oops`). Reminder problems: check `scheduler.enabled` before reading code.

## Step 3 – Isolate

1. Shrink to the smallest command or test that fails.
2. Split the path at its stages (routing → model → executor → implementation →
   state) and check each stage's output. `grandpa-agent-engineering` has the
   message flow; `grandpa-action-layer` has the executor.
3. Compare with a known-good commit (`git bisect run uv run pytest <test> -q`).
4. Check the known pitfalls below before inventing a theory.

## Step 4 – Fix with proof

1. Write the failing regression test first (in the package's `tests/` folder).
2. Make the smallest fix at the stage that is wrong.
3. Show the test failing before and passing after, and run the focused suite.
4. In the PR, state the root cause in one sentence and the evidence.

## Performance work

**Measure on the target machine, report numbers.** Ryzen 5 7520U, integrated
GPU, 16 GB RAM shared with Ollama. The README notes identical work varying
105× in wall time on that machine, so take several runs and report the median
and range.

Known costs (from `runtime/ollama_adapter.py`, measured):

| Request | Wall time |
|---|---|
| cold, no tools | ~28 s (weights load ~20 s) |
| cold, 86 tools in prompt | ~560 s (tool prompt evaluation at ~10 tok/s) |
| warm, same prompt (cache hit) | ~8 s |

So the big wins are: keep the model loaded (`engine.ollama.keep_alive`), keep
the tool prompt byte-identical (sorted, no timestamps) so the cache hits, send
fewer tools (`load_tools` by subject), and pick a smaller role for simple
turns (`grandpa-local-models`). Warm evaluation of new text is still only
~50–230 tok/s, so trimming prompt size matters on the voice path.

Other levers:

| Area | How to measure | Lever |
|---|---|---|
| CLI start-up | `uv run python -X importtime -m grandpa --help 2> imports.txt` | keep commands lazy (`_lazy` in `cli/__init__.py`), move heavy imports into functions |
| Avatar | `ui/avatar_budget.py` samples GPU % and WebView2 RAM | stay within 20% iGPU / 300 MB; the ring-only fallback |
| Memory recall | `uv run grandpa memory recall-test` (README) | embedding model and store choice (`grandpa-memory-knowledge`) |
| STT | voice accuracy runs (README "Measuring recognition accuracy") | faster-whisper model size vs latency |

Never trade safety for speed: no skipping confirmation, no disabling the audit,
no removing a guard.

## Known pitfalls (check these first)

| Symptom | Real cause seen in this repo |
|---|---|
| Thousands of test errors about writes or GRANDPA_HOME | `GRANDPA_HOME` exported while running pytest |
| Linux full-suite run shows ~2,700 cascade errors | order-dependent `fake_import_module` leak from `tests/jarvis/test_voice_input.py`; run the package alone |
| pytest ends with INTERNALERROR, no summary | `verification_plugin.write_record` refused by the write guard at session end; use `--junitxml` |
| Tests red because of a browser tab title | host state not pinned; see the `real_host_state` marker |
| Command printed its output then never exited | a lingering thread; arm `GRANDPA_STALL_TIMEOUT` |
| Model "hangs" for minutes on first request | cold tool-prompt evaluation, not a hang; `warn_if_cold` in `cli/_tool_loop.py` |
| Reminder never fired | `scheduler.enabled` is off by default; use `reminders watch` or `run-due` |
| Windows-only failure not seen on Linux | trust Windows CI (`test (windows)`) |
