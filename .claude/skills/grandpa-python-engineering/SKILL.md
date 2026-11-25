---
name: grandpa-python-engineering
description: Write Grandpa Python code the way this repo writes it - uv and extras, ruff rules, Python 3.10 compatibility, dataclass config sections in core/config.py, GRANDPA_HOME paths, lazy CLI commands and optional imports with install hints, logging with credential redaction, error handling without blanket excepts, safe file writes, subprocess rules, and Windows-specific code. Use when writing or reviewing any Python in src/grandpa, adding a config option, CLI command or dependency, or when code style or structure is in question.
---

# GRANDPA Python engineering standards

These are the conventions the existing code already follows (verified on
`fde2164`). Match them; do not introduce a new style.

## Toolchain

| Item | Value | Where |
|---|---|---|
| Python | `requires-python >= 3.10`; installer uses 3.11 | `pyproject.toml`, `scripts/install.ps1` |
| Package manager | **uv**; `uv.lock` is tracked on purpose | `.gitignore` note |
| Build | hatchling, wheel from `src/grandpa` | `pyproject.toml` |
| Lint | ruff, `select = ["E","F","I","W"]`, `E501` ignored, target `py310` | `[tool.ruff]` |
| Tests | pytest, 300 s per-test timeout, strict markers | `[tool.pytest.ini_options]` |

Daily commands (Windows PowerShell or bash):

```powershell
uv sync --extra dev --extra server --extra voice --extra screen
uv run ruff check src tests
uv run ruff format --check <files you changed>
```

Keep code valid on **3.10**: no `tomllib` without the `tomli` fallback, no
`typing.Self`, no `ExceptionGroup` / `except*`, no `enum.StrEnum`. Known
violation: `ui/bubble.py`, `ui/avatar_states.py` and `voice/cli_session.py`
already import `StrEnum`, so those modules fail on 3.10. Fix the floor or add a
fallback; don't add more.

## Module shape

- Start with a module docstring that says **why** the module exists, and
  `from __future__ import annotations` (640 of 688 modules do).
- Comments explain *why*, often naming the incident or measurement behind the
  choice. Don't write comments that restate the code.
- Prefer small dataclasses (`@dataclass(slots=True)` in config) and explicit
  return types such as `ActionResult` over loose dicts.
- Add new features as a package under `src/grandpa/<domain>/`, not as a new
  flat module (see `grandpa-architecture-design`).

## Configuration

- One `GrandpaConfig` with ~28 section dataclasses in `core/config.py`,
  loaded by `load_config()` from `GRANDPA_HOME/config.toml`.
- To add an option: add a field with a safe default to the right section, read
  it through `load_config()`, document it in `docs/getting-started/configuration.md`,
  and test both the default and an override.
- `DEFAULT_CONFIG_DIR` is **frozen at import**. A dataclass default like
  `str(DEFAULT_CONFIG_DIR / name)` is evaluated once; use a
  `field(default_factory=...)` or resolve the path at call time
  (see the comment near the top of `core/config.py`).
- Never hard-code `~/.grandpa` or `~/.Grandpa`. Use the config dir or
  `grandpa.runtime_paths`.

## CLI commands

- Commands are registered lazily with `_lazy(name, "grandpa.cli.x_cmd:x", short_help=..., optional_modules=..., install_hint=...)`
  in `cli/__init__.py`. Startup must not import heavy packages.
- Use click plus `rich.console.Console` for output.
- Destructive commands confirm with `grandpa.cli._tty.require_confirmation(prompt, yes=..., cancelled=...)`
  and accept `--yes`; non-interactive runs refuse instead of guessing.

## Optional dependencies

- Declare them as an extra in `[project.optional-dependencies]` (e.g. `screen`,
  `voice`, `gmail`, `tray`, `avatar`, `piper`, `wake`).
- Import inside the function that needs them and raise a clear error with the
  install command (`uv sync --extra <name>`). Core commands must still work.
- A new **core** dependency needs a reason in a comment, like the `pycaw` note in
  `pyproject.toml`. Use platform markers (`; sys_platform == 'win32'`).
- After adding a package: `uv add <pkg>` (or `uv add --optional <extra> <pkg>`),
  commit `pyproject.toml` and `uv.lock` together.

## Logging

- `logger = logging.getLogger(__name__)` per module.
- The CLI configures logging in `cli/log_config.py:setup_logging`; its
  `SanitizingFormatter` passes every line through `CredentialStripper`. Don't
  add handlers that bypass it.
- `grandpa --verbose` turns on DEBUG and a rotating `cli.log` under the config
  dir. Never log secrets, tokens, full email bodies or screen text.

## Error handling

- The repo has ~1,000 `except Exception` sites. Do not add more. Catch the
  specific exception, and at a boundary (CLI, server route, action) turn it into
  a clear user message (`response_cleanup.clean_error_message` exists for
  user-facing text).
- Never swallow an error silently. Log it, or return a failed `ActionResult`
  with a reason.
- Missing optional dependency, missing device, Ollama not running: degrade with
  a message that names the fix (the `grandpa doctor` style).

## Files and paths

- Sensitive directories and files: `security/file_utils.py` → `secure_mkdir`
  (0700) and `secure_create` (0600).
- Atomic writes: write a temporary file, then `os.replace(temp, target)` (pattern
  in `profile.py`, `projects/registry.py`).
- Respect `security/file_policy.py` for user file operations; protected paths
  are checked before existence.
- Use `pathlib.Path` and `encoding="utf-8"` everywhere; Windows defaults differ.

## Subprocesses

- No `shell=True` in new code. The 5 existing uses are known
  (`tools/shell_exec.py`, `security/subprocess_sandbox.py`,
  `cli/self_update_cmd.py`) and covered by security review.
- Pass an argument list, set a `timeout`, and never build a command from model
  or user text. Typed actions instead of shell is a product rule.

## Windows-specific code

- Guard with `sys.platform == "win32"` and keep the decision logic in a pure
  function that Linux CI can test.
- COM, pycaw, UI Automation, DPAPI and pywin32 calls go behind a small adapter
  so tests can inject a fake.
- Windows CI (`test (windows)`) is the authoritative signal for this code.

## Before you hand over

1. `uv run ruff check` on the changed files, and `ruff format` on new files.
2. Focused tests (`grandpa-testing-qa`, `scripts/which_tests.py`).
3. Any script that imports `grandpa` runs with `GRANDPA_HOME` set to a temp dir.
4. Docs updated for new commands or config.
