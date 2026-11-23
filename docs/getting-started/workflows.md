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

## Sample: morning routine

`examples/workflows/morning-routine.yaml` says good morning with the weather
(Bengaluru by default), today's reminders and the battery level, spoken in
Grandpa's configured voice (your ElevenLabs voice when its key is set, else
Piper or the local voice). Every step only reads; nothing on the PC changes.

```powershell
Copy-Item examples\workflows\morning-routine.yaml $env:USERPROFILE\.grandpa\workflows\
uv run python -m grandpa workflow run morning-routine                      # dry run
uv run python -m grandpa workflow run morning-routine --yes                # say it
uv run python -m grandpa workflow run morning-routine --yes --var city=Chennai
```

The weather comes from [Open-Meteo](https://open-meteo.com) (free, no key);
only the city name and its coordinates leave the PC. With no internet the
routine still says the reminders and battery. The actions it uses --
`weather_now`, `reminders_today`, `battery_status`, `speak_text` -- can be
steps in your own workflows too.

To hear it every morning, or when you ask for it (see Triggers below):

```powershell
uv run python -m grandpa workflow trigger add morning-routine --at 07:30
uv run python -m grandpa workflow trigger add morning-routine --phrase "run my morning routine"
```

## Triggers: start a workflow on its own

```powershell
uv run python -m grandpa workflow trigger add check-my-pc --at 07:30          # every day (also daily:HH:MM, weekly:0:09:00 for Monday, hourly)
uv run python -m grandpa workflow trigger add check-my-pc --file-in $env:USERPROFILE\Downloads --pattern *.pdf
uv run python -m grandpa workflow trigger add check-my-pc --app code.exe     # when VS Code starts
uv run python -m grandpa workflow trigger add check-my-pc --phrase "run my morning routine"
uv run python -m grandpa workflow trigger list
uv run python -m grandpa workflow trigger pause 1
uv run python -m grandpa workflow trigger resume 1
uv run python -m grandpa workflow trigger remove 1
uv run python -m grandpa workflow trigger check     # check time/file/app triggers once, now
```

- **Time, file and app** triggers are checked every few seconds by Grandpa's
  background scheduler (it runs inside `grandpa serve`).
- A **file** trigger fires for a file that was not there at the last check
  (half-finished downloads are ignored). If the workflow has a `file` variable,
  it gets the new file's path.
- An **app** trigger fires when the program starts, not while it stays open.
- A **phrase** trigger works in chat, `grandpa ask`, voice and from the phone:
  "Hey Grandpa, run my morning routine".
- A triggered run has nobody to ask, so a step that needs your yes is
  **refused**, not run. `trigger add` warns you about such steps.
- Every run (triggered or `run --yes`) writes one line to the action audit log
  (`%USERPROFILE%\.grandpa\runtime\logs\local_actions.jsonl`, `"source": "workflow"`).
