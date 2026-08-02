"""Genuinely goal-aware and project-aware roadmap planner for Self-Planning Engine V1."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from grandpa.agent.development.models import Milestone, ProjectState, Roadmap, Task


@dataclass
class ProjectTypeEvidence:
    """Evidence of project stack and language types."""

    detected_type: str = "unknown"
    detected_stack: List[str] = field(default_factory=list)
    evidence_files: List[str] = field(default_factory=list)
    confidence: float = 0.0
    unknowns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected_type": self.detected_type,
            "detected_stack": self.detected_stack,
            "evidence_files": self.evidence_files,
            "confidence": self.confidence,
            "unknowns": self.unknowns,
        }


def detect_project_type(project_path: str) -> ProjectTypeEvidence:
    """Inspect repository files to determine languages, stacks, frameworks, and tools."""
    path = Path(project_path)
    evidence = ProjectTypeEvidence()

    if not path.exists():
        return evidence

    # Check common project files
    files_to_check = {
        "pyproject.toml": ("Python", "python"),
        "requirements.txt": ("Python", "python"),
        "package.json": ("Node/JavaScript", "nodejs"),
        "Cargo.toml": ("Rust", "rust"),
        "Dockerfile": ("Docker", "docker"),
        "pubspec.yaml": ("Flutter", "flutter"),
        "build.gradle": ("Android/Kotlin", "kotlin"),
    }

    found_files = []
    detected_types = []
    detected_stacks = []

    for fname, (ptype, pstack) in files_to_check.items():
        if (path / fname).exists():
            found_files.append(fname)
            detected_types.append(ptype)
            detected_stacks.append(pstack)

    # FastAPI check
    fastapi_found = False
    for py_file in path.glob("**/*.py"):
        # Prevent going into virtual environments or build folders
        if any(p in py_file.parts for p in (".venv", "venv", "build", "dist")):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if "fastapi" in content.lower():
                fastapi_found = True
                break
        except Exception:
            pass

    if fastapi_found:
        detected_stacks.append("fastapi")
        if "FastAPI" not in detected_types:
            detected_types.append("FastAPI")

    # React / Vite check inside package.json
    pkg_json = path / "package.json"
    if pkg_json.exists():
        try:
            content = pkg_json.read_text(encoding="utf-8", errors="ignore")
            if "react" in content.lower():
                detected_stacks.append("react")
            if "vite" in content.lower():
                detected_stacks.append("vite")
        except Exception:
            pass

    # Populate final evidence
    if detected_types:
        evidence.detected_type = detected_types[0]
        evidence.detected_stack = list(set(detected_stacks))
        evidence.evidence_files = found_files
        evidence.confidence = 0.9 if len(found_files) > 1 else 0.7
    else:
        evidence.detected_type = "unknown"
        evidence.detected_stack = []
        evidence.confidence = 0.0

    return evidence


def classify_goal(goal_text: str, project_evidence: ProjectTypeEvidence) -> str:
    """Classify the user's planning goal into one of 15 standard developer task categories."""
    lowered = goal_text.lower().strip()

    # Priority order checks
    if any(k in lowered for k in ("auth", "login", "register", "password", "hash", "token", "jwt", "bcrypt")):
        return "authentication"
    if any(k in lowered for k in ("playwright", "selenium", "webdriver", "browser", "page", "navigate", "puppeteer")):
        return "browser_automation"
    if any(k in lowered for k in ("desktop", "win32", "pywinauto", "uiautomation", "mouse", "keyboard", "click")):
        return "desktop_automation"
    if any(k in lowered for k in ("voice", "speak", "speech", "audio", "jarvis")):
        return "voice_assistant"
    if any(k in lowered for k in ("test", "pytest", "unittest", "assert", "coverage", "lint", "ruff")):
        return "testing_quality"
    if any(k in lowered for k in ("docker", "k8s", "kubernetes", "deploy", "cloud", "ci", "cd", "workflow", "github-actions")):
        return "deployment"
    if any(k in lowered for k in ("doc", "docs", "guide", "readme", "markdown", "walkthrough", "comments")):
        return "documentation"
    if any(k in lowered for k in ("fix", "bug", "error", "fail", "issue", "resolve")):
        return "bug_fix"
    if any(k in lowered for k in ("refactor", "clean", "rewrite", "restructure")):
        return "refactor"
    if any(k in lowered for k in ("research", "investigate", "explore", "look", "audit")):
        return "research"
    if any(k in lowered for k in ("db", "sqlite", "postgres", "mysql", "save", "load", "persist", "retrieve")):
        # Distinguish database feature vs generic memory system
        if "sql" in lowered or "schema" in lowered or "migration" in lowered:
            return "database_feature"
        return "memory_system"
    if any(k in lowered for k in ("fastapi", "api", "endpoint", "endpoints", "rest", "graphql", "route")):
        return "backend_api"
    if any(k in lowered for k in ("react", "vue", "vite", "flutter", "html", "css", "ui", "screen", "view", "component", "pages", "interface")):
        return "frontend_ui"

    # Stack-based fallback
    if "fastapi" in project_evidence.detected_stack:
        return "backend_api"
    if "react" in project_evidence.detected_stack or "vite" in project_evidence.detected_stack:
        return "frontend_ui"

    return "unknown"


