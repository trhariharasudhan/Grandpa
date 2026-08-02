# Project Engineer Mode V1

Project Engineer Mode V1 allows Grandpa to act as an automated software project engineer. It evaluates active project configurations, analyzes roadmaps, tracks completed and blocked milestones, checks branch and code health, and recommends structured work packages.

---

## Prioritization Logic

Milestones and tasks are analyzed and recommended following a strict priority order:

1. **Blockers**: Active blockers in milestones or tasks are prioritized first to resolve bottlenecks.
2. **Current Milestone**: Recommends dependency-free tasks from the active milestone.
3. **Dependencies**: Ensures no task is recommended unless all its dependencies are fully completed.
4. **Roadmap Order**: Recommends planned milestones from the roadmap sequentially.

---

## CLI Reference

### 1. `grandpa project plan`
Generate an engineering plan for the next milestone with reasoning.

```bash
$ grandpa project plan
Recommended Milestone: Milestone_1
Reasoning: Milestone 'Milestone_1' is active. Task [t1] has all dependencies met and is prioritized.
Next Task  : [t1] Implement core interface
```

### 2. `grandpa project next-task`
Identify and show the next ready task to work on.

```bash
$ grandpa project next-task
Next Task: [t1] Implement core interface
Reason   : Milestone 'Milestone_1' is active. Task [t1] has all dependencies met and is prioritized.
```

### 3. `grandpa project work-package`
Generate a structured engineering work package showing state details, recommended milestone/task, task breakdown, validation checklist, and risk assessment.

```bash
$ grandpa project work-package
Project: ChronoBot
Current State: Milestone_1 / main
Repository Health: HEALTHY

Recommended Milestone: Milestone_1

Reason:
Milestone 'Milestone_1' is active. Task [t1] has all dependencies met and is prioritized.

Tasks:
1. [t1] Implement core interface (Priority: HIGH, Status: pending)
2. Verify dependencies: []
3. Implement core functionality for 'Implement core interface'
4. Run focused validation checks

Validation:
- pytest tests/
- uv run ruff check src tests
- python -m compileall -q src tests scripts

Risk:
LOW
```

### 4. `grandpa project blockers`
List all active blockers for milestones or tasks.

```bash
$ grandpa project blockers
Blocked Milestones:
  - (None)
Blocked Tasks:
  - (None)
```

---

## Agent Runtime Integration

You can invoke the Project Engineer Mode directly through chat goals:

- `Continue project`
- `What should I work on next?`
- `Plan next milestone`
- `Generate work package`
