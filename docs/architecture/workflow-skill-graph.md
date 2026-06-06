# Workflow Skill Graph Migration

Grandpa workflows now support two step schemas:

- `raw_action_v1`: legacy natural-language action records. These remain supported for existing SQLite workflow rows.
- `skill_graph_v2`: structured skill-backed steps with `skill`, `params`, `risk_level`, `approval_required`, `dependencies`, and `execution_source`.

## Compatibility

Existing workflow rows are not rewritten destructively. When a workflow is read, Grandpa normalizes each step in memory:

- Known safe diagnostic/readiness actions are converted to `skill_graph_v2`.
- Unknown, app-launch, file, browser, and automation actions remain `raw_action_v1`.
- Medium/high-risk actions keep approval metadata and do not bypass the PC-control safety layer.

## Skill Execution

Skill-backed workflow steps execute through the runtime skill registry during dry-run simulation. The executor reports:

- schema version
- skill name
- params summary with sensitive keys redacted
- execution source
- risk level
- approval state
- truthful failure status

Legacy raw steps continue to use the existing dry-run path.

## Migration Scope

The first migrated workflow paths are intentionally low risk:

- developer workspace readiness
- desktop diagnostics
- browser research planning
- visual diagnostics
- workflow/readiness checks

File organization, visual clicks, keyboard/mouse automation, destructive operations, and unrecognized app actions remain legacy or approval-gated until a later dedicated migration.