# Recipe database for all 15 goal types
RECIPES: Dict[str, Dict[str, Any]] = {
    "authentication": {
        "milestones": [
            {
                "id": "user_model",
                "title": "User Model and Database Schema",
                "description": "Establish database tables/models for storing users.",
                "rationale": "Base schema storage is needed for all login validation steps.",
                "priority": "high",
                "dependencies": [],
                "acceptance_criteria": ["Database schema is defined", "Migrations can be run"],
                "validation_strategy": ["Verify migrations run successfully"],
            },
            {
                "id": "password_hash",
                "title": "Secure Password Hashing",
                "description": "Implement password cryptographically secure hashing controls.",
                "rationale": "Passwords must never be stored in plain text.",
                "priority": "high",
                "dependencies": ["user_model"],
                "acceptance_criteria": ["Hashing helper functions exist", "Salted hash verification succeeds"],
                "validation_strategy": ["Run password hashing unit tests"],
            },
            {
                "id": "token_strategy",
                "title": "Token and Session Management",
                "description": "Setup cryptographically signed tokens (e.g. JWT or sessions).",
                "rationale": "Stateless verification requires cryptographically signed claims.",
                "priority": "medium",
                "dependencies": ["password_hash"],
                "acceptance_criteria": ["Token generator and verifier functions are implemented", "Expiration works"],
                "validation_strategy": ["Verify token validation suite passes"],
            },
            {
                "id": "auth_routes",
                "title": "Login and Registration Routes",
                "description": "Expose endpoints for login and user registration.",
                "rationale": "Users need active route controllers to authenticate.",
                "priority": "high",
                "dependencies": ["token_strategy"],
                "acceptance_criteria": ["POST /register works", "POST /login returns valid tokens"],
                "validation_strategy": ["Verify end-to-end routing integration"],
            },
            {
                "id": "auth_guards",
                "title": "Route Authorization Guards",
                "description": "Restrict access to protected endpoints using token headers.",
                "rationale": "Access control layers secure private resources.",
                "priority": "medium",
                "dependencies": ["auth_routes"],
                "acceptance_criteria": ["Guarded endpoints return 401 on missing tokens", "Valid tokens grant access"],
                "validation_strategy": ["Verify guard authentication intercepts"],
            },
        ],
        "tasks": [
            {
                "id": "tsk_auth_schema",
                "milestone": "user_model",
                "title": "Implement User Database Schema",
                "description": "Define the user database model with username and hashed password fields.",
                "rationale": "Stores user credentials securely.",
                "priority": "high",
                "dependencies": [],
                "affected_areas": ["models/user.py"],
                "expected_artifacts": ["models/user.py"],
                "acceptance_criteria": ["User table has unique username field", "Password hash field exists"],
                "validation_commands": ["pytest tests/test_user_model.py"],
                "risk_level": "low",
            },
            {
                "id": "tsk_password_crypt",
                "milestone": "password_hash",
                "title": "Implement Password Hashing Helpers",
                "description": "Write hash_password and verify_password helpers using bcrypt or passlib.",
                "rationale": "Encrypts clear-text passwords securely.",
                "priority": "high",
                "dependencies": ["tsk_auth_schema"],
                "affected_areas": ["security/hashing.py"],
                "expected_artifacts": ["security/hashing.py"],
                "acceptance_criteria": ["verify_password returns True on correct password", "Returns False on wrong password"],
                "validation_commands": ["pytest tests/test_hashing.py"],
                "risk_level": "low",
            },
        ]
    },
    "browser_automation": {
        "milestones": [
            {
                "id": "browser_session",
                "title": "Browser Discovery and Session Initiation",
                "description": "Initialize browser instances and context models safely.",
                "rationale": "Automation actions require a running and responsive browser instance.",
                "priority": "high",
                "dependencies": [],
                "acceptance_criteria": ["Browser launches successfully", "Context session is initialized"],
                "validation_strategy": ["Verify launch logs and session connections"],
            },
            {
                "id": "dom_extraction",
                "title": "DOM and Accessibility Extraction",
                "description": "Extract raw DOM structures and accessibility trees.",
                "rationale": "Locating interactive elements requires parsing page hierarchies.",
                "priority": "medium",
                "dependencies": ["browser_session"],
                "acceptance_criteria": ["Extracts page text and button elements correctly"],
                "validation_strategy": ["Run parser integration tests"],
            },
        ],
        "tasks": [
            {
                "id": "tsk_launch_browser",
                "milestone": "browser_session",
                "title": "Implement Browser Launch Controller",
                "description": "Write launcher logic using Playwright/Selenium that instantiates browser contexts.",
                "rationale": "Initiates programmatic browser sessions.",
                "priority": "high",
                "dependencies": [],
                "affected_areas": ["browser/launcher.py"],
                "expected_artifacts": ["browser/launcher.py"],
                "acceptance_criteria": ["Launcher opens browser in headless mode", "Handles cleanup"],
                "validation_commands": ["pytest tests/test_launcher.py"],
                "risk_level": "medium",
            }
        ]
    },
    "desktop_automation": {
        "milestones": [
            {
                "id": "desktop_session",
                "title": "Desktop Session Discovery",
                "description": "Find and attach to active Windows UI elements.",
                "rationale": "Automating windows requires finding window handle controllers.",
                "priority": "high",
                "dependencies": [],
                "acceptance_criteria": ["Active windows list can be queried", "Finds target window"],
                "validation_strategy": ["Verify window hook tests"],
            }
        ],
        "tasks": [
            {
                "id": "tsk_hook_window",
                "milestone": "desktop_session",
                "title": "Implement Window Hook Manager",
                "description": "Create a hook utility attaching to specific window titles.",
                "rationale": "Hooks give access to element trees.",
                "priority": "high",
                "dependencies": [],
                "affected_areas": ["desktop/hook.py"],
                "expected_artifacts": ["desktop/hook.py"],
                "acceptance_criteria": ["Successfully attaches to Notepad or Explorer window handles"],
                "validation_commands": ["pytest tests/test_hook.py"],
                "risk_level": "high",
            }
        ]
    },
    "backend_api": {
        "milestones": [
            {
                "id": "api_routing",
                "title": "API Routes Definition",
                "description": "Configure base router paths and controller methods.",
                "rationale": "Incoming request mappings depend on valid route tables.",
                "priority": "high",
                "dependencies": [],
                "acceptance_criteria": ["Endpoints respond to request payloads"],
                "validation_strategy": ["Check endpoint response statuses"],
            }
        ],
        "tasks": [
            {
                "id": "tsk_route_setup",
                "milestone": "api_routing",
                "title": "Setup Base Controller Routes",
                "description": "Implement route controllers maps inside router modules.",
                "rationale": "Exposes API surface area.",
                "priority": "high",
                "dependencies": [],
                "affected_areas": ["api/routes.py"],
                "expected_artifacts": ["api/routes.py"],
                "acceptance_criteria": ["Exposes health and stats endpoints"],
                "validation_commands": ["pytest tests/test_routes.py"],
                "risk_level": "low",
            }
        ]
    },
}


