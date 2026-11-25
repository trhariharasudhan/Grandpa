# GRANDPA Claude Skills – Master Index

Project-level Claude Code skills for developing **GRANDPA** (Generative Reasoning
Autonomous Native Digital Personal Agent), the Windows-first, offline-first
personal AI assistant in this repository. The assistant calls itself Grandpa;
**Odin** is the codename of its local model family (`prompt/identity.py`).

These are *developer* skills for Claude. They are unrelated to Grandpa's own
runtime "skills" (`src/grandpa/skills/`, TOML files run by the product).

- Evidence and reasoning behind this set: [GRANDPA_SKILLS_AUDIT_REPORT.md](GRANDPA_SKILLS_AUDIT_REPORT.md)
- Baseline: `main` @ `fde2164` (2026-11-24). Facts in the skills were checked against that tree.

## Skills (19, grouped by domain)

| Skill | Domain | Purpose | Use when | Supporting files |
|---|---|---|---|---|
| `grandpa-master-orchestrator` | Master | Shared project knowledge, safety rules, routing, multi-skill coordination | Start of any GRANDPA task | `references/project-vision.md`, `roadmap.md`, `capability-status.md`, `architecture-map.md`, `governance.md`, `skill-routing.md`, `scripts/validate_skills.py` |
| `grandpa-product-planning` | Plan & design | Requirements, feature briefs, PRD/SRS, milestones, roadmap upkeep | A new idea, "what next", a spec | `references/templates.md` |
| `grandpa-architecture-design` | Plan & design | Where code lives, seams, refactors of duplicated subsystems, ADRs | New subsystem, refactor, cross-package change | `references/adr-template.md` |
| `grandpa-research-prototyping` | Plan & design | Compare options against Grandpa's constraints, spikes, survey docs, future-phase feasibility | "Which library/model?", "is X possible?", new dependency | `references/survey-template.md` |
| `grandpa-python-engineering` | Build | House Python style: uv, ruff, 3.10, config, CLI, optional deps, logging, errors, files, subprocess, Windows | Writing or reviewing any Python | – |
| `grandpa-agent-engineering` | Build: intelligence | Message → reply path, prompts, identity, context window, brain, cleanup, agents and planners | Wrong/forgetful replies, prompt changes, agent loops | – |
| `grandpa-local-models` | Build: intelligence | Ollama runtime, Odin roles, Modelfiles, eval, fine-tune data | Model choice, latency, new role, LoRA data | `references/odin-models.md` |
| `grandpa-memory-knowledge` | Build: intelligence | Personal memory, Memory V1, RAG, embeddings, SQLite stores, migrations | Remember/recall bugs, memory features, schema changes | `references/memory-stores.md` |
| `grandpa-voice-pipeline` | Build: interaction | Mic, PTT, VAD, wake word, STT, TTS backends, voice data | Voice bugs, wake tuning, new TTS backend | `references/voice-architecture.md` |
| `grandpa-screen-vision` | Build: interaction | Capture, OCR, privacy gate, grandpa-eyes, UIA read/click | Screen features, OCR quality | – |
| `grandpa-desktop-ui` | Build: interaction | Bubble, orb, palette, avatar window, lip-sync display, tray | UI look, states, focus, GPU budget | – |
| `grandpa-action-layer` | Build: control | Catalogue, risk tiers, confirmation, executor, tool loop, desktop domains | Adding/changing an action or tool | `references/catalogue-guide.md`, `scripts/catalogue_report.py` |
| `grandpa-workflows-extensions` | Build: control | YAML workflows, triggers, reminders/routines, plugins, MCP servers | Automations, plugins, MCP, reminders not firing | `references/formats.md` |
| `grandpa-api-server` | Build: connect | FastAPI server, auth, device routes, headless node | Endpoints, `grandpa serve`, Pironman node | – |
| `grandpa-external-integrations` | Build: connect | Gmail, Calendar, web search, weather, ElevenLabs, new HTTP APIs | Any integration, OAuth, API key | – |
| `grandpa-security-governance` | Quality | Trust boundaries and security review lens | Auth, approvals, secrets, devices, plugins, MCP, privacy, tiers | `references/boundaries.md` |
| `grandpa-testing-qa` | Quality | Test scope, guards, sandboxing, CI parity, commit guard, e2e, release gate | After every change; failing tests | `references/test-infrastructure.md`, `scripts/which_tests.py` |
| `grandpa-debugging-performance` | Quality | Root cause, doctor/oops/stall/telemetry evidence, latency, RAM, GPU | "It doesn't work / hangs / is slow" | – |
| `grandpa-devops-release` | Delivery | Git workflow, CI jobs, versions, release gate, installer, Docker | PRs, red CI, releases, installer | – |

