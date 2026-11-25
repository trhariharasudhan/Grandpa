# Test infrastructure reference

## Layout

- `tests/<pkg>/` mirrors many `src/grandpa/<pkg>/` packages (action_layer, agents, cli, core, desktop,
  devices, memory, mcp, plugins, runtime, scheduler, security, server, speech, tools, ui, voice, workflow, …).
- ~85 flat `tests/test_*.py` files cover flat modules and older assistant features.
- Packages **without** a test dir (e.g. `notes`, `screen`, `vision`, `browser`, `gmail`, `calendar`,
  `downloads`, `files`, `apps`): their tests live in flat files such as `tests/test_notes_automation.py`,
  `tests/test_screen_*.py`. The commit guard treats a change there as "full suite".

## Autouse guards (in `tests/`)

| File | What it prevents | Opt-out marker |
|---|---|---|
| `actuation_guard.py` | Every implementation named by the action catalogue, plus low-level primitives, is replaced before each test | `real_actions(reason=…)` |
| `write_guard.py` | Writes outside `tmp_path` / sandbox `GRANDPA_HOME` | `real_writes(reason=…)` |
| `host_state.py` | Reading the live foreground window (protected-window keywords like "sign in") | `real_host_state(reason=…)` |
| `conftest.py` | Clears registries and the event bus between tests | – |
| `sandbox.py` | `arm()` for scripts outside pytest | – |
| `verification_plugin.py` | Records pytest's real exit status for the commit guard | – |
| `witness_support.py` | Stubs focus witnesses (foreground-window readings) | – |

Each guard's docstring tells the incident that created it (Notepad opened, volume set to 30%,
screen locked, `~/.ssh/authorized_keys` written by a mutation test). Read them before touching them.
A change to any of these files requires the full suite.

## CI (`.github/workflows/ci.yml`)

| Job | Runner | What |
|---|---|---|
| lint | ubuntu | `uv sync --extra dev --extra server --extra voice --extra screen`, `ruff check src/ tests/` |
| test | ubuntu | builds the Rust extension with maturin, runs an explicit list of 18 test files, coverage ≥20% |
| test (windows) | windows | imports check, hardware-gating check, then `pytest -m "not live and not cloud"` (full deterministic suite) |
| e2e | windows, manual dispatch only | installs Ollama, pulls a model, `scripts/run_e2e.py` |
| rust | ubuntu | `cargo clippy --workspace -D warnings`, `cargo test` (Python pinned 3.12 for pyo3) |

Other workflows: `docs.yml` (mkdocs), `docker-headless.yml` (arm64 headless image), `pypi-publish.yml`,
`autotag.yml`, `take-assign.yml`.

Known CI defect (verified 2026-11-24): `autotag.yml` runs `gh workflow run desktop.yml`, but no
`desktop.yml` exists, so every push to `main` ends with "Auto-tag on main push: failure"
(HTTP 422) after the tag and the PyPI dispatch already happened.

## Observed baseline in a Linux cloud container (2026-11-25)

Full `pytest -m "not live and not cloud and not microphone and not e2e"` on Linux/Python 3.13 with
CI extras: see `GRANDPA_SKILLS_AUDIT_REPORT.md` §9.7 for the exact counts. Failures there are
mostly Windows-only paths; the authoritative signal is the Windows CI job.

Pitfalls seen in that audit:

- Running pytest with `GRANDPA_HOME` exported produced 2,300+ errors (write guard refusing
  `runtime/test-home`). Run pytest with `GRANDPA_HOME` unset; use `GRANDPA_TEST_HOME` to move the test home.
- A full Linux run ends with an INTERNALERROR in `verification_plugin.pytest_sessionfinish` (write guard still
  armed), so no pytest summary is printed. Use `--junitxml=<file>` to get counts anyway.
- An order-dependent leak (patched `importlib.import_module` from `tests/jarvis/test_voice_input.py`) cascades
  into ~2,775 import errors in a full Linux run. If you see `ModuleNotFoundError` raised by
  `fake_import_module`, it is this leak, not your change.

## Debugging recipes

- **Hang**: `uv run python -m pytest <path> -x -vv --timeout 60` and look for real I/O (microphone,
  sockets, Ollama). Add a mock rather than raising the timeout.
- **Only fails in the full run**: test-order leakage through a registry or a module-level path; check
  `conftest.py` resets and whether the module computed a path from `DEFAULT_CONFIG_DIR` at import.
- **Fails only on the dev box**: live host state (focused window title) – pin it via `host_state`.
- **User reports a bug**: ask for `grandpa oops --export` output; it holds the last command, model, TTS
  backend, voice capture stats and version, already redacted.