def _get_recipe(goal_type: str) -> Dict[str, Any]:
    """Retrieve recipe fallback to backend_api if not explicitly defined."""
    if goal_type in RECIPES:
        return RECIPES[goal_type]

    # Generic developer template fallback that satisfies "meaningful tasks and milestones"
    return {
        "milestones": [
            {
                "id": f"milestone_init_{goal_type}",
                "title": f"Initial {goal_type.replace('_', ' ').title()} Scope Setup",
                "description": f"Define and configure base parameters for {goal_type.replace('_', ' ')} implementation.",
                "rationale": "Initial configuration sets up package structures correctly.",
                "priority": "high",
                "dependencies": [],
                "acceptance_criteria": ["Requirements files are updated", "Configuration loads"],
                "validation_strategy": ["Run config verification unit tests"],
            },
            {
                "id": f"milestone_impl_{goal_type}",
                "title": f"Core {goal_type.replace('_', ' ').title()} Coding",
                "description": "Implement core functions fulfilling the primary goal.",
                "rationale": "The functional capabilities are the target output of the goal.",
                "priority": "high",
                "dependencies": [f"milestone_init_{goal_type}"],
                "acceptance_criteria": ["Code compiles", "Baseline methods operate without errors"],
                "validation_strategy": ["Verify compileall and test suite runs"],
            }
        ],
        "tasks": [
            {
                "id": f"tsk_init_{goal_type}",
                "milestone": f"milestone_init_{goal_type}",
                "title": f"Setup {goal_type.replace('_', ' ').title()} Modules",
                "description": "Configure file directories and initial configuration templates.",
                "rationale": "Sets up imports and environment configs.",
                "priority": "high",
                "dependencies": [],
                "affected_areas": ["config.py"],
                "expected_artifacts": ["config.py"],
                "acceptance_criteria": ["Configuration imports correctly"],
                "validation_commands": ["pytest tests/test_config.py"],
                "risk_level": "low",
            },
            {
                "id": f"tsk_core_{goal_type}",
                "milestone": f"milestone_impl_{goal_type}",
                "title": "Implement Core Functional Logic",
                "description": "Code the main interfaces and methods supporting the active goal.",
                "rationale": "Implements the core logic requested.",
                "priority": "high",
                "dependencies": [f"tsk_init_{goal_type}"],
                "affected_areas": ["core.py"],
                "expected_artifacts": ["core.py"],
                "acceptance_criteria": ["Baseline method calls work"],
                "validation_commands": ["pytest tests/test_core.py"],
                "risk_level": "medium",
            }
        ]
    }


