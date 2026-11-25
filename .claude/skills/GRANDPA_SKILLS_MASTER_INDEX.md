# GRANDPA Claude Skills – Master Index

Project-level Claude Code skills for developing **GRANDPA** (Generative Reasoning
Autonomous Native Digital Personal Agent; assistant identity **ODIN**), the
Windows-first, offline-first personal AI assistant in this repository.

These are *developer* skills for Claude. They are unrelated to Grandpa's own
runtime "skills" (`src/grandpa/skills/`, TOML files run by the product).

- Evidence and reasoning behind this set: [GRANDPA_SKILLS_AUDIT_REPORT.md](GRANDPA_SKILLS_AUDIT_REPORT.md)
- Baseline: `main` @ `fde2164` (2026-11-24). Facts in the skills were checked against that tree.

## Skills

| Skill | Tier | Purpose | Use when | Depends on | Supporting files |
|---|---|---|---|---|---|
| `grandpa-dev-orchestrator` | Master | Project map, shared safety rules, routing to specialists | Start of any GRANDPA task; unsure which area a change touches | – | `references/architecture-map.md`, `capability-status.md`, `governance.md`, `skill-routing.md`, `scripts/validate_skills.py` |
| `grandpa-action-layer` | Essential | Catalogue, risk tiers, confirmation, executor, tool loop, desktop/app/file/browser/etc. domains | Adding/changing an action or tool; "model did not call the tool" | orchestrator, security, testing | `references/catalogue-guide.md`, `scripts/catalogue_report.py` |
| `grandpa-testing-qa` | Essential | Test scope, guards, sandboxing, CI parity, commit guard, e2e/release, doctor/oops | After every change; failing/hanging tests; before committing | orchestrator | `references/test-infrastructure.md`, `scripts/which_tests.py` |
| `grandpa-security-governance` | Essential | Trust boundaries and review lens | Any change to auth, approvals, secrets, devices, plugins, MCP, screen privacy, tiers | orchestrator, action-layer | `references/boundaries.md` |
| `grandpa-voice-pipeline` | Essential | Mic, PTT, VAD, wake word, STT, TTS backends, bubble/avatar speech | Voice bugs, wake tuning, new TTS backend | action-layer, local-models, testing | `references/voice-architecture.md` |
| `grandpa-local-models` | Recommended | Ollama runtime, Odin roles, Modelfiles, eval, fine-tune data | Model choice, latency, new role, LoRA data | testing | `references/odin-models.md` |
| `grandpa-memory-knowledge` | Recommended | Personal memory, Memory V1, RAG/knowledge, embeddings, migrations | Remember/recall bugs, memory features, DB schema changes | local-models, security, testing | `references/memory-stores.md` |
| `grandpa-screen-vision` | Recommended | Capture, OCR, privacy gate, grandpa-eyes, UIA read/click | Screen features, OCR quality | action-layer, security, local-models | – |
| `grandpa-workflows-extensions` | Recommended | YAML workflows, triggers, reminders/routines, plugins, MCP servers | Automations, routines, plugins, MCP tools, reminders not firing | action-layer, security | `references/formats.md` |
| `grandpa-api-server` | Recommended | FastAPI server, auth, device routes, headless node | New/changed endpoints, `grandpa serve`, Pironman node | action-layer, security, testing | – |

Every specialist assumes the orchestrator's rules (sandboxed `GRANDPA_HOME`,
no real actuation in tests, one action door, no secrets, owner approval for
destructive steps) and ends with `grandpa-testing-qa` verification.

## Routing at a glance

```
task ──► grandpa-dev-orchestrator ──► specialist(s) ──► grandpa-security-governance (if a boundary moves)
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
  upload it under Settings → Capabilities → Skills. The frontmatter only uses portable keys
  (`name`, `description`), so it is accepted there too. Scripts that run `uv`/`grandpa` only work
  where the repo is checked out.
- **Invoke explicitly:** type `/grandpa-action-layer` (etc.) in Claude Code; otherwise Claude
  loads a skill when the request matches its description.

## Validation

```bash
python .claude/skills/grandpa-dev-orchestrator/scripts/validate_skills.py
```

Checks folder/name match, kebab-case names, frontmatter validity and portable keys,
description length (40–1024), body under 500 lines, relative links, script
compilation, secret-looking strings, and that this index lists exactly the skills on disk.

## Maintenance

1. **When code changes a fact a skill states** (a path, a command, a count, a default), update the
   skill in the same PR. Counts are dated "verified …"; re-measure rather than edit by hand
   (e.g. `catalogue_report.py --summary` for action counts).
2. **When a feature lands or is removed**, update
   `grandpa-dev-orchestrator/references/capability-status.md`.
3. **New skill:** only when an area has independent, recurring workflows that do not fit an existing
   skill (see the criteria in the audit report §5). Add it to the table above and to
   `references/skill-routing.md`, then run the validator.
4. **Keep SKILL.md short.** Put detail in `references/`; keep instructions actionable and evidence-based;
   mark unknowns as unknown.
5. **Never** put secrets, personal data, or machine-specific paths in a skill.
