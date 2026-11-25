---
name: grandpa-product-planning
description: Turn an idea for Grandpa into a buildable plan - clarify the requirement, check what already exists, write a feature brief or PRD/spec with measurable acceptance criteria, slice it into milestone-sized PRs, and keep the roadmap and status documents current. Use when Captain says "I want Grandpa to...", asks what to build next, asks for a spec, PRD, SRS or roadmap, or when a request is too big or vague to code directly.
---

# GRANDPA product planning

Grandpa is not built from zero. It already has ~170 catalogued actions, voice,
screen, memory, workflows, plugins, an API server and an avatar. Most good
plans **extend or finish** something. The most expensive mistake is planning a
feature that already exists or contradicts a recorded decision.

Shared knowledge lives in the `grandpa-master-orchestrator` skill:
`references/project-vision.md` (vision, priorities, target machine),
`references/roadmap.md` (milestone history) and
`references/capability-status.md`. Read the parts you need first.

## Authority

Captain owns scope and priority. You propose, with a recommendation and the
trade-off. Ask only questions whose answer changes the plan. Everything else,
decide sensibly, state the assumption, and move on.

## Workflow

1. **Restate the goal in the user's terms.** One sentence about what Captain
   will be able to do, not about code. Example: "Say 'Hey Grandpa, read my
   last email' and hear the subject and sender."
2. **Check what exists.**
   - `capability-status.md` and `roadmap.md` (orchestrator skill).
   - `docs/audit/CAPABILITY-MAP.md` for run evidence; `docs/audit/DEFERRED.md`
     for code kept on purpose.
   - Search the code: `rg -n "<keyword>" src/grandpa`,
     `uv run grandpa --help`, and the action catalogue
     (`grandpa-action-layer` has `scripts/catalogue_report.py`).
   - Classify the result: **exists** (then it's a bug or a UX gap), **partial**
     (finish it), **planned** (decide it), or **missing** (new feature).
3. **Check it against the product rules.** Local-first, typed actions instead of
   shell, confirmation for risky actions, graceful when optional dependencies
   are missing, Windows-first. A cloud path is only ever an explicit opt-in.
4. **Write the brief.** Use [references/templates.md](references/templates.md).
   One page for a feature; a PRD only for a multi-milestone theme.
5. **Write acceptance criteria that can be measured.** The repo's style is to
   measure, not to assert: "8/8 phrases route through the action layer",
   "drift < 100 ms", "ring only if over 20% GPU or 300 MB". Each criterion names
   how it is checked: a test, `scripts/run_e2e.py`, or a manual QA script in
   `docs/testing/*-manual-qa.md`.
6. **Slice into milestones.** Each slice is one focused, behaviour-preserving PR
   with its own tests (CONTRIBUTING). Give each a proposed tag in the right
   series (`roadmap.md`), e.g. `C5`, and say it is a proposal.
7. **Mark risk and dependencies.** For each slice, give the risk tier of any new
   action (LOW/MEDIUM/HIGH) and whether `grandpa-security-governance` must
   review it. List which specialist skills implement it.
8. **Record it.** Plans for review go to Captain first. After approval, keep
   `docs/development/roadmap.md` and `CHANGELOG.md` (`[Unreleased]`) current
   in the implementing PRs, and update the orchestrator's `roadmap.md` and
   `capability-status.md` when a slice merges.

## Sizing guide

| Size | Signs | Plan form |
|---|---|---|
| Small | one domain, one action or one bug | a short brief in the PR description |
| Medium | 2–4 PRs, one subsystem | feature brief + milestone list |
| Large | crosses subsystems, needs a data migration or a new trust boundary | PRD + architecture review (`grandpa-architecture-design`) + Captain's explicit go-ahead before code |

## Quality bar for a plan

- Every claim about the current state cites a path or a command.
- Implemented, partial, planned and missing are kept distinct.
- Windows-only behaviour is called out, because CI on Linux cannot prove it.
- It says what will **not** be done (non-goals), so scope does not creep.
- No secrets, personal data or real account names in plan documents.

## Known planning traps in this repo

- The README's sentence about "no plugin runtime, no mobile client" is stale;
  plugins and phone pairing exist. Check code, not that sentence.
- Several architecture decisions (AD-001..AD-022) are still "Needs
  ratification". A plan that depends on one must say so.
- The milestone letter C was reused (Aug stabilisation, Nov screen). Use the
  full title when you cite one.
- Reminders often "don't fire" because `scheduler.enabled` is off by default.
  That is configuration, not a missing feature.

## Hand-offs

- Design of the solution: `grandpa-architecture-design`.
- Unknown technology or feasibility: `grandpa-research-prototyping` first.
- Implementation: the domain skill named in the routing table of
  `grandpa-master-orchestrator`.