**Future phase (not built on purpose):** `grandpa-smart-home-iot` and
`grandpa-hardware-robotics`. Grandpa has no smart-home, IoT or robotics code yet;
create these skills when that work starts. Until then
`grandpa-research-prototyping` covers feasibility.

### How the 50-item candidate list was consolidated

Every candidate maps to one owner, so nothing is lost and no two skills compete
for the same request:

| Candidates | Owner |
|---|---|
| master orchestrator, project discovery, documentation (shared knowledge) | `grandpa-master-orchestrator` |
| requirements, product management, roadmap, project documentation (PRD/SRS) | `grandpa-product-planning` |
| system architecture, module design, scalability, application integration, refactoring | `grandpa-architecture-design` |
| technical research, technology selection, research & experimentation | `grandpa-research-prototyping` |
| python engineering, backend development, configuration, file system, error handling, logging, dependency management | `grandpa-python-engineering` |
| AI engineering, LLM/prompting, agents, agent planning, context engineering, conversation, multimodal routing, localization | `grandpa-agent-engineering` |
| local model engineering, model routing | `grandpa-local-models` |
| memory engineering, RAG/knowledge, database engineering, backup & recovery | `grandpa-memory-knowledge` |
| voice engineering, speech recognition, speech synthesis, wake word, audio | `grandpa-voice-pipeline` |
| vision engineering | `grandpa-screen-vision` |
| UI/UX, design system, frontend, desktop development, accessibility | `grandpa-desktop-ui` |
| tool calling, computer control, OS integration, process management, permission mechanics | `grandpa-action-layer` |
| automation engineering, task scheduling | `grandpa-workflows-extensions` |
| API engineering | `grandpa-api-server` |
| API integration (third-party) | `grandpa-external-integrations` |
| security engineering, security architecture, permission policy | `grandpa-security-governance` |
| testing & quality, code review (with Claude Code's built-in `/code-review`) | `grandpa-testing-qa` |
| debugging, performance optimisation, logging & monitoring | `grandpa-debugging-performance` |
| DevOps & CI/CD, git workflow, release engineering | `grandpa-devops-release` |
| IoT, home automation, network engineering, hardware, robotics | future skills (above) |

Every specialist assumes the orchestrator's rules (sandboxed `GRANDPA_HOME`,
no real actuation in tests, one action door, no secrets, owner approval for
destructive steps) and ends with `grandpa-testing-qa` verification.

## Routing at a glance

```
task ──► grandpa-master-orchestrator ──► specialist(s) ──► grandpa-security-governance (if a boundary moves)
                                                    └─► grandpa-testing-qa (always)
```

## Installation

The skills are project skills: Claude Code discovers `.claude/skills/<name>/SKILL.md`
automatically when it runs inside this repository. No install step is needed
after the branch is merged.

- **Use in another checkout or worktree:** they come with the repo (`git pull`).
- **Use everywhere on one machine (personal):** copy the folders to `~/.claude/skills/`
  (Windows: `%USERPROFILE%\.claude\skills\`). A personal copy overrides the project copy of the same name.
  ```powershell
  Copy-Item -Recurse .claude\skills\grandpa-* $env:USERPROFILE\.claude\skills\
  ```
- **claude.ai / Claude desktop app:** zip one skill folder (the folder itself at the zip root) and
  upload it under Settings → Capabilities → Skills. One zip is one skill. Always add
  `grandpa-master-orchestrator`, because the specialists refer to its shared knowledge by name. The frontmatter only uses portable keys
  (`name`, `description`), so it is accepted there too. Scripts that run `uv`/`grandpa` only work
  where the repo is checked out.
- **Invoke explicitly:** type `/grandpa-action-layer` (etc.) in Claude Code; otherwise Claude
  loads a skill when the request matches its description.

## Validation

```bash
python .claude/skills/grandpa-master-orchestrator/scripts/validate_skills.py
```

Checks folder/name match, kebab-case names, frontmatter validity and portable keys,
description length (40–1024), body under 500 lines, relative links, script
compilation, secret-looking strings, and that this index lists exactly the skills on disk.

## Maintenance

1. **When code changes a fact a skill states** (a path, a command, a count, a default), update the
   skill in the same PR. Counts are dated "verified …"; re-measure rather than edit by hand
   (e.g. `catalogue_report.py --summary` for action counts).
2. **When a feature lands or is removed**, update
   `grandpa-master-orchestrator/references/capability-status.md`.
3. **New skill:** only when an area has independent, recurring workflows that do not fit an existing
   skill (see the criteria in the audit report §5). Add it to the table above and to
   `references/skill-routing.md`, then run the validator.
4. **Keep SKILL.md short.** Put detail in `references/`; keep instructions actionable and evidence-based;
   mark unknowns as unknown.
5. **Never** put secrets, personal data, or machine-specific paths in a skill.
