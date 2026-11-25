---
name: grandpa-master-orchestrator
description: Master entry point for any GRANDPA (Grandpa / ODIN) development work, from planning a feature to shipping it. Use at the start of every GRANDPA task to load the shared project knowledge (vision, roadmap, capability status, architecture map, governance), apply the non-negotiable safety rules (GRANDPA_HOME sandbox, no real actuation in tests, confirmation gates), and route to the right specialist skill or combination of skills (planning, architecture, Python, agents, UI, actions, voice, vision, models, memory, workflows, API, integrations, security, testing, debugging, release, research).
---

# GRANDPA master orchestrator

You are working on **Grandpa** (repo `trhariharasudhan/Grandpa`), a Windows-first,
offline-first personal AI assistant. "ODIN" is the internal codename of the
local model family (`grandpa-brain`, `grandpa-fast`, ...), not a separate program.
The Python package is `grandpa` under `src/grandpa/`; the console script is
`grandpa` (`grandpa.cli:main`).

This skill does four things: holds the shared project knowledge, enforces the
shared rules, routes you to specialist skills, and keeps multi-skill work
consistent. It does not repeat the specialists' content.

## 0. Shared project knowledge (read what the task needs, not all of it)

| File | Read it when |
|---|---|
| [references/project-vision.md](references/project-vision.md) | any product question, priorities, target machine, languages, current vs future phase |
| [references/roadmap.md](references/roadmap.md) | planning new work, naming a milestone, checking what already landed |
| [references/capability-status.md](references/capability-status.md) | before saying a feature exists, is partial, or is missing |
| [references/architecture-map.md](references/architecture-map.md) | finding where a subsystem lives, layer rules, known structural problems |
| [references/governance.md](references/governance.md) | authority, boundaries, what needs Captain's explicit yes |
| [references/skill-routing.md](references/skill-routing.md) | dependency map, overlap owners, multi-skill recipes |

Do not ask Captain for anything these files already answer. Ask only when a
requirement is genuinely ambiguous and a wrong guess would be expensive.

## 1. Orient before you touch anything

1. Read the request and decide which subsystem(s) it touches (table in §3).
2. Read [references/architecture-map.md](references/architecture-map.md) for the
   layer map and where each subsystem lives.
3. Check [references/capability-status.md](references/capability-status.md) so you
   never describe a planned feature as implemented.
4. Inspect the real code (`rg`, read the module docstrings: they are unusually
   accurate in this repo and usually explain *why*). Repo docs under
   `docs/architecture/` are partly stale (they predate the `action_layer` and
   still mention `local_actions.py`, which is now the `grandpa.local` package).
   Trust code over docs, and say so when they disagree.

## 2. Non-negotiable rules (apply to every specialist)

Full text and reasons: [references/governance.md](references/governance.md).

- **Sandbox first.** Any Python that imports `grandpa` outside pytest must run with
  `GRANDPA_HOME` set to a throwaway dir *before* import (several paths are frozen
  at import time from `grandpa.core.config.DEFAULT_CONFIG_DIR`). The repo's own
  Claude hook `scripts/hooks/require_sandboxed_probe.py` refuses commands that
  don't. Example: `GRANDPA_HOME=$(mktemp -d) uv run grandpa doctor`.
- **Nothing actuates in tests.** `tests/actuation_guard.py`, `tests/write_guard.py`
  and `tests/host_state.py` are autouse. Opt-outs need a marker *with a reason*
  (`real_actions`, `real_writes`, `real_host_state`). Never remove a guard to make
  a test pass.
- **Every desktop/system action goes through `grandpa.action_layer.executor.execute`.**
  Never add a second door to an implementation, and never weaken a risk tier or
  confirmation rule to make a feature work.
- **No secrets in code, docs, skills or logs.** Credentials go through
  `grandpa.security.secret_store.SecretStore`.
- **Inspect before editing; preserve behaviour; report failed tests honestly.**
- **Destructive or outward-facing steps need the owner's explicit yes**: deleting
  user data, `git push --force`, resets, touching `~/.grandpa` on a real machine,
  sending email/messages, running real desktop actions, Ollama model removal.
- **Commit/push only when asked.** The repo has a Stop hook
  (`scripts/hooks/require_pushed_commits.py`) that complains about unpushed commits,
  and an optional commit-msg guard (`scripts/commit_verification.py`) that refuses
  commits without a recorded passing test run for the touched packages.
- **Heredocs:** never write file content containing backslashes through a shell
  heredoc (`scripts/hooks/block_escaped_heredoc.py` blocks it). Use the file-write tool.

## 3. Route to a specialist