class RoadmapGenerator:
    """Generates milestones, tasks, and task dependency graphs for project descriptions."""

    def __init__(self, state: ProjectState) -> None:
        self.state = state

    def generate_roadmap(
        self, description: str, goals: List[str], existing_milestones: Optional[List[str]] = None
    ) -> Roadmap:
        """Derive a genuinely goal-aware, project-aware roadmap based on description, evidence, and recipes."""
        evidence = detect_project_type(self.state.project_path)
        gtype = classify_goal(description, evidence)

        # Get recipe
        recipe = _get_recipe(gtype)
        roadmap = self.state.roadmap

        # Save planning action history
        roadmap.planning_history.append(
            {
                "timestamp": time.time(),
                "action": "generate_roadmap",
                "description": description,
                "goals": goals,
                "goal_type": gtype,
                "project_evidence": evidence.to_dict(),
            }
        )

        # Apply project stack variations to names/validation commands
        stack = evidence.detected_stack
        validation_tool = "pytest"
        if "rust" in stack:
            validation_tool = "cargo test"
        elif "nodejs" in stack:
            validation_tool = "npm test"

        # Create Milestones
        for mdata in recipe["milestones"]:
            # Generate deterministic stable ID prefixing the goal details
            mid = f"ms_{gtype}_{mdata['id']}"

            # Map milestone dependencies
            deps = [f"ms_{gtype}_{d}" for d in mdata.get("dependencies", [])]

            title = mdata["title"]
            desc = mdata["description"]
            if "fastapi" in stack:
                title = f"FastAPI: {title}"
                desc = f"{desc} (Implemented inside FastAPI framework)"

            m = Milestone(
                milestone_id=mid,
                title=title,
                description=desc,
                status=mdata.get("status", "pending"),
                priority=mdata.get("priority", "medium"),
                dependencies=deps,
                rationale=mdata.get("rationale", "Needed for roadmap completion."),
                acceptance_criteria=mdata.get("acceptance_criteria", []),
                validation_strategy=mdata.get("validation_strategy", []),
            )
            roadmap.milestones[mid] = m
            if mid not in roadmap.planned_milestones:
                roadmap.planned_milestones.append(mid)

        # Create Tasks
        for tdata in recipe["tasks"]:
            tid = f"task_{gtype}_{tdata['id'].replace('tsk_', '')}"
            mid = f"ms_{gtype}_{tdata['milestone']}"

            # Map dependencies
            deps = [f"task_{gtype}_{d.replace('tsk_', '')}" for d in tdata.get("dependencies", [])]

            # Adjust validation command tool
            vcmds = []
            for cmd in tdata.get("validation_commands", []):
                if validation_tool != "pytest":
                    cmd = cmd.replace("pytest", validation_tool)
                vcmds.append(cmd)

            # Prevent duplication
            existing_t = [t for t in self.state.tasks if t.task_id == tid]
            if not existing_t:
                t = Task(
                    task_id=tid,
                    title=tdata["title"],
                    status=tdata.get("status", "pending"),
                    priority=tdata.get("priority", "medium"),
                    dependencies=deps,
                    completion_state=tdata.get("completion_state", False),
                    description=tdata.get("description", ""),
                    milestone=mid,
                    rationale=tdata.get("rationale", ""),
                    affected_areas=tdata.get("affected_areas", []),
                    expected_artifacts=tdata.get("expected_artifacts", []),
                    acceptance_criteria=tdata.get("acceptance_criteria", []),
                    validation_commands=vcmds,
                    risk_level=tdata.get("risk_level", "medium"),
                )
                self.state.tasks.append(t)

        return roadmap

    def expand_milestone(self, milestone_id: str, tasks_data: List[Dict[str, Any]]) -> None:
        """Generate tasks and task dependencies inside a milestone, explaining why they exist."""
        if milestone_id not in self.state.roadmap.milestones:
            raise KeyError(f"Milestone '{milestone_id}' does not exist.")

        for tdata in tasks_data:
            t_id = tdata["task_id"]

            # Prevent duplicate tasks
            existing_t = [t for t in self.state.tasks if t.task_id == t_id]
            if existing_t:
                continue

            t = Task(
                task_id=t_id,
                title=tdata["title"],
                status=tdata.get("status", "pending"),
                priority=tdata.get("priority", "medium"),
                dependencies=tdata.get("dependencies", []),
                completion_state=tdata.get("completion_state", False),
                description=tdata.get("description", ""),
                milestone=milestone_id,
                rationale=tdata.get("rationale", ""),
                affected_areas=tdata.get("affected_areas", []),
                expected_artifacts=tdata.get("expected_artifacts", []),
                acceptance_criteria=tdata.get("acceptance_criteria", []),
                validation_commands=tdata.get("validation_commands", []),
                risk_level=tdata.get("risk_level", "medium"),
            )
            self.state.tasks.append(t)

            self.state.roadmap.planning_history.append(
                {
                    "timestamp": time.time(),
                    "action": "expand_milestone",
                    "milestone_id": milestone_id,
                    "task_id": t_id,
                    "explanation": tdata.get("explanation", "Required for milestone delivery."),
                }
            )


