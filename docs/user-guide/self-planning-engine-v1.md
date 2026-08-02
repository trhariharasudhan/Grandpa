# Self-Planning Engine V1

Self-Planning Engine V1 allows Grandpa to automatically create, maintain, and evolve project roadmaps that are genuinely goal-aware and project-aware.

---

## Architecture & Design

### 1. Goal Classification
Deterministic keyword-based and stack-based classification maps incoming requirements into 15 standard developer task categories, including:
- `backend_api`
- `frontend_ui`
- `browser_automation`
- `desktop_automation`
- `voice_assistant`
- `memory_system`
- `database_feature`
- `authentication`
- `testing_quality`
- `deployment`
- `documentation`
- `bug_fix`
- `refactor`
- `research`
- `unknown`

### 2. Project-Type Detection
Inspects the repository structure looking for indicators such as `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile`, and searches for imported frameworks (e.g. FastAPI, React, Flutter, Android/Kotlin) to gather structured evidence.

---

## Milestone & Task Model

Milestones and tasks generated dynamically include specific criteria:
- **Milestone fields**: `milestone_id`, `title`, `description`, `rationale`, `status`, `priority`, `dependencies`, `acceptance_criteria`, `validation_strategy`.
- **Task fields**: `task_id`, `milestone_id`, `title`, `description`, `rationale`, `status`, `priority`, `dependencies`, `affected_areas`, `expected_artifacts`, `acceptance_criteria`, `validation_commands`, `risk_level`.

---

## CLI Reference

### 1. Creating Roadmap
```bash
# Create a new goal-aware roadmap
$ grandpa roadmap create "Build browser automation"

# Merge new goals into the existing roadmap
$ grandpa roadmap create "FastAPI authentication" --merge

# Replace the current roadmap completely (requires confirmation)
$ grandpa roadmap create "FastAPI authentication" --replace
```

### 2. Milestone Expansion
```bash
$ grandpa roadmap expand ms_core -t tsk_custom --title "Implementation details"
```

### 3. Task Regeneration
```bash
$ grandpa roadmap regenerate task task_init
```

### 4. Graph Visualization
Outputs a Mermaid DAG graph representation:
```bash
$ grandpa roadmap graph
```

### 5. Archiving
Confirms and archives the current roadmap state:
```bash
$ grandpa roadmap archive
```

### 6. Validation
Validates cyclical links, duplicate IDs, and orphan references:
```bash
$ grandpa roadmap validate
```

---

## Safety Guidelines
Roadmap creation operations are strictly **planning-only**. They do not:
- Edit project source code files
- Execute active code runtimes or command processes
- Write to git repository state or history logs
