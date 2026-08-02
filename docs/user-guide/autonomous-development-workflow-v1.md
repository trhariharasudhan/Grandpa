# Autonomous Development Workflow V1

The Autonomous Development Workflow V1 empowers Grandpa to manage and continue long-running developer projects contextually and robustly. It tracks milestones, handles task dependencies, manages state snapshots, and integrates with global short-term and long-term memory.

## Architecture

The workflow consists of the following modules under `src/grandpa/agent/development/`:

1. **Project State Tracker (`tracker.py`)**: Persists active milestones, last completed features, and active task states in `.grandpa/development_state.json`.
2. **Task Registry (`models.py`)**: Manages individual tasks, priority levels, and dependency chains.
3. **Roadmap Memory (`models.py`)**: Tracks completed, current, planned, and blocked milestones.
4. **Checkpoint System (`checkpoint.py`)**: Snapshots the complete project state and provides validation checks (verifying branch/health compatibility).
5. **Continuation Engine (`engine.py`)**: Classifies intents and generates multi-step plans for goals (e.g., `Continue Grandpa project`).

---

## CLI Reference

### 1. `grandpa project status`
View the active tracker status, repository branch, compilation health, active milestone, and task counts.

```bash
$ grandpa project status
Project Name      : Grandpa
Project Path      : D:\Grandpa
Active Branch     : main
Repository Health : HEALTHY
Current Milestone : Milestone V1
Next Milestone    : Milestone V2
Completed Tasks   : 3
Pending Tasks     : 2
```

### 2. `grandpa project roadmap`
Show all milestones partitioned by completion/planned/blocked status.

```bash
$ grandpa project roadmap
Completed Milestones:
  - Setup Environment
Current Milestone: Milestone V1
Planned Milestones:
  - Milestone V2
Blocked Milestones:
  - (None)
```

### 3. `grandpa project next`
Resolve and display the next pending task based on priority levels and dependency resolution.

```bash
$ grandpa project next
Next Task: [tsk_004] Implement memory syncing
Priority : HIGH
Depends  : ['tsk_002', 'tsk_003']
```

### 4. `grandpa project checkpoint`
Save, load, and validate state snapshot checkpoints.

```bash
# Save a checkpoint
$ grandpa project checkpoint save --id init_backup
Saved checkpoint 'init_backup' successfully.

# Load/Restore a checkpoint
$ grandpa project checkpoint load init_backup
Restored project state from checkpoint 'init_backup'.
```

### 5. `grandpa project resume`
Resume work on the current project, evaluating workspace diagnostics and next task.

```bash
$ grandpa project resume
Resuming project 'Grandpa'.
Next task identified: [tsk_004] 'Implement memory syncing' (Priority: HIGH). Dependencies: ['tsk_002', 'tsk_003'].
```

---

## Limitations

1. **Single-Project Scope**: Currently tracks state at the root of a resolved project path via `.grandpa/development_state.json`.
2. **Local Git-Awareness**: Diagnoses branch and compile status locally; does not poll remote origin repositories automatically.
3. **Focused Compilation Checks**: Compile validation checks standard syntax validity using `compileall`; it does not run test suites automatically during state tracking updates.