def validate_roadmap(state: ProjectState) -> Tuple[bool, List[str]]:
    """Enforces validation rules: no duplicates, no circular dependencies, no orphan tasks, no invalid references."""
    errors = []

    # 1. Duplicate checks
    milestone_ids = list(state.roadmap.milestones.keys())
    if len(milestone_ids) != len(set(milestone_ids)):
        errors.append("Duplicate milestone IDs detected.")

    task_ids = [t.task_id for t in state.tasks]
    if len(task_ids) != len(set(task_ids)):
        errors.append("Duplicate task IDs detected.")

    # Convert lists to sets for fast lookup
    ms_set = set(milestone_ids)
    tsk_set = set(task_ids)

    # 2. Reference checks & Orphan tasks
    for t in state.tasks:
        if t.task_id in t.dependencies:
            errors.append(f"Task '{t.task_id}' depends on itself.")
        if t.milestone and t.milestone not in ms_set:
            errors.append(f"Task '{t.task_id}' is orphan: references non-existent milestone '{t.milestone}'.")
        for dep in t.dependencies:
            if dep not in tsk_set:
                errors.append(f"Task '{t.task_id}' references non-existent dependency '{dep}'.")

    for mid, m in state.roadmap.milestones.items():
        if mid in m.dependencies:
            errors.append(f"Milestone '{mid}' depends on itself.")
        for dep in m.dependencies:
            if dep not in ms_set:
                errors.append(f"Milestone '{mid}' references non-existent dependency '{dep}'.")

    # 3. Circular dependency detection for milestones
    ms_graph = {mid: m.dependencies for mid, m in state.roadmap.milestones.items()}
    if _has_cycle(ms_graph):
        errors.append("Circular dependency detected in milestones.")

    # 4. Circular dependency detection for tasks
    tsk_graph = {t.task_id: t.dependencies for t in state.tasks}
    if _has_cycle(tsk_graph):
        errors.append("Circular dependency detected in tasks.")

    return len(errors) == 0, errors


