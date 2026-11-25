# Skill routing and overlaps

Skills are loaded on demand; never assume another skill is already in context.
Each specialist restates only the rules it enforces and links here for the rest.

## Dependency map

```
                         grandpa-dev-orchestrator  (map, rules, routing)
                                    │
   ┌──────────────┬─────────────┬───┴─────────┬──────────────┬───────────────┐
   ▼              ▼             ▼             ▼              ▼               ▼
action-layer   voice-pipeline  screen-vision  memory-knowledge  local-models  workflows-extensions
   │  ▲            │              │              │               │               │
   │  └────────────┴──────────────┴──────────────┴───────────────┴───────────────┘
   │        (every actuation routes through the action layer's executor)
   ▼
security-governance  ◄── api-server (auth, devices, headless)
   │
   ▼
testing-qa  (every skill ends here: focused tests, ruff, honest report)
```

## Overlap resolution

| Situation | Owner | Also consult |
|---|---|---|
| New catalogue action for screen/voice/memory | `grandpa-action-layer` (catalogue entry) | the domain skill (implementation) |
| Changing a risk tier or confirmation rule | `grandpa-security-governance` (decision) | `grandpa-action-layer` (mechanics) |
| New HTTP route that runs actions | `grandpa-api-server` | `grandpa-security-governance`, `grandpa-action-layer` |
| Plugin or MCP permission semantics | `grandpa-workflows-extensions` | `grandpa-security-governance` |
| Embedding model choice | `grandpa-local-models` | `grandpa-memory-knowledge` |
| Voice says something the model generated | `grandpa-voice-pipeline` | `grandpa-local-models` |
| Test infrastructure itself (guards, conftest) | `grandpa-testing-qa` | — (full suite required) |

## Not covered by a dedicated skill (use the orchestrator + code)

- `agents/`, `agent/`, `planner/`, `kernel/` – duplicated, low recent activity; see `docs/architecture/MIGRATION_PLAN.md`.
- `ui/` avatar web assets (three.js) – small, specialised; follow `docs/testing/avatar-manual-qa.md`.
- `rust/` – inherited, optional; do not extend without the owner's decision.
- Gmail / Calendar / notes / downloads / web search domains – covered as action-layer domains.
