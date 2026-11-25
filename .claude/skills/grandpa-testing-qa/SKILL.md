---
name: grandpa-testing-qa
description: Test, verify and debug Grandpa changes safely - choosing the right pytest scope, the autouse actuation/write/host-state guards and their markers, GRANDPA_HOME sandboxing, CI parity (Linux subset vs full Windows job), the commit-verification guard, e2e and confirmation probes, release gate, and grandpa doctor / oops for troubleshooting. Use after any code change, when tests fail or hang, when writing new tests, or before committing.
---

# Grandpa testing and QA

The suite is large (527 test files) and protective: by default **nothing in a
test may actuate the desktop, write outside its sandbox, or read live host
state.** Your job is to keep it that way while proving your change works.
Infrastructure details: [references/test-infrastructure.md](references/test-infrastructure.md).

## Setup (once per checkout)

```bash
uv sync --extra dev --extra server --extra voice --extra screen   # same extras as CI
```

Without `server`/`voice` extras ~36 modules fail at collection (`fastapi`, `numpy`
missing). That is an environment problem, not a code failure.

**Do not export `GRANDPA_HOME` when running pytest.** `tests/conftest.py` sets up its own
home (`GRANDPA_TEST_HOME`, default `./runtime/test-home`; its `.db`/`.jsonl` files are git-ignored) and rebinds
`core.config.DEFAULT_CONFIG_DIR` to it, but only *defaults* `GRANDPA_HOME`. A pre-set
`GRANDPA_HOME` splits the two, and the write guard then refuses writes to the test home:
thousands of spurious `ActuationDenied` errors (observed: 2,300+ errors in one run). The
sandbox rule in the orchestrator is for ad-hoc scripts, not for `python -m pytest`.

## Workflow

1. **Pick the scope** from what changed (mirrors the commit guard exactly):
   `python .claude/skills/grandpa-testing-qa/scripts/which_tests.py`
   - `src/grandpa/<pkg>/…` → `tests/<pkg>`; `src/grandpa/<mod>.py` → `tests/test_<mod>*.py`
   - always plus the smoke set `tests/action_layer`
   - anything in `tests/` root helpers (conftest, guards, sandbox, fixtures) or a package with no test dir → full suite
2. **Run focused tests**: `uv run python -m pytest <paths> -q`. Read pytest's own
   summary line; never trust an exit code after `| tail`.
3. **Fix, then re-run only what failed** (`--lf` or the node ids).
4. **Lint**: `uv run ruff check src tests` (CI runs ruff on `src/ tests/`).
5. **Broader run when required**: `uv run python -m pytest -m "not live and not cloud" -q`.
   The Windows CI job runs exactly this; the Linux job runs an 18-file subset.
6. **Report** counts (passed/failed/skipped/errors), the command, and anything
   you could not verify because it is Windows-only or needs hardware/Ollama.

## Writing tests

- Use `tmp_path` and the sandboxed `GRANDPA_HOME` the fixtures provide. Never name a real absolute path.
- Mock boundaries: Ollama (`respx` for httpx), microphone, TTS, UIA, pyautogui, Google APIs.
- Need a real implementation? Add `@pytest.mark.real_actions(reason="…")`, `real_writes(reason=…)`
  or `real_host_state(reason=…)`. The reason is mandatory and must say what keeps it off the machine.
- Markers in `pyproject.toml`: `core`, `release`, `integration`, `optional`, `environment`, `slow`,
  `live`, `microphone`, `browser`, `e2e`, hardware vendor markers. Hardware tests self-skip unless
  e.g. `GRANDPA_RUN_MICROPHONE_TESTS=1`.
- `pytest-timeout` is 300 s per test; a hang usually means real hardware or a real network call slipped through.

## Probes outside pytest

Any ad-hoc script importing `grandpa` must be sandboxed first – either
`GRANDPA_HOME=$(mktemp -d) uv run python script.py` or `from tests.sandbox import arm; arm()`
at the top. The repo's Claude hook refuses unsandboxed probes. `grandpa.core.config.DEFAULT_CONFIG_DIR`
is computed at import, so setting the env var after import is too late.

## Higher-level checks

| Check | Command | Needs |
|---|---|---|
| e2e CLI suite | `uv run python scripts/run_e2e.py --model <tag>` (exit 2 = could not run, not a pass) | Ollama + a model |
| Confirmation enforcement probe | `uv run python scripts/verify_confirmation_enforcement.py` | Ollama |
| Daily-use validation | `uv run python scripts/validate_daily_use.py --skip-app-launch` | Windows |
| Release gate | `uv run python scripts/release/final_release_gate.py` / `final-release-gate.ps1` | Windows |
| Test report | `uv run python scripts/testing/test_suite_report.py --release-only` | – |
| Readiness | `GRANDPA_HOME=… uv run grandpa doctor --json` | – |
| User bug capture | `grandpa oops "…"`, `grandpa oops --export` | – |

## Commit guard (opt-in, per worktree)

`python scripts/install_git_hooks.py` arms `scripts/git-hooks/commit-msg`, which refuses a
commit unless `tests/verification_plugin.py` recorded a passing run covering the touched
packages for exactly that tree. Escape hatch: a `Tests-Skipped: <reason, ≥20 chars>` trailer –
use only with the owner's agreement and say so in the report.

## Constraints

- Never delete, skip, xfail or loosen a test or guard to get green. Never remove a marker reason.
- Never run real desktop actions, microphone capture, email/calendar mutations or purchases from tests.
- Never commit on a failing or partial run; never claim a pass you did not observe.
- On Linux many Windows-only tests fail or error (pywin32, UIA, SAPI, tkinter display). Compare against
  a baseline run of `main` before attributing failures to your change.
