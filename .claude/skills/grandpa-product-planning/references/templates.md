# Planning templates

Copy, fill, and delete sections that do not apply. Keep a feature brief to one
page.

## Feature brief

```markdown
# <Feature name> (proposed milestone: <series><n>)

## Goal
<One sentence, in Captain's words: what he can do afterwards.>

## Current state
- Exists / partial / planned / missing: <which>, evidence: <path or command>
- Related code: <paths>

## Scope
- In: <bullets>
- Out (non-goals): <bullets>

## User flow
1. <Captain says / types ...>
2. <Grandpa does ...>
3. <Grandpa answers / asks to confirm ...>

## Acceptance criteria (each one measurable)
| # | Criterion | How it is checked |
|---|---|---|
| 1 | <...> | <test path / run_e2e / manual QA doc> |

## Safety
- New actions and risk tiers: <action: LOW/MEDIUM/HIGH, confirm?>
- Trust boundary moved? <yes/no, which> → security review needed: <yes/no>
- Data written under GRANDPA_HOME: <files>

## Dependencies
- Optional extras / new packages: <none or list, with reason>
- Skills that implement it: <grandpa-...>

## Milestones
| Tag | PR scope | Tests |
|---|---|---|

## Open questions (only those that change the plan)
```

## PRD (multi-milestone theme)

```markdown
# <Theme> PRD

1. Problem and who has it (Captain's daily use, with an example)
2. Goals and success metrics (numbers)
3. Non-goals
4. Current state with evidence
5. Requirements
   - Functional (numbered, testable)
   - Non-functional: latency on the target machine, RAM, offline behaviour,
     missing-dependency behaviour, Windows versions
6. Design overview (link the architecture review / ADR)
7. Security and privacy (risk tiers, data stored, consent)
8. Milestones and order, with what each unlocks
9. Risks and mitigations
10. Rollout: config flag default, doctor line, docs to update
```

## SRS-style requirement line

`REQ-<area>-<n>: When <trigger>, Grandpa shall <behaviour> within <limit>,
verified by <test/manual QA>.`

Example: `REQ-VOICE-3: When Captain holds Ctrl+Win and says "volume 30",
Grandpa shall set the volume to 30% within 3 s on the target machine, verified
by docs/testing/push-to-talk-manual-qa.md step 4.`
