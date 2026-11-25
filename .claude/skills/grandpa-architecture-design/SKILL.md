---
name: grandpa-architecture-design
description: Design and evolve Grandpa's structure - decide where new code lives, define module boundaries and seams, review a design for fit with the action layer and GRANDPA_HOME rules, plan behaviour-preserving refactors of duplicated subsystems (two memory systems, several planners, engine vs runtime, import cycles), and write architecture decision records. Use before building a new subsystem, when code "doesn't have an obvious home", when asked to refactor or clean up architecture, or when a change crosses three or more packages.
---

# GRANDPA architecture and design

The tree is a **hard fork of an Apache-2.0 platform** (OpenJarvis/IPW) with a
Windows assistant built on top. That history explains most of the duplication.
Read `references/architecture-map.md` in `grandpa-master-orchestrator` for the
layer map and module table, then come back here for the rules.

## Design rules (follow these unless Captain approves an exception)

1. **One door for actuation.** Anything that changes the machine is a
   catalogued action run by `action_layer.executor.execute`. Domain code keeps
   its implementation, parser and messages; the layer owns risk, confirmation,
   dispatch and audit (`docs/architecture/MIGRATION-PATTERN.md`, "What moves").
2. **Structured seam first.** A domain exposes a function that takes a
   structured request (e.g. `NotesAutomation.execute(action, ...)`). Never route
   by re-parsing strings inside the layer.
3. **New code goes in a package, not a flat module.** The flat
   `src/grandpa/*.py` files (`pc_control.py`, `memory_context.py`, ...) are
   history. Add `src/grandpa/<domain>/` with small modules.
4. **Behaviour separate from toolkit and hardware.** UI controllers take an
   injected view (`ui/bubble.py`, `ui/tk_view.py`); hardware and Windows APIs sit
   behind short adapters. That is what makes the code testable on Linux CI.
5. **State lives under `GRANDPA_HOME`.** Use `grandpa.core.config` /
   `grandpa.runtime_paths`; never a relative path or a hard-coded `~/.Grandpa`.
6. **Optional dependencies are lazy.** Import heavy or platform packages
   inside the function, raise a clear install hint, and declare an extra in
   `pyproject.toml`. Core must run without them.
7. **No new import cycles.** `voice/assistant.py` already imports a private
   function from `cli/chat_cmd.py`. Don't add more cli ↔ voice or
   pc_control ↔ desktop edges. Shared logic moves *down* into a lower package.
8. **Wire it or delete it** (AD-013). Do not add a module that nothing calls,
   and do not leave security code orphaned.

## Recorded decisions you must respect

`docs/architecture/ARCHITECTURE_DECISIONS.md` (2026-08-26). Many are
**Recommended** or **Needs ratification**, not done. Check the code before
assuming one happened.

| ID | Decision | State in code (fde2164) |
|---|---|---|
| AD-005 / AD-006 | one IntentDispatcher, one PolicyEngine | partly: the action layer is the policy door; several routers remain |
| AD-007 | collapse `engine/` into `runtime/` | not done; `engine/` is a shim with the larger fan-in |
| AD-008 / AD-009 | `agents/` is the agent framework, `planner/` the planner | not done; `agent/`, `agents/`, `planner/` all live |
| AD-010 | one MemoryFacade, four named stores | not done; needs a data migration and Captain's approval |
| AD-002 | archive Rust out of tree | superseded in practice: E2 (#59) made Rust optional, still in tree |
| AD-020 | `agent/development/` is product code | retained |
| AD-022 | safety rests on the policy layer, not on path absence | binding |

Target and phases: `docs/architecture/TARGET_ARCHITECTURE.md`,
`MIGRATION_PLAN.md` (Phases 0–7), owners per concern in `MODULE_OWNERSHIP.md`
(CANONICAL / ABSORB / SHIM / ARCHIVE / DELETE / KEEP).

## Workflow for a design

1. **Frame.** The requirement (from `grandpa-product-planning`) and its
   non-functional limits: latency on the target machine, RAM, offline
   behaviour, Windows-only parts.
2. **Map what exists.** `rg` for the concept; check `MODULE_OWNERSHIP.md` for
   the canonical owner; list duplicates you will touch.
3. **Choose the seam.** Name the package, the public function or class, the
   data types (dataclasses), and the catalogue actions with risk tiers.
4. **Draw the flow.** Entry surface → routing → executor → implementation →
   state. Use the ASCII style of `architecture-map.md`.
5. **Consider two options at least**, including "extend the existing module".
   Record the trade-off.
6. **Write an ADR** for anything structural, using
   [references/adr-template.md](references/adr-template.md). Number it after
   the last AD in `ARCHITECTURE_DECISIONS.md` and mark it *Proposed*.
7. **Hand off** to the implementing skills with the file list and tests.

## Refactor protocol (duplicated or tangled code)

1. Open an issue or get Captain's go-ahead first (CONTRIBUTING asks for it
   before large changes).
2. Follow `MODULE_OWNERSHIP.md`: pick the canonical owner, then ABSORB
   behaviour into it.
3. Keep old import paths working with a **SHIM** (a thin re-export with a stated
   removal release) until every caller moves.
4. One concern per PR. No behaviour change mixed with a move.
5. Tests: the touched packages plus everything that imports them
   (`grandpa-testing-qa`, `scripts/which_tests.py`). Windows CI must stay green.
6. Data migrations of live user stores need a backup step, a dry run, and
   Captain's explicit yes (`grandpa-memory-knowledge`).

## Review checklist for a design or PR

- [ ] Does any new path actuate without the executor?
- [ ] Is there an existing owner this duplicates?
- [ ] Are new files under `GRANDPA_HOME`, created with `secure_mkdir` / `secure_create` where sensitive?
- [ ] Does it run (degraded) without its optional extra?
- [ ] Any new import cycle? (`python -X importtime -c "import grandpa.<pkg>"` shows the import chain.)
- [ ] Is Windows-only code behind a platform check, with a Linux-testable core?
- [ ] Is the decision recorded (ADR or PR description) with the alternatives?
