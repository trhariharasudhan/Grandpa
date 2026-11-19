# Workflows

A workflow is a small YAML file that runs several of Grandpa's actions in a
row. Every step is an action from the action catalogue, so a workflow can never
do anything Grandpa cannot already do, and every risky step still asks you first.

Workflows live in `%USERPROFILE%\.grandpa\workflows\<name>.yaml`
(set `GRANDPA_WORKFLOWS_DIR` to use another folder). A sample is in
`examples/workflows/check-my-pc.yaml`.

```powershell
uv run python -m grandpa workflow list
uv run python -m grandpa workflow validate check-my-pc
uv run python -m grandpa workflow run check-my-pc              # dry run: nothing happens
uv run python -m grandpa workflow run check-my-pc --yes        # really run it
uv run python -m grandpa workflow run check-my-pc --yes --var quiet_level=10
```

`--yes` means "really run the steps". It does **not** approve risky steps:
a step whose action needs confirmation (deleting, shutting down, emptying the
recycle bin...) still asks `[y/N]` on the terminal, and fails when nobody can
answer.

## File format

```yaml
name: quiet
description: Lower the volume
vars:                 # defaults; override with --var name=value
  level: 20
steps:
  - id: before        # letters, digits, _ and -; used by later steps
    action: volume_get
  - id: lower
    action: volume_set
    params: {level: "{{ vars.level }}"}
    when: steps.before.ok and steps.before.data.level > vars.level
    retries: 1        # extra tries after a failure (max 5)
    retry_delay: 1    # seconds between tries
    timeout: 60       # seconds; time spent answering a prompt is not counted
    continue_on_error: false
```

- **Templates**: `{{ vars.name }}` (or just `{{ name }}`), `{{ steps.<id>.message }}`,
  `{{ steps.<id>.ok }}`, `{{ steps.<id>.data.<key> }}`.
- **Conditions** (`when:`): `==`, `!=`, `<`, `>`, `<=`, `>=`, `contains`,
  `not contains`, a leading `not`, joined with `and` / `or`. They are never
  run as Python.
- A step that fails stops the workflow unless it has `continue_on_error: true`.
  A step that was declined, timed out or had bad parameters is never retried.
