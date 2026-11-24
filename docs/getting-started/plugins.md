# Plugins

A plugin adds tools to Grandpa with a small folder: a `plugin.toml` that says
what the plugin may do, and one Python file. Each tool becomes a Grandpa
action called `plugin__<plugin>__<tool>`, usable from `grandpa plugin call`
and from workflow steps.

Grandpa looks for plugins in:

- `%USERPROFILE%\.grandpa\plugins\<name>\` (your own plugins), and
- the `plugins\` folder of the Grandpa checkout (the `hello` sample lives there).

`GRANDPA_PLUGINS_DIR` (a `;`-separated list of folders) replaces both.

## The rules

- **Off until you enable it.** `grandpa plugin enable <name>` shows the
  plugin's permissions and tools and asks. Enabling records a fingerprint of
  every file in its folder; if any file changes later, the plugin stops working
  until you enable it again.
- **Risk only goes up.** A tool's risk is the highest of what it declares and
  what its permissions imply. Every tool above LOW asks you first, every time.
- **The permission check.** A plugin may run a Grandpa action only if its
  manifest lists `actions:<action name>`. The action goes through the normal
  checks and asks you the same way. A plugin can never answer a question for
  you, and event handlers (which run in the background) have nobody to ask, so
  anything needing a yes is refused there.
- **The code check.** Before loading, Grandpa reads the plugin's code and
  refuses it if it imports Grandpa's internals (anything but `grandpa.plugins`),
  uses `eval`/`exec`/dynamic imports or hidden `__dunder__` attributes, or uses
  processes, the network or file deletion without the matching permission.
  This check is best-effort: plugin code runs inside Grandpa's process, so
  **enable only plugins you trust**.
- **Kill switch.** `GRANDPA_PLUGINS_OFF=1` turns every plugin off at once.

## Permissions

| Permission | Means | Lowest risk of its tools |
| --- | --- | --- |
| `actions:<name>` | may run that Grandpa action through `ctx.run_action` | that action's risk |
| `network` | uses the internet | MEDIUM (asks) |
| `files` | moves or deletes files | HIGH (asks) |
| `system` | starts processes, uses system APIs | HIGH (asks) |

## plugin.toml

```toml
[plugin]
name = "hello"                 # must match the folder name
version = "0.1.0"
description = "A sample plugin."
module = "plugin.py"           # the Python file, inside the folder
permissions = ["actions:datetime_now"]

[config.greeting]              # options, with defaults
default = "Vanakkam"
description = "The word used to greet."

[[tools]]
name = "greet"                 # becomes plugin__hello__greet
description = "Greet someone by name."
function = "greet"             # defaults to the tool name
risk = "low"                   # low, medium or high
required = ["name"]

[tools.parameters]
name = { type = "string", description = "Who to greet." }

[[events]]
on = "workflow_end"            # a Grandpa event name
handler = "on_workflow_end"
```

Change an option without editing the plugin (that would un-enable it) in
`%USERPROFILE%\.grandpa\plugins.toml`:

```toml
[hello]
greeting = "Hello"
```

## plugin.py

Every function gets `ctx` first, then the tool's parameters:

```python
from grandpa.plugins import ActionResult

def greet(ctx, name):
    return f"{ctx.config['greeting']}, {name}!"

def greet_with_time(ctx, name="Captain"):
    clock = ctx.run_action("datetime_now", kind="time")   # needs actions:datetime_now
    if not clock.success:
        return ActionResult.failed("no_clock", message=clock.message)
    return f"{ctx.config['greeting']}, {name}! {clock.message}"
```

A function may return text, a dict (returned as data), or an `ActionResult`.
`ctx.log("...")` writes to Grandpa's log. Event handlers run when the
scheduler daemon is running.

## Commands

```powershell
cd D:\Grandpa
uv run python -m grandpa plugin list
uv run python -m grandpa plugin enable hello
uv run python -m grandpa plugin call plugin__hello__greet --arg name=Captain
uv run python -m grandpa plugin disable hello
```