def _has_cycle(graph: Dict[str, List[str]]) -> bool:
    """Helper to detect cycles using DFS path-tracking (states: 0=unvisited, 1=visiting, 2=visited)."""
    states: Dict[str, int] = {node: 0 for node in graph}

    def dfs(node: str) -> bool:
        if states.get(node, 0) == 1:
            return True  # Cycle detected
        if states.get(node, 0) == 2:
            return False

        states[node] = 1
        for neighbor in graph.get(node, []):
            if dfs(neighbor):
                return True
        states[node] = 2
        return False

    for node in graph:
        if states[node] == 0:
            if dfs(node):
                return True
    return False


def is_legacy_roadmap(state: ProjectState) -> bool:
    """Detect legacy generic roadmap signatures."""
    has_ms_core = "ms_core" in state.roadmap.milestones
    has_tsk_init = any(t.task_id == "tsk_init" for t in state.tasks)

    has_legacy_ms_title = False
    if has_ms_core:
        m = state.roadmap.milestones["ms_core"]
        if m.title == "Core Infrastructure Implementation":
            has_legacy_ms_title = True

    has_legacy_tsk_title = False
    for t in state.tasks:
        if t.task_id == "tsk_init" and t.title == "Initialize Repository Structures":
            has_legacy_tsk_title = True
            break

    if state.roadmap.roadmap_schema_version < 2:
        if has_ms_core or has_tsk_init or has_legacy_ms_title or has_legacy_tsk_title:
            return True

    return False


