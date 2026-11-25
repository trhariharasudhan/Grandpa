---
name: grandpa-workflows-extensions
description: Extend Grandpa without touching its core - YAML workflows (grandpa workflow list/validate/run), workflow triggers (time, new file, app start, phrase), reminders, routines and the scheduler daemon, plugins (plugin.toml + plugin.py, grandpa plugin enable), external stdio MCP servers (~/.grandpa/mcp.toml, grandpa mcp), and the product's own TOML skills runtime. Use when a user wants an automation, routine, plugin or MCP tool, or when reminders/triggers do not fire.
---

# Grandpa workflows, schedules, plugins and MCP

All four extension mechanisms end in the action-layer executor, so an extension
can never do more than a catalogued action, and anything confirmable still asks
a human – or is refused when nobody can be asked (triggered runs have no
callback). File formats and examples: [references/formats.md](references/formats.md).

## Pick the mechanism

| Need | Use | Code |
|---|---|---|
| Several existing actions in a row, with vars/conditions/retries | YAML workflow | `workflow/loader.py` (`load_yaml_workflow`), `workflow/engine.py`, `workflow/expressions.py` (safe condition language, never `eval`) |
| Run it at a time / on a new file / when an app starts / on a phrase | Workflow trigger | `workflow/triggers.py` (SQLite), checked by the scheduler daemon tick; phrase via `grandpa.local.handle_local_action` |
| One-shot reminder | Reminders | `reminders.py`, `reminder_parser.py`, `grandpa reminders add "…" --in 10m` |
| Recurring routine (morning briefing, etc.) | Routines | `task_scheduler.py`, `scheduler/`, `scheduler_daemon.py`, actions `routine_*` |
| New capability in Python, packaged by the owner | Plugin | `plugins/host.py`, `plugins/manifest.py`, sample `plugins/hello/` |
| A capability someone else ships as an MCP server | MCP stdio server | `mcp/servers.py`, `mcp/transport.py`, `grandpa mcp list/test/call/off/on` |
| A genuinely new built-in action | Not an extension → `grandpa-action-layer` | |

The product also has an inherited **TOML skills runtime** (`src/grandpa/skills/`, bundled
definitions in `skills/data/*.toml`, `grandpa skill …`) and a declarative `skill_builder/`.
These are Grandpa's runtime skills, not Claude Code skills; they run through `tools/`, not the
action catalogue. Prefer YAML workflows for new automations.

## Workflow: create or fix an automation

1. Validate first: `GRANDPA_HOME=$(mktemp -d) GRANDPA_WORKFLOWS_DIR=<dir> uv run grandpa workflow validate <name>`
   checks every step against the catalogue.
2. Dry run (default): `grandpa workflow run <name>`; real run only with `--yes` (still asks for confirmable steps).
3. Triggers: `grandpa workflow trigger add <name> --at 07:30 | --file-in <dir> --pattern *.pdf | --app code.exe | --phrase "…"`,
   then `trigger list/pause/resume/remove/check`. First check after adding only snapshots (no fire for existing files/apps).
4. "Reminder never fired": the scheduler is **off by default** (`scheduler.enabled`); delivery happens on
   `grandpa reminders watch`, `reminders run-due`, or a running daemon/`grandpa serve`. Late reminders are still
   delivered with "(N late)" and logged to `reminders-delivered.log` under `GRANDPA_HOME`.
5. Tests: `uv run python -m pytest tests/workflow tests/scheduler tests/test_reminders.py tests/test_reminder_parser.py tests/test_task_scheduler.py tests/test_scheduler_daemon.py -q`.

## Workflow: plugin

1. Copy `plugins/hello/` to `~/.grandpa/plugins/<name>/` (or set `GRANDPA_PLUGINS_DIR`).
2. Declare every permission in `plugin.toml` (`network`, `files`, `system`, `actions:<name>`); risk only goes up
   (`network` MEDIUM, `files`/`system` HIGH). Undeclared-but-used capabilities stop the plugin loading.
3. `grandpa plugin enable <name>` shows permissions, asks, and pins file fingerprints; any later edit disables it
   until re-enabled. Tools become `plugin__<name>__<tool>`.
4. Test with `grandpa plugin call plugin__<name>__<tool>`; unit tests in `tests/plugins/`.

## Workflow: MCP server

1. Add `[servers.<id>]` to `~/.grandpa/mcp.toml` (`GRANDPA_MCP_CONFIG`) with `command`, `args`, an explicit
   `allow` list (missing = nothing allowed), `timeout`.
2. `grandpa mcp test <id>` (handshake + tool list), then `grandpa mcp call mcp__<id>__<tool>`.
3. Every MCP action is HIGH and asks each time. Kill switch: `grandpa mcp off` / `GRANDPA_MCP_OFF=1`.

## Constraints

- Never give a workflow, trigger, plugin or MCP server a way to answer a confirmation.
- Plugins run in Grandpa's process and cannot be sandboxed; the static check is best-effort. Review plugin code
  like core code (`grandpa-security-governance`).
- Don't add `eval`/`exec`/dynamic import to the workflow expression language.
- Don't install third-party MCP servers or plugins on the owner's machine without their yes.
