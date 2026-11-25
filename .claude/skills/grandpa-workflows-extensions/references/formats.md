# Extension file formats (summary)

Full user docs: `docs/getting-started/workflows.md`, `plugins.md`, `mcp.md`, `docs/user-guide/scheduler.md`.
This file summarises them so you can check a file quickly; the docs and the loaders win on any difference.

## YAML workflow (`~/.grandpa/workflows/<name>.yaml`, `GRANDPA_WORKFLOWS_DIR`)

```yaml
name: check-my-pc
description: System info, volume and brightness
vars: {quiet_level: 30}          # override: --var quiet_level=10
steps:
  - id: volume                   # letters, digits, _ and -
    action: volume_get           # any catalogue action, plugin__*, or mcp__*
    retries: 1                   # max 5; declined/timed-out/bad-params never retried
    retry_delay: 1
    timeout: 60                  # prompt time not counted
    continue_on_error: true
  - id: quieter
    action: volume_set
    params: {level: "{{ vars.quiet_level }}"}
    when: steps.volume.ok and steps.volume.data.level > vars.quiet_level
```

Templates: `{{ vars.x }}`, `{{ steps.<id>.message|ok|data.<key> }}`. Conditions: `== != < > <= >=`,
`contains`, `not contains`, leading `not`, `and`/`or` – parsed by `workflow/expressions.py`, never run as Python.
Loader: `yaml.safe_load` only. Samples: `examples/workflows/check-my-pc.yaml`, `morning-routine.yaml`.
The same package also has an older TOML `load_workflow()` (inherited graph format).

## Triggers (`grandpa workflow trigger add <name> …`)

`--at 07:30` (also `daily:HH:MM`, `weekly:<0-6>:HH:MM`, `hourly`) · `--file-in <dir> --pattern *.pdf`
(new files only; a `file` var receives the path) · `--app code.exe` (on start) · `--phrase "…"`.
Stored in SQLite; unattended runs get no confirmation callback; every run/failure is audited.

## plugin.toml (`~/.grandpa/plugins/<name>/` or repo `plugins/`, `GRANDPA_PLUGINS_DIR`)

```toml
[plugin]
name = "hello"            # = folder name
version = "0.1.0"
description = "…"
module = "plugin.py"
permissions = ["actions:datetime_now"]   # also: network (MEDIUM), files (HIGH), system (HIGH)

[config.greeting]
default = "Vanakkam"

[[tools]]
name = "greet"            # action plugin__hello__greet
function = "greet"
risk = "low"              # can only be raised by permissions
required = ["name"]
[tools.parameters]
name = { type = "string", description = "Who to greet." }

[[events]]
on = "workflow_end"
handler = "on_workflow_end"
```

`plugin.py` functions take `ctx` first (`ctx.config`, `ctx.run_action(name, **params)`, `ctx.log`) and return
text, a dict, or `grandpa.plugins.ActionResult`. Options are overridden in `~/.grandpa/plugins.toml` (editing the
plugin itself un-enables it). Kill switch: `GRANDPA_PLUGINS_OFF`.

## mcp.toml (`~/.grandpa/mcp.toml`, `GRANDPA_MCP_CONFIG`)

```toml
# enabled = false
[servers.files]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/Notes"]
allow = ["list_directory", "read_text_file"]   # "*" = all; missing = none
timeout = 30
# cwd = "D:/Notes"
```

Keys belong in environment variables, not this file (servers inherit Grandpa's environment).
The older `[tools.mcp] servers` config entry is not used by this mechanism.
