# Multi-Project Memory V1

Multi-Project Memory V1 allows Grandpa to manage, track, and switch between multiple software development projects concurrently. It enforces project-specific memory isolation and active project tracking, allowing users to switch contexts seamlessly.

---

## Architecture

The multi-project management architecture consists of the following components under `src/grandpa/agent/development/`:

1. **Project Registry (`registry.py`)**: `MultiProjectRegistry` loads and saves global metadata (such as paths, IDs, branches, and health status) into `~/.grandpa/projects_registry.json`.
2. **Project State isolation**: Each project stores its own tasks, milestones, checkpoints, and continuation logs inside its own directory structure under `.grandpa/development_state.json`.
3. **Intent Routing & Runtime Integration**: The `AgentRuntime` intercepts multi-project queries and automatically switches the active project context if an explicit project is specified in the goal.

---

## Memory Structure

### 1. Global Project Registry (`~/.grandpa/projects_registry.json`)
Tracks the active project identifier and the list of registered project paths.

```json
{
  "active_project_id": "prj_chronobot",
  "projects": {
    "prj_chronobot": {
      "project_id": "prj_chronobot",
      "project_name": "ChronoBot",
      "project_path": "D:\\ChronoBot",
      "description": "Time tracking assistant",
      "active_branch": "main",
      "repository_health": "healthy"
    }
  }
}
```

### 2. Local Project Memory (`<project_path>/.grandpa/development_state.json`)
Isolates milestone and task tracking specific to the project directory.

---

## CLI Reference

### 1. `grandpa project create <name> <path>`
Create a new project folder, initialize its `.grandpa` workspace, and register it.

```bash
$ grandpa project create ChronoBot D:\ChronoBot
Created and registered project 'ChronoBot' [prj_chronobot] at D:\ChronoBot.
```

### 2. `grandpa project register <name> <path>`
Register an existing project path in the global registry.

```bash
$ grandpa project register MotoCompass D:\MotoCompass
Registered project 'MotoCompass' [prj_motocompass] at D:\MotoCompass.
```

### 3. `grandpa project list`
List all registered projects, highlighting the currently active project with an asterisk `*`.

```bash
$ grandpa project list
Registered Projects:
* ChronoBot [prj_chronobot] - D:\ChronoBot (healthy)
  MotoCompass [prj_motocompass] - D:\MotoCompass (healthy)
```

### 4. `grandpa project switch <identifier>`
Switch active project context using name or ID.

```bash
$ grandpa project switch MotoCompass
Switched active project context to 'MotoCompass' [prj_motocompass].
```

### 5. `grandpa project current`
Show the currently active project context name.

```bash
$ grandpa project current
Active Project: MotoCompass [prj_motocompass]
```

### 6. `grandpa project context`
Show detailed context, branch, and health summary for the active project.

```bash
$ grandpa project context
Active Project    : MotoCompass [prj_motocompass]
Description       : None
Project Path      : D:\MotoCompass
Active Branch     : main
Repository Health : HEALTHY
Current Milestone : None
Next Milestone    : None
Next Task         : None
Completed Tasks   : 0
Pending Tasks     : 0
```
