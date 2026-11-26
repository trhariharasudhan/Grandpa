# Where Everything Is

A map of the repository: what each folder is for, so you can find a thing by
its job. Updated 2026-11-26.

## Top level

| Folder / file | What it is |
| --- | --- |
| `src/grandpa/` | **All of Grandpa's Python code.** Map below. |
| `tests/` | Automated tests, mirroring `src/grandpa/` folder by folder. |
| `docs/` | Documentation. Map below. |
| `scripts/` | Install, setup and maintenance scripts (e.g. `install_launcher.ps1`). |
| `assets/` | Brand: logo, icons, images. |
| `configs/` | Example configuration files. |
| `models/` | Recipes for Grandpa's local models (no downloaded weights). |
| `notebooks/` | Colab/Kaggle notebooks for training Grandpa's own models. |
| `plugins/` | Example plugins (`plugins/<name>/plugin.toml`). |
| `examples/` | Small usage examples. |
| `rust/` | Optional native speed-ups (Rust). |
| `docker/` | Container files for the home server. |
| `voice_runtime/` | Local voice models and tools (mostly downloaded, not in git). |
| `grandpa.cmd` / `grandpa.sh` | Start Grandpa without the blocked `.exe` (Windows / Linux). |
| `pyproject.toml`, `uv.lock` | Python package definition and locked versions. |
| `README.md`, `CHANGELOG.md`, `LICENSE`, `NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` | Standard project files, kept at the top where GitHub looks for them. |

Folders that only exist on your PC and are not in git: `.venv` (Python
packages), `.uv-cache`, `runtime/`, `_scratch/`, `.grandpa/`.

## `src/grandpa/`: the code, by job

The folders below are grouped by what they do. (They all still sit side by
side in `src/grandpa/`; moving them into group folders is planned, see the
end of this page.)

### 1. What you see and talk to (the "frontend")

| Folder | Job |
| --- | --- |
| `app/` | The desktop app (`grandpa app`): chat window, settings, phone pairing. Its page is in `app/web/`. |
| `ui/` | The orb ring (`grandpa orb`), "Hey Grandpa", reminders said aloud. Page in `ui/avatar_web/`. |
| `tui/` | The full-screen terminal chat (`grandpa` with no arguments). |
| `cli/` | Every `grandpa ...` command, and the chat engine (`cli/chat_cmd.py`). |
| `server/` | The local API server (`grandpa serve`). |
| `voice/`, `speech/` | Microphone, wake word, speech to text, text to speech. |
| `tray.py` | The system tray icon. |

### 2. The brain

| Folder | Job |
| --- | --- |
| `engine/`, `runtime/` | Talking to the AI models (Ollama on your PC, or a cloud key). |
| `intelligence/`, `models/` | Which models exist, Grandpa's own models. |
| `prompt/` | Grandpa's personality and rules (how he talks). |
| `planner/` | Breaking a long request into steps. |
| `agent/`, `agents/`, `operators/`, `workflow/` | Multi-step and background agents. |
| `router/`, `learning/` | Deciding which part should handle a request. |

### 3. Doing things on the PC (actions)

| Folder | Job |
| --- | --- |
| `action_layer/` | **The single list of everything Grandpa can do**, with each action's risk and whether it asks first. |
| `actions/`, `local/` | Older action paths behind the action layer. |
| `desktop/`, `apps/` | Open/close apps, windows, volume, brightness, power. |
| `browser/`, `browser_awareness/`, `browser_intelligence/` | Control and read the web browser. |
| `files/`, `downloads/`, `notes/` | Files, the Downloads folder, notes. |
| `screen/`, `vision/` | Reading the screen. |
| `automation/` | Clicking and typing on screen, carefully. |
| `web_search/` | Searching the web. |
| `gmail/`, `calendar/` | Google mail and calendar (optional). |
| `tools/`, `skills/`, `skill_builder/`, `mcp/`, `plugins/` | Tools, skills, MCP connectors and plugins. |

### 4. Remembering (the "database" side)

| Folder | Job |
| --- | --- |
| `memory/` | What Grandpa remembers about you. |
| `knowledge/`, `connectors/` | Your documents, searchable. |
| `reminders.py`, `scheduler/` | Reminders and scheduled tasks (SQLite). |
| `sessions/`, `traces/`, `telemetry/` | Conversation sessions, logs, usage records. |

### 5. Safety and the foundation

| Folder | Job |
| --- | --- |
| `security/` | Safety checks, audit log, blocked actions. |
| `core/` | Settings (`core/config.py`), shared types, events, yes/no reading, "never claim a fake done". |
| `kernel/`, `system/`, `services/` | How requests run end to end. |
| `devices/` | Paired phones. |
| `diagnostics/` | `grandpa doctor` and health checks. |

The loose `.py` files directly in `src/grandpa/` (38 of them, e.g.
`pc_control.py`, `natural_actions.py`, `reminders.py`) are older modules that
belong to one of the groups above.

## `docs/`

| Folder | What's in it |
| --- | --- |
| `docs/user-guide/` | How to use Grandpa (e.g. `phone-access.md`). |
| `docs/getting-started/` | Install and first run. |
| `docs/product/` | Product plan, desktop app spec, MVP status. |
| `docs/plans/` | Work plans. |
| `docs/architecture/` | How the code is designed. |
| `docs/audit/` | Code audits and capability maps. |
| `docs/development/` | For working on the code (this page). |
| `docs/testing/` | Test checklists. |
| `docs/release/` | Release notes and process. |
| `docs/archive/` | Old documents kept for history. |

## Planned: group the code folders

Moving the folders above into real group folders (`src/grandpa/interface/`,
`src/grandpa/brain/`, `src/grandpa/actions/`, `src/grandpa/data/`,
`src/grandpa/foundation/`) touches thousands of import lines, so it is done in
steps, one group at a time, with the tests run after each step. Status: TBD.
