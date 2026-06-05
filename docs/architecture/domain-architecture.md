# Grandpa Domain Architecture

Grandpa keeps `src/grandpa` as the public Python package while progressively
grouping backend capabilities into domain packages. Compatibility shims stay in
place for old imports until a release explicitly removes them.

## Domain Boundaries

- `ai/`: response cleanup, model routing, planning, and AI diagnostics.
- `browser/`: visible browser control and extension-backed page context.
- `vision/`: screen awareness, OCR, visual targeting, and UI detection.
- `voice/`: realtime browser voice state and diagnostics.
- `desktop/`: app launching, window control, monitor/process awareness, and desktop automation.
- `automation/`: routines, schedulers, workflow execution, and orchestration.
- `memory/`: personal memory, recall, persistence, and semantic context.
- `safety/`: approvals, permission policy, audit, and security checks.
- `integrations/`: mobile, communication, IoT, and external service bridges.
- `skills/`: runtime skill registry plus legacy manifest/overlay skill tooling.

## Runtime Skill Registry

The runtime registry lives in `src/grandpa/skills/registry/` and is separate
from the older manifest/overlay skill system. It is the incremental bridge from
large action routers toward modular tools usable by CLI, API, workflows, mobile,
and future MCP/plugin runtimes.

The registry exposes:

- `register_skill(...)`
- `get_skill(...)`
- `list_skills(...)`
- `list_categories(...)`
- `execute_skill(...)`

Each `RuntimeSkill` declares:

- name
- description
- category
- risk level
- approval requirement
- supported parameters
- dry-run support
- executor

The first migrated runtime skills are thin wrappers around existing Grandpa
implementations:

- `desktop.summary`
- `desktop.monitors`
- `desktop.diagnostics`
- `browser.diagnostics`
- `vision.visual_diagnostics`
- `vision.screen_diagnostics`
- `automation.workflow_status`
- `memory.recall`
- `desktop.keyboard_type` as an approval-gated example wrapper

Legacy command parsing in `local_actions.py` is intentionally preserved. In
this phase, selected low-risk diagnostics delegate to the registry at execution
time. This keeps old CLI/API behavior stable while creating a scalable runtime
tool surface.

## API Surface

Runtime skill diagnostics are available at:

- `GET /v1/skills`
- `GET /v1/skills/categories`
- `GET /v1/skills/{name}`
- `POST /v1/skills/execute`

`GET /v1/skills` preserves the existing `skills` response key for older
frontend/API consumers and adds a `runtime` diagnostics object.

## Allowed Import Direction

- Domain packages may depend on `core`, `safety`, and narrow utility modules.
- `local_actions.py` and `pc_control.py` may temporarily call runtime skills.
- Runtime skill wrappers should call existing implementations rather than
duplicating action logic.
- Future workflow steps should prefer `{skill, params}` references once the
target skill has focused tests.

## Remaining High-Risk Modules

These modules remain intentionally flat for now:

- `local_actions.py`
- `pc_control.py`
- `sdk.py`
- `_rust_bridge.py`

They are broad public/runtime surfaces and should be split only through small,
tested registry-backed extractions.

## Next Migration Order

1. Extract more read-only PC-control actions into runtime skills.
2. Convert safe workflow steps from raw action strings to `{skill, params}`.
3. Add registry wrappers for browser context and visual search/click planning.
4. Move integration foundation modules into `integrations/` with shims.
5. Keep destructive or approval-heavy actions in `pc_control.py` until the
   approval bridge is proven through focused tests.
