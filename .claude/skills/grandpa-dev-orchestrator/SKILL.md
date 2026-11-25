---
name: grandpa-dev-orchestrator
description: Entry point for any development work on the GRANDPA (Grandpa / ODIN) Windows-first local AI assistant repo. Use at the start of a GRANDPA task to get the project map, the non-negotiable safety rules (GRANDPA_HOME sandbox, no real actuation in tests, confirmation gates), and to pick the right specialist skill (action layer, testing, security, voice, models, memory, screen, workflows/plugins/MCP, API server).
---

# GRANDPA development orchestrator

You are working on **Grandpa** (repo `trhariharasudhan/Grandpa`), a Windows-first,
offline-first personal AI assistant. "ODIN" is the internal codename of the
local model family (`grandpa-brain`, `grandpa-fast`, ...), not a separate program.
The Python package is `grandpa` under `src/grandpa/`; the console script is
`grandpa` (`grandpa.cli:main`).

This skill does three things: orients you, enforces the shared rules, and routes
you to a specialist skill. It does not repeat the specialists' content.

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

| Task touches | Use skill |
|---|---|
| Adding/changing an action, risk tier, confirmation, tool loop, `pc_control`, desktop/apps/files/browser/notes/downloads/gmail/calendar automation | `grandpa-action-layer` |
| Writing or running tests, CI, commit guard, release gate, `doctor`/`oops` debugging | `grandpa-testing-qa` |
| Auth, approvals, secrets, device pairing, plugin/MCP trust, screen privacy, injection, audit logs, any security review | `grandpa-security-governance` |
| Microphone, STT (faster-whisper), VAD, push-to-talk, wake word, TTS backends, bubble/avatar speech | `grandpa-voice-pipeline` |
| Ollama runtime, Odin roles, Modelfiles, model eval, tool-capable models, LoRA dataset/notebooks | `grandpa-local-models` |
| Personal memory, memory V1 store, knowledge/RAG, embeddings, SQLite stores | `grandpa-memory-knowledge` |
| Screenshots, OCR, grandpa-eyes, UI Automation, read window, screen click, privacy list | `grandpa-screen-vision` |
| YAML workflows, triggers, reminders/routines/scheduler, plugins (`plugin.toml`), stdio MCP servers | `grandpa-workflows-extensions` |
| FastAPI server, `/v1` + `/api` routes, headless Pironman node, phone device routes | `grandpa-api-server` |

Cross-cutting tasks: load the primary skill first, then `grandpa-security-governance`
if a trust boundary moves, and always finish with `grandpa-testing-qa`.
Routing details and overlaps: [references/skill-routing.md](references/skill-routing.md).

## 4. Standard workflow

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

Run `python .claude/skills/grandpa-dev-orchestrator/scripts/validate_skills.py`
after editing any skill. Update `references/capability-status.md` when a feature
lands. Index: `.claude/skills/GRANDPA_SKILLS_MASTER_INDEX.md`.
