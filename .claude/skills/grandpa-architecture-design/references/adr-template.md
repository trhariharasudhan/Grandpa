# Architecture decision record template

Match the style of `docs/architecture/ARCHITECTURE_DECISIONS.md`: evidence
first, tagged facts, a clear decision, and a status Captain can ratify.

```markdown
## AD-0NN — <decision in one line>

**Status:** Proposed | Recommended | Needs ratification | Accepted | Superseded by AD-0MM
**Date:** YYYY-MM-DD

### Context
What problem forces a decision now. Cite paths, commands and numbers.
- [FACT] <verified statement> (`path/to/file.py:line`)
- [INFERENCE] <reasoned conclusion, marked as such>

### Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| A. Extend the existing module | | | |
| B. New package `grandpa/<x>/` | | | |
| C. Do nothing | | | |

### Decision
<The chosen option and the one-sentence reason.>

### Consequences
- Modules affected: <paths> and their disposition (CANONICAL/ABSORB/SHIM/...)
- Data: <stores touched under GRANDPA_HOME, migration needed?>
- Safety: <actions, risk tiers, trust boundaries>
- Tests that prove it: <paths>
- What becomes harder

### Follow-ups
- [ ] <task> (owner, milestone)
```

Keep one ADR per decision. When an ADR replaces another, edit the old one's
status to "Superseded by AD-0NN" instead of deleting it.
