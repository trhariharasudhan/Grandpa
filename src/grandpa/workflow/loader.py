"""Workflow loader — load workflows from TOML files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from grandpa.workflow.graph import WorkflowGraph
from grandpa.workflow.types import NodeType, WorkflowEdge, WorkflowNode

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def load_workflow(path: str | Path) -> WorkflowGraph:
    """Load a workflow definition from a TOML file.

    Expected format:
    ```toml
    [workflow]
    name = "my_workflow"

    [[workflow.nodes]]
    id = "researcher"
    type = "agent"
    agent = "orchestrator"
    tools = ["web_search"]

    [[workflow.nodes]]
    id = "summarizer"
    type = "agent"
    agent = "simple"

    [[workflow.edges]]
    source = "researcher"
    target = "summarizer"
    ```
    """
    path = Path(path)
    if path.suffix.lower() in YAML_SUFFIXES:
        return load_yaml_workflow(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    wf_data = data.get("workflow", {})
    name = wf_data.get("name", path.stem)

    graph = WorkflowGraph(name=name)

    for node_data in wf_data.get("nodes", []):
        node = _parse_node(node_data)
        graph.add_node(node)

    for edge_data in wf_data.get("edges", []):
        edge = WorkflowEdge(
            source=edge_data["source"],
            target=edge_data["target"],
            condition=edge_data.get("condition", ""),
        )
        graph.add_edge(edge)

    valid, msg = graph.validate()
    if not valid:
        raise ValueError(f"Invalid workflow in {path}: {msg}")

    return graph


def _parse_node(data: Dict[str, Any]) -> WorkflowNode:
    """Parse a single node from TOML data."""
    node_type = NodeType(data.get("type", "agent"))
    return WorkflowNode(
        id=data["id"],
        node_type=node_type,
        agent=data.get("agent", ""),
        tools=data.get("tools", []),
        config=data.get("config", {}),
        condition_expr=data.get("condition_expr", data.get("condition", "")),
        max_iterations=data.get("max_iterations", 10),
        transform_expr=data.get("transform_expr", data.get("transform", "")),
    )


# --- YAML workflows: steps that are catalogued actions -----------------------

YAML_SUFFIXES = (".yaml", ".yml")
_STEP_KEYS = {
    "id",
    "action",
    "params",
    "when",
    "retries",
    "retry_delay",
    "timeout",
    "continue_on_error",
    "description",
}
_TOP_KEYS = {"name", "description", "vars", "steps"}
_ID = re.compile(r"^[A-Za-z_][\w\-]*$")
MAX_STEPS = 50
MAX_RETRIES = 5
MAX_TIMEOUT_SECONDS = 600.0


class WorkflowFileError(ValueError):
    """A workflow file that cannot be used, with every problem found."""

    def __init__(self, path: str | Path, problems: List[str]) -> None:
        self.path = str(path)
        self.problems = list(problems)
        super().__init__(f"{path}: " + "; ".join(problems))


def workflow_dir() -> Path:
    """Where ``grandpa workflow`` looks for ``<name>.yaml`` files."""
    override = os.environ.get("GRANDPA_WORKFLOWS_DIR")
    if override:
        return Path(override).expanduser()
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "workflows"


def list_workflow_files(directory: Path | None = None) -> List[Path]:
    folder = directory or workflow_dir()
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in YAML_SUFFIXES
    )


def find_workflow(name_or_path: str, directory: Path | None = None) -> Path:
    """A path as given, else ``<workflow dir>/<name>.yaml`` (or a file whose
    ``name:`` matches)."""
    candidate = Path(name_or_path).expanduser()
    if candidate.suffix.lower() in YAML_SUFFIXES and candidate.is_file():
        return candidate
    folder = directory or workflow_dir()
    for suffix in YAML_SUFFIXES:
        path = folder / f"{name_or_path}{suffix}"
        if path.is_file():
            return path
    for path in list_workflow_files(folder):
        try:
            data = _read_yaml(path)
        except WorkflowFileError:
            continue
        if isinstance(data, dict) and str(data.get("name", "")).lower() == (
            name_or_path.lower()
        ):
            return path
    raise FileNotFoundError(
        f"No workflow called {name_or_path!r} in {folder} (looked for "
        f"{name_or_path}.yaml)."
    )


def _read_yaml(path: Path) -> Any:
    import yaml

    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowFileError(path, [f"cannot read the file: {exc}"]) from exc


def load_yaml_workflow(path: str | Path) -> WorkflowGraph:
    """Load a YAML workflow and check every step against the action catalogue.

    ```yaml
    name: tidy-up
    description: Quiet the PC
    vars:
      level: 20
    steps:
      - id: before
        action: volume_get
      - id: lower
        action: volume_set
        params: {level: "{{ vars.level }}"}
        when: steps.before.ok
        retries: 1
        timeout: 30
    ```

    Raises :class:`WorkflowFileError` listing *every* problem, so one
    ``grandpa workflow validate`` shows all of them at once.
    """
    path = Path(path)
    data = _read_yaml(path)
    problems: List[str] = []
    if not isinstance(data, dict):
        raise WorkflowFileError(path, ["the file must be a mapping with 'steps:'"])
    for key in sorted(set(data) - _TOP_KEYS):
        problems.append(
            f"unknown key {key!r} (allowed: {', '.join(sorted(_TOP_KEYS))})"
        )
    variables = data.get("vars") or {}
    if not isinstance(variables, dict):
        problems.append("'vars' must be a mapping")
        variables = {}
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append("'steps' must be a non-empty list")
        steps = []
    if len(steps) > MAX_STEPS:
        problems.append(f"at most {MAX_STEPS} steps are allowed")

    graph = WorkflowGraph(name=str(data.get("name") or path.stem))
    graph.description = str(data.get("description") or "")
    graph.variables = dict(variables)
    graph.source = str(path)

    seen: List[str] = []
    for index, raw in enumerate(steps, start=1):
        node, step_problems = _parse_action_step(raw, index, seen, variables)
        problems.extend(step_problems)
        if node is None:
            continue
        graph.add_node(node)
        if seen:
            graph.add_edge(WorkflowEdge(source=seen[-1], target=node.id))
        seen.append(node.id)

    if problems:
        raise WorkflowFileError(path, problems)
    return graph


def _number(value: Any, label: str, problems: List[str], *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        problems.append(f"{label} must be a number of 0 or more")
        return 0.0
    if value > maximum:
        problems.append(f"{label} must be at most {maximum:g}")
    return float(value)


def _parse_action_step(
    raw: Any, index: int, seen: List[str], variables: Dict[str, Any]
) -> tuple[WorkflowNode | None, List[str]]:
    from grandpa.action_layer.catalogue import get as catalogue_get
    from grandpa.action_layer.model import RiskLevel
    from grandpa.workflow.expressions import (
        ExpressionError,
        evaluate_condition,
        references,
    )

    label = f"step {index}"
    if not isinstance(raw, dict):
        return None, [f"{label} must be a mapping with 'action:'"]
    problems: List[str] = []
    step_id = str(raw.get("id") or f"step{index}")
    label = f"step {index} ({step_id})"
    if not _ID.match(step_id):
        problems.append(f"{label}: id may use letters, digits, '_' and '-' only")
    if step_id in seen:
        problems.append(f"{label}: id is used twice")
    for key in sorted(set(raw) - _STEP_KEYS):
        problems.append(f"{label}: unknown key {key!r}")

    action = str(raw.get("action") or "")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        problems.append(f"{label}: 'params' must be a mapping")
        params = {}
    if not action:
        problems.append(f"{label}: 'action' is missing")
    else:
        try:
            spec = catalogue_get(action)
        except KeyError:
            spec = None
            problems.append(
                f"{label}: no catalogued action called {action!r} "
                "(see `grandpa tool list`)"
            )
        if spec is not None:
            if spec.risk is RiskLevel.BLOCKED:
                problems.append(f"{label}: {action} is blocked and never runs")
            schema = spec.parameters
            properties = schema.get("properties", {})
            for name in schema.get("required", []):
                if name not in params:
                    problems.append(f"{label}: {action} needs parameter {name!r}")
            for name in params:
                if name not in properties:
                    allowed = ", ".join(sorted(properties)) or "none"
                    problems.append(
                        f"{label}: {action} has no parameter {name!r} "
                        f"(accepted: {allowed})"
                    )

    # A template may only look backwards: at vars, or at steps already run.
    for ref in sorted(references(params) | _condition_refs(raw.get("when"))):
        head, _, rest = ref.partition(".")
        if head == "steps":
            target = rest.split(".", 1)[0]
            if target not in seen:
                problems.append(
                    f"{label}: refers to step {target!r}, which does not run before it"
                )
        elif head == "vars":
            if rest.split(".", 1)[0] not in variables:
                problems.append(f"{label}: unknown variable {ref!r}")
        elif head not in variables:
            problems.append(f"{label}: unknown variable {ref!r}")

    when = raw.get("when") or ""
    if when and not isinstance(when, str):
        problems.append(f"{label}: 'when' must be text")
        when = ""
    if when:
        try:
            evaluate_condition(when, {"vars": variables, "steps": {}})
        except ExpressionError as exc:
            problems.append(f"{label}: cannot read 'when': {exc}")

    retries = raw.get("retries", 0)
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        problems.append(f"{label}: retries must be a whole number of 0 or more")
        retries = 0
    elif retries > MAX_RETRIES:
        problems.append(f"{label}: retries must be at most {MAX_RETRIES}")
    delay = _number(
        raw.get("retry_delay", 1.0), f"{label}: retry_delay", problems, maximum=60
    )
    timeout = _number(
        raw.get("timeout", 60.0),
        f"{label}: timeout",
        problems,
        maximum=MAX_TIMEOUT_SECONDS,
    )
    if timeout == 0:
        problems.append(f"{label}: timeout must be more than 0")

    node = WorkflowNode(
        id=step_id,
        node_type=NodeType.ACTION,
        action=action,
        params=dict(params),
        when=when,
        retries=int(retries),
        retry_delay_seconds=delay,
        timeout_seconds=timeout or 60.0,
        continue_on_error=bool(raw.get("continue_on_error", False)),
        description=str(raw.get("description") or ""),
    )
    return (None if step_id in seen else node), problems


def _condition_refs(when: Any) -> set[str]:
    if not isinstance(when, str):
        return set()
    from grandpa.workflow.expressions import references

    found = references(when)
    # Bare dotted names (``steps.x.ok``) outside quotes count too.
    unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", " ", when)
    for token in re.findall(r"[A-Za-z_][\w\-]*(?:\.[\w\-]+)+", unquoted):
        found.add(token)
    return found


__all__ = [
    "WorkflowFileError",
    "find_workflow",
    "list_workflow_files",
    "load_workflow",
    "load_yaml_workflow",
    "workflow_dir",
]