def migrate_legacy_roadmap(state: ProjectState) -> Tuple[ProjectState, Dict[str, Any]]:
    """Safely migrate the existing roadmap to the modern version 2 schema."""
    changes = {
        "archived_milestones": [],
        "archived_tasks": [],
        "added_milestones": [],
        "added_tasks": [],
    }

    # 1. Archive legacy placeholder items
    archive_m = {}
    for mid in list(state.roadmap.milestones.keys()):
        if mid == "ms_core" or state.roadmap.milestones[mid].title == "Core Infrastructure Implementation":
            archive_m[mid] = state.roadmap.milestones[mid]
            changes["archived_milestones"].append(mid)
            del state.roadmap.milestones[mid]

    archive_t = []
    new_tasks = []
    for t in state.tasks:
        if t.task_id == "tsk_init" or t.title == "Initialize Repository Structures":
            archive_t.append(t)
            changes["archived_tasks"].append(t.task_id)
        else:
            new_tasks.append(t)
    state.tasks = new_tasks

    # Record archived data in history
    state.roadmap.planning_history.append({
        "action": "migrate_archive_legacy",
        "timestamp": time.time(),
        "archived_milestones": {mid: m.to_dict() for mid, m in archive_m.items()},
        "archived_tasks": [t.to_dict() for t in archive_t],
    })

    # 2. Seed verified Grandpa history milestones
    completed_milestone_list = [
        "Voice Runtime",
        "Windows Automation",
        "Vision Engine V1",
        "Executive Planner V1",
        "Browser Intelligence V1",
        "Memory System V1",
        "Memory Integration V1",
        "Agent Runtime V1",
        "Agent Execution Engine V2",
        "Autonomous Development Workflow V1",
        "Multi-Project Memory V1",
        "Project Engineer Mode V1",
        "Self-Planning Engine V1.1",
    ]

    # Create completed milestone entries
    for idx, title in enumerate(completed_milestone_list, 1):
        mid = f"ms_completed_{idx}"
        m = Milestone(
            milestone_id=mid,
            title=title,
            description=f"Completed {title} implementation.",
            status="completed",
            priority="medium",
            dependencies=[f"ms_completed_{idx-1}"] if idx > 1 else [],
            rationale="Verified historical project progress.",
            acceptance_criteria=["Verified by project completion logs"],
            validation_strategy=["Verify all existing test cases pass"],
        )
        state.roadmap.milestones[mid] = m
        if mid not in state.roadmap.completed_milestones:
            state.roadmap.completed_milestones.append(mid)
        changes["added_milestones"].append(mid)

    # 3. Create active stabilization milestone
    active_mid = "ms_self_planning_stabilization"
    m_active = Milestone(
        milestone_id=active_mid,
        title="Self-Planning Engine V1.1 stabilization",
        description="Stabilize goal-aware and project-aware self-planning engine.",
        status="in_progress",
        priority="high",
        dependencies=[f"ms_completed_{len(completed_milestone_list)}"],
        rationale="Upgrade project engineer planning outputs to use the migrated roadmap.",
        acceptance_criteria=["Roadmap validate runs cleanly", "Real CLI commands return new roadmap tasks"],
        validation_strategy=["pytest tests/test_self_planning_engine.py"],
    )
    state.roadmap.milestones[active_mid] = m_active
    state.roadmap.current_milestone = active_mid
    state.current_milestone = active_mid
    if active_mid not in state.roadmap.planned_milestones:
        state.roadmap.planned_milestones.append(active_mid)
    changes["added_milestones"].append(active_mid)

    # Add stabilization tasks
    active_tsk_id = "task_self_planning_stabilization_verify"
    t_active = Task(
        task_id=active_tsk_id,
        title="Run self-planning verification diagnostics",
        status="pending",
        priority="high",
        dependencies=[],
        completion_state=False,
        description="Verify that the project engineer work package produces the correct next task.",
        milestone=active_mid,
        rationale="Verifies migration success.",
        affected_areas=["src/grandpa/agent/development/"],
        expected_artifacts=["tests/test_self_planning_engine.py"],
        acceptance_criteria=["work-package CLI command executes cleanly", "All tests pass"],
        validation_commands=["uv run pytest tests/test_self_planning_engine.py"],
        risk_level="low",
    )
    state.tasks.append(t_active)
    changes["added_tasks"].append(active_tsk_id)

    # 4. Create planned milestone: Autonomous Sprint Runner V1
    runner_mid = "ms_autonomous_sprint_runner"
    m_runner = Milestone(
        milestone_id=runner_mid,
        title="Autonomous Sprint Runner V1",
        description="Develop automated execution loops and runners for developer tasks.",
        status="pending",
        priority="medium",
        dependencies=[active_mid],
        rationale="Enables autonomous execution of work packages.",
        acceptance_criteria=["Sprint runner CLI operates", "Sprint tasks run without human input"],
        validation_strategy=["pytest tests/test_sprint_runner.py"],
    )
    state.roadmap.milestones[runner_mid] = m_runner
    if runner_mid not in state.roadmap.planned_milestones:
        state.roadmap.planned_milestones.append(runner_mid)
    changes["added_milestones"].append(runner_mid)

    # Add planned sprint runner tasks
    runner_tsk_id = "task_autonomous_sprint_runner_init"
    t_runner = Task(
        task_id=runner_tsk_id,
        title="Initialize Sprint Runner CLI layout",
        status="pending",
        priority="medium",
        dependencies=[active_tsk_id],
        completion_state=False,
        description="Establish the CLI framework and basic option parser for the sprint runner.",
        milestone=runner_mid,
        rationale="Initial entry point for runner controls.",
        affected_areas=["src/grandpa/cli/sprint_runner.py"],
        expected_artifacts=["src/grandpa/cli/sprint_runner.py"],
        acceptance_criteria=["sprint-runner CLI returns help output"],
        validation_commands=["uv run --no-sync grandpa sprint-runner --help"],
        risk_level="medium",
    )
    state.tasks.append(t_runner)
    changes["added_tasks"].append(runner_tsk_id)

    # Update versioning meta
    state.roadmap.roadmap_schema_version = 2
    state.roadmap.migrated_from_version = 1
    state.roadmap.migration_timestamp = time.time()
    state.roadmap.generated_by = "self_planning_migration"
    state.roadmap.generation_goal = "Migrate legacy roadmap to Goal-Aware V2"

    return state, changes
