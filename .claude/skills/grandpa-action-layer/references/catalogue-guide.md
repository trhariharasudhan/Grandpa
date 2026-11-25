# Action catalogue guide

Source: `src/grandpa/action_layer/` at `main` @ `fde2164`.

## Files

| File | Role |
|---|---|
| `model.py` | `ActionRequest`, `ActionResult`, `Origin`, `RiskLevel`. Pure data, frozen dataclasses. |
| `catalogue.py` (~3.2k lines) | `CATALOGUE` (174 `ActionSpec`), `_CALLS`, `_ALWAYS_CONFIRM`, `EXCLUSIONS`, `LAYER_OWNED`, `DOMAINS`, `CORE_DOMAINS`, `candidate_domains()`, `get()`, `MCP_PREFIX`, `PLUGIN_PREFIX`. |
| `executor.py` | `execute()`, `_call()` adapters per `Binding`, `_audit()`, `audit_log_path()`, announce hooks for the avatar ("tool_call_start"). |
| `loop.py` | Model-driven loop: `run()`, `supports_tools()`, domain loading via `load_tools`, `DEFAULT_STEP_LIMIT = 8`, env `GRANDPA_TOOL_TIERS`, `GRANDPA_TOOL_PRESELECT`. |
| `tool_schema.py` | Ollama/OpenAI-style tool definitions; `core_tool_definitions()`, `domain_tool_definitions()`. |

## Counts (measured with `scripts/catalogue_report.py --summary`)

- 174 actions: 112 LOW, 51 MEDIUM, 11 HIGH, 0 BLOCKED (blocked things live in `EXCLUSIONS`).
- Confirmation: 139 none, 19 layer, 16 domain.
- HIGH: `system_sleep/restart/shutdown`, `empty_recycle_bin`, `process_kill`, `file_delete`, `notes_delete`, `downloads_delete`, `memory_clear`, `calendar_delete`, `gmail_trash`.

## Bindings (how the executor calls an implementation)

`REQUEST_ACTION` `method(request, action)` · `REQUEST_ACTION_PLATFORM` `method(request, action, platform=)` ·
`ACTION_PLATFORM` · `PLATFORM_ONLY` · `REQUEST_ONLY` · `SERVICE_REQUEST` · `SERVICE_ONLY` ·
plus domain-specific shapes (`APPLICATION_ACTION`, `ACTION_TARGET`, ...). Methods are resolved to their
class and the class is constructed with no arguments. The request object is a duck-typed
`_ServiceRequest` with `.target` and `.args` (mirrors `pc_control.LocalActionRequest`).

## Dynamic actions

- `mcp__<server>__<tool>` – built on demand from `~/.grandpa/mcp.toml`; always HIGH + layer confirmation.
- `plugin__<plugin>__<tool>` – built on demand from enabled plugins; risk only goes up from declared permissions.

## Origins

`USER_CLI`, `USER_CHAT`, `USER_VOICE`, `MODEL`, `AGENT`, `SKILL`, `HTTP`, `PLAN`. Origin is for audit and
caller policy, never for risk. The deterministic-first invariant: phrase handlers (`grandpa.local.handle_local_action`)
only ever receive *user* text, never model output (`tests/test_action_origin_invariant.py`).

## Legacy paths still present

- `pc_control.py` (~2k lines): risk tables, approval store, emergency stop, `run_local_action`. HTTP routes in
  `server/routes.py` still use it for structured local actions and emergency stop.
- `desktop/kernel/` (risk, approvals, execution, audits, emergency) – live, small.
- `local/` package (former `local_actions.py`): allowlisted phrase parsing, never arbitrary shell.
- `cli/_tool_loop.py` docstring still says "deliberately not wired into chat"; that is stale – chat uses
  `chat_tool_turn` by default since PR #16 (`[tools] chat_tool_loop`, default true).

## Tests that guard the layer

`tests/action_layer/`: `test_executor.py`, `test_loop.py`, `test_loop_tiers.py`, `test_domain_preselection.py`,
`test_catalogue_coverage.py`, `test_automation_actions_all_confirm.py`, `test_import_isolation.py`,
`test_tool_schema.py`, `test_tool_tiers.py`, per-domain `test_*_actions.py`. Root-level: `tests/test_pc_control*.py`,
`tests/test_action_origin_invariant.py`, `tests/test_local_actions*.py`.

## Review notes (open questions, not bugs)

- `file_move`, `file_rename`, `file_copy` are MEDIUM with no confirmation; check overwrite behaviour in
  `files/executor.py` before relying on that for model-initiated calls.
- `memory_forget` does not ask; `memory_clear` does (HIGH).
