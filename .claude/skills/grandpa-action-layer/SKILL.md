---
name: grandpa-action-layer
description: Build or change anything Grandpa can DO on the computer - catalogued actions, risk tiers, confirmation, the executor, the model tool loop, pc_control mirroring, and the Windows desktop/app/window/file/browser/notes/downloads/memory/reminder/gmail/calendar automation domains. Use when adding a new action or tool, wiring a command to an implementation, debugging "the model did not call the tool", or touching src/grandpa/action_layer, pc_control.py, desktop/control, local/ or cli/_tool_loop.py.
---

# Grandpa action layer

`src/grandpa/action_layer/` is the single door through which Grandpa acts.
Chat (tool loop on by default), voice operator, `jarvis`, workflows, plugins,
MCP tools and paired phones all end in
`grandpa.action_layer.executor.execute(request, confirm_callback)`.

Read the package docstrings first; they are the spec. Detailed mechanics:
[references/catalogue-guide.md](references/catalogue-guide.md).

## Mental model

```
ActionRequest(action, parameters, origin, risk, requires_confirmation)   model.py (frozen)
      │
execute():  get(spec) → BLOCKED? → _validate(schema) → resolve defaults
            → synthetic input with no callback? refuse
            → confirmation (LAYER: executor asks | DOMAIN: domain asks via callback)
            → _call(spec) by Binding → _as_result → _audit (JSONL)
      │
ActionResult(success, message, data, error)   error codes: unknown_action,
invalid_parameters, confirmation_required, confirmation_declined, blocked,
implementation_unavailable, execution_failed
```

Rules baked into the layer (do not break them):

- **Catalogue decides; a caller may only be stricter.** `needs = spec.requires_confirmation or request.requires_confirmation`.
- **No callback = no consent.** Confirmable actions refuse when `confirm_callback is None` (voice, triggered workflows, unattended runs).
- **Failures are returned, never raised** – the tool loop feeds them back to the model.
- **Import isolation.** The package never imports `pc_control`, `local`, `desktop_automation` or handlers at module scope; implementations are dotted-path strings resolved at call time. Enforced by `tests/action_layer/test_import_isolation.py`.
- **Risk mirrors `pc_control`.** `LOW/MEDIUM/HIGH/BLOCKED` must equal `pc_control.{LOW,MEDIUM,HIGH}_RISK_ACTIONS`/`BLOCKED_ACTIONS` unless the action is listed in `LAYER_OWNED` with a reason. Enforced by `tests/action_layer/test_catalogue_coverage.py`.
- **HIGH or `_ALWAYS_CONFIRM` ⇒ LAYER confirmation.** All synthetic input (`keyboard_*`, `mouse_*`, `desktop_navigate`), `close_app/close_window`, `system_lock`, `screen_click` always ask.

## Workflow: add a new action

1. Inspect: `GRANDPA_HOME=$(mktemp -d) uv run python .claude/skills/grandpa-action-layer/scripts/catalogue_report.py --domain <d>` to see neighbours and their risk.
2. Implement the capability in its domain package (e.g. `desktop/control/…`, `notes/automation.py`), not in the action layer. Keep it testable without Windows.
3. Add a `_CALLS` row (Binding, `target`, optional `alias`) – missing rows are an import-time `KeyError`.
4. Add the `_spec(...)` entry in the right `_*_ACTIONS` tuple with an honest one-line description and a JSON schema built with `_schema/_string/_integer`.
5. Decide risk: add the name to the matching `pc_control` risk table **or** to `LAYER_OWNED` with a reason. Use `Confirmation.DOMAIN` only if the prompt text depends on what the domain discovers.
6. Add it to its subject in `DOMAINS` (whole domains only; see `CORE_DOMAINS` docstring on why splitting a domain hides actions from the model).
7. If it is synthetic input or acts in another app, add it to `_ALWAYS_CONFIRM` and check `test_automation_actions_all_confirm.py`.
8. Tests: a domain unit test + an action-layer test in `tests/action_layer/` using a fake implementation. Never let it actuate (the autouse actuation guard replaces every catalogued implementation).
9. Run: `uv run python -m pytest tests/action_layer -q` and the domain's tests, then `uv run ruff check src tests`.

## Workflow: "the model did not call my tool"

1. Does the model support tools? `loop.supports_tools()` asks Ollama `/api/show` capabilities; only `grandpa-brain` and `grandpa-fast` roles call tools (see `grandpa-local-models`).
2. Is the domain loaded? Tiering sends only `CORE_DOMAINS` plus pre-selected domains (`candidate_domains`). Test with `GRANDPA_TOOL_PRESELECT=0` / `GRANDPA_TOOL_TIERS=0` to isolate.
3. Is the description specific? It is what the model reads (`tool_schema.as_tool_definition`).
4. Try it directly: `grandpa ask --tool-loop "<goal>"` (proving-ground path in `cli/_tool_loop.py`).

## Constraints

- Never add an implementation path that bypasses `execute()` (no direct `pc_control.run_local_action` from new code; `voice/operator.py` was migrated away from that).
- Never lower a risk tier or remove an `_ALWAYS_CONFIRM` entry without a security review (`grandpa-security-governance`).
- `EXCLUSIONS` (`shell_run`, `script_run`, `file_permanent_delete`, `browser_submit_form`, `browser_purchase`, `browser_extract_password`) stay excluded unless the owner decides otherwise.
- Windows-only implementations must degrade to an `ActionResult.failed(...)` on other platforms, not crash.

## Verification checklist

- [ ] `tests/action_layer` passes (it is also the commit guard's smoke set).
- [ ] Coverage test agrees with `pc_control` (or `LAYER_OWNED` reason added).
- [ ] Confirmation behaviour tested both with and without a callback.
- [ ] Audit record written (`audit_log_path()`; tests point it into the sandbox).
- [ ] No new module-scope imports of legacy stacks in `action_layer/`.
