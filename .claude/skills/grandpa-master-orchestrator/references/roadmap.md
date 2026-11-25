# GRANDPA roadmap and milestone history

Shared knowledge. Read this before you propose new work, so you build on what
landed and do not redo it. Built from `git log origin/main` @ `fde2164`
(2026-11-24). Re-run `git log --oneline origin/main | head -40` for anything newer.

## How milestones are named

PR titles carry a **letter + number** milestone tag, for example
`[F1] Workflows: ...` or `feat(server): ... (P2) (#66)`. No tracked file defines
the series. The letters below are inferred from the merged PRs. **C was used
twice**: C0–C14 (Aug 2026) were stabilisation fixes, and C1–C4 (Nov 2026) are
screen features. When you plan new work, propose the next free number in the
right series and say it is a proposal.

| Series | Area (inferred) | Merged examples |
|---|---|---|
| A | Avatar window | A1–A7 (A7 = performance budget) |
| B | Hands-free voice and Captain's voice | B1 wake word, B2 always listening + barge-in, B5 hands-free commands, B6 cloned voice |
| C (Aug) | Stabilisation, Windows CI, attribution | C0–C14 |
| C (Nov) | Screen understanding | C1 grandpa-eyes, C2 read window, C3 press button, C4 private apps |
| E | Start-up and platform | E0 `grandpa.cmd` launcher, E1 encrypted credentials, E2 Rust optional |
| F | Workflows | F1 YAML workflows, F2 triggers, F3 morning routine |
| G | Extensions | G1 stdio MCP servers, G2 plugins |
| H | Cloud voice | H1 ElevenLabs cache |
| O | Odin models | O3 Odin-1 LoRA training kit |
| P | Setup and home server | P1 one-command install + first-run wizard, P2 Pironman headless server |
| V1-T | Routing phrases through the action layer | V1-T6 power keywords, V1-T7 `grandpa jarvis` via the action layer |
| (untagged) | Grandpa's own offline voice | Piper training set and Colab notebook (#54, #67) |

## Status documents (newest first; trust code over all of them)

| Document | Date | Use it for |
|---|---|---|
| `capability-status.md` (this skill) | 2026-11-24 | what is implemented, partial, planned |
| `docs/MVP-STATUS.md` | 2026-10-07 | the nine MVP items, verified by running them |
| `docs/audit/CAPABILITY-MAP.md` | 2026-10-27 | 96 capabilities with run evidence |
| `docs/audit/FEATURE-INVENTORY*.md` | 2026-09 | older inventory |
| `docs/audit/DEFERRED.md` | — | code kept on purpose and debt to remove later |
| `docs/architecture/ARCHITECTURE_DECISIONS.md` | 2026-08-26 | AD-001..AD-022 |
| `CHANGELOG.md` `[Unreleased]` | live | what changed since the last release |

## Open themes worth planning next (from the audit, not yet decided by Captain)

These are candidates, not commitments. Each needs Captain's go-ahead.

1. Hands-free voice reliability (VAD is Partial; push-to-talk is the recommended mode).
2. Goal understanding and multi-step agents (CAPABILITY-MAP rates goal understanding BROKEN).
3. One memory facade (AD-010; two memory systems, `memory.db` has two writers).
4. Wire or delete orphaned security code (AD-013; injection scanner, subprocess sandbox).
5. Fix the autotag workflow (it dispatches a missing `desktop.yml`).
6. Smart home and IoT (future phase; no code yet).

Update this file when a milestone merges: add it to the table and remove it from
the open themes.
