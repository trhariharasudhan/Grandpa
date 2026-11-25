# Skill routing, overlaps and multi-skill recipes

Skills are loaded on demand; never assume another skill is already in context.
Each specialist restates only the rules it enforces and refers to the others by
name (not by file link, so each skill still works when uploaded on its own).

## Dependency map

```
                              grandpa-master-orchestrator
                 (vision, roadmap, status, architecture map, governance, routing)
                                          │
        ┌───────────── PLAN & DESIGN ─────┼──────────────────────────────┐
        │ product-planning → architecture-design ← research-prototyping  │
        └─────────────────────────────────┼──────────────────────────────┘
                                          ▼
   BUILD (python-engineering applies to all of these)
     intelligence: agent-engineering ─ local-models ─ memory-knowledge
     interaction:  voice-pipeline ─ screen-vision ─ desktop-ui
     control:      action-layer ◄── workflows-extensions
     connect:      api-server ─ external-integrations
          │   (every actuation goes through action-layer's executor)
          ▼
   QUALITY:  security-governance → testing-qa ; debugging-performance on demand
          ▼
   DELIVERY: devops-release
```

## Overlap resolution (who owns what)

| Situation | Owner | Also consult |
|---|---|---|
| New catalogue action for screen/voice/memory/integration | `grandpa-action-layer` (catalogue entry) | the domain skill (implementation) |
| Changing a risk tier or confirmation rule | `grandpa-security-governance` (decision) | `grandpa-action-layer` (mechanics) |
| Prompt text, conversation window, tool-loop behaviour | `grandpa-agent-engineering` | `grandpa-local-models` (model choice) |
| Model too slow | `grandpa-debugging-performance` (measure) | `grandpa-local-models` (keep_alive, role) |
| Avatar shows the wrong state | `grandpa-desktop-ui` | `grandpa-voice-pipeline` if speech-driven |
| Lip-sync timing | `grandpa-voice-pipeline` (audio) | `grandpa-desktop-ui` (display) |
| New HTTP route that runs actions | `grandpa-api-server` | `grandpa-security-governance`, `grandpa-action-layer` |
| Third-party API or OAuth | `grandpa-external-integrations` | `grandpa-security-governance` |
| Plugin or MCP permission semantics | `grandpa-workflows-extensions` | `grandpa-security-governance` |
| Embedding model choice | `grandpa-local-models` | `grandpa-memory-knowledge` |
| Schema change or migration of a user store | `grandpa-memory-knowledge` | `grandpa-architecture-design` (if structural) |
| Where a new module goes, refactors | `grandpa-architecture-design` | `grandpa-python-engineering` |
| New dependency | `grandpa-research-prototyping` (choose) | `grandpa-python-engineering` (add), `grandpa-devops-release` (lock, CI) |
| Test infrastructure itself (guards, conftest) | `grandpa-testing-qa` | — (full suite required) |
| Red CI job | `grandpa-devops-release` (which job, rules) | `grandpa-debugging-performance` (root cause) |

## Multi-skill recipes

**New feature, end to end**
1. `grandpa-product-planning` – brief, acceptance criteria, milestones.
2. `grandpa-architecture-design` – seam, package, actions and tiers (if structural).
3. Domain skill(s) + `grandpa-python-engineering` – implement.
4. `grandpa-security-governance` – if a trust boundary or risk tier moved.
5. `grandpa-testing-qa` – focused tests, then the PR via `grandpa-devops-release`.

**New outside service**: `grandpa-research-prototyping` (pick the API) →
`grandpa-external-integrations` (package pattern) → `grandpa-action-layer`
(catalogue) → `grandpa-security-governance` → `grandpa-testing-qa`.

**"Grandpa is slow / wrong"**: `grandpa-debugging-performance` (evidence, root
cause) → the owning skill for the fix → `grandpa-testing-qa`.

**Voice command end to end**: `grandpa-voice-pipeline` (hear) →
`grandpa-agent-engineering` (understand) → `grandpa-action-layer` (do) →
`grandpa-desktop-ui` (show) → `grandpa-testing-qa`.

## Areas with no dedicated skill (by design)

- `rust/` – inherited and optional since E2; don't extend without Captain's decision.
- `kernel/` (near-dead) vs `desktop/kernel/` (live) – see `grandpa-architecture-design`.
- Smart home, IoT, hardware, robotics – future phase; `grandpa-research-prototyping`
  until `grandpa-smart-home-iot` / `grandpa-hardware-robotics` are created.