Load only the skills the task needs. Most tasks need one specialist plus
`grandpa-testing-qa` at the end.

| Task touches | Use skill |
|---|---|
| A new idea, feature brief, PRD/spec, scope, milestone, "what should we build next" | `grandpa-product-planning` |
| Where code should live, module boundaries, refactors, duplicated subsystems, ADRs | `grandpa-architecture-design` |
| Python style, config, logging, errors, optional dependencies, file/path handling, uv | `grandpa-python-engineering` |
| How a message becomes a reply: prompts, identity, conversation window, tool loop behaviour, agents, planners, Tamil/English | `grandpa-agent-engineering` |
| Bubble, orb, avatar window, tray, palette, UI states, lip-sync display | `grandpa-desktop-ui` |
| Adding/changing an action, risk tier, confirmation, `pc_control`, desktop/apps/files/browser/notes/downloads automation | `grandpa-action-layer` |
| Microphone, STT, VAD, push-to-talk, wake word, TTS backends, voice datasets | `grandpa-voice-pipeline` |
| Screenshots, OCR, grandpa-eyes, UI Automation, read window, screen click, privacy list | `grandpa-screen-vision` |
| Ollama runtime, Odin roles, Modelfiles, model eval, tool-capable models, LoRA data | `grandpa-local-models` |
| Personal memory, memory V1 store, knowledge/RAG, embeddings, SQLite stores, migrations | `grandpa-memory-knowledge` |
| YAML workflows, triggers, reminders/routines/scheduler, plugins, stdio MCP servers | `grandpa-workflows-extensions` |
| FastAPI server, `/v1` + `/api` routes, headless Pironman node, phone device routes | `grandpa-api-server` |
| Gmail, Calendar, web search, weather, ElevenLabs, OAuth, any third-party HTTP API | `grandpa-external-integrations` |
| Auth, approvals, secrets, device pairing, plugin/MCP trust, screen privacy, injection, any security review | `grandpa-security-governance` |
| Writing or running tests, CI parity, commit guard, e2e, release gate | `grandpa-testing-qa` |
| A bug with unknown cause, a hang, slowness, RAM/CPU/latency, `doctor`/`oops` evidence | `grandpa-debugging-performance` |
| Git workflow, CI workflows, versioning, packaging, install script, Docker, releases | `grandpa-devops-release` |
| Comparing libraries/models/approaches, feasibility, a spike or prototype | `grandpa-research-prototyping` |

**Multi-skill tasks.** Pick one primary skill and say which. Add
`grandpa-security-governance` when a trust boundary moves, and always finish with
`grandpa-testing-qa`. Recipes for common combinations (new feature end to end,
new integration, performance fix) are in
[references/skill-routing.md](references/skill-routing.md).

**Future phase.** Smart home, IoT, hardware and robotics have no code yet. Do not
invent a skill for them. Use `grandpa-research-prototyping` for feasibility, and
propose `grandpa-smart-home-iot` / `grandpa-hardware-robotics` when Captain starts
that work.

## 4. Standard workflow

0. **Check status** – is this already built, partial, or planned?
   (`capability-status.md`, `roadmap.md`). Never rebuild what exists.
1. **Understand** – locate code with `rg`; read docstrings and the matching
   `tests/<pkg>/` or `tests/test_<module>*.py`.
2. **Plan** – name the files you will change and the tests that prove it.
3. **Change** – smallest behaviour-preserving diff; follow the existing comment
   style (comments explain *why*, often with the incident that motivated them).
4. **Verify** – run focused tests (see `grandpa-testing-qa`, `scripts/which_tests.py`),
   then `uv run ruff check src tests`.
5. **Report** – what changed, what was run, exact pass/fail counts, what could
   not be verified (e.g. Windows-only behaviour on Linux).

## 5. Project vocabulary

- **Captain** – how the code and docs address the owner (the human authority).
- **Origin** – who asked for an action (`USER_CLI`, `USER_CHAT`, `USER_VOICE`, `MODEL`, `AGENT`, `SKILL`, `HTTP`, `PLAN`).
- **Grandpa "skills"** (`src/grandpa/skills/`, TOML files in `skills/data/`) are the
  *product's* runtime skills. They are unrelated to these Claude Code skills.
- **Odin roles** – Brain, Fast, Mini, Coder, Eyes, Guard, Memory, Ears, Voice.

## 6. Maintaining these skills

Run `python .claude/skills/grandpa-master-orchestrator/scripts/validate_skills.py`
after editing any skill. When a feature lands, update
`references/capability-status.md` and `references/roadmap.md` in the same PR.
Index: `.claude/skills/GRANDPA_SKILLS_MASTER_INDEX.md`.
