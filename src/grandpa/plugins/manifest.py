"""Reading ``plugins/<name>/plugin.toml`` and checking a plugin's code (G2).

A manifest says everything a plugin may do. Nothing in it can loosen a rule:
a tool's risk can only go *up* from what its permissions imply, and a
permission the code obviously needs but the manifest does not declare stops
the plugin from loading.

The code check is static and best-effort. Python running in Grandpa's own
process cannot be sandboxed, so the real decision is ``grandpa plugin
enable``, which shows the permissions, asks, and pins the plugin's files. The
check here catches the honest mistakes and the obvious tricks: importing
Grandpa's internals (to reach the executor without its checks), dynamic
imports and ``eval``, and using processes, the network or file deletion
without saying so.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from grandpa.action_layer.model import RiskLevel

__all__ = [
    "MANIFEST",
    "PERMISSIONS",
    "ConfigOption",
    "EventHook",
    "Manifest",
    "ManifestError",
    "ToolDecl",
    "check_code",
    "parse_manifest",
    "read_manifest",
]

MANIFEST = "plugin.toml"

PERMISSIONS: Mapping[str, RiskLevel] = {
    "network": RiskLevel.MEDIUM,
    "files": RiskLevel.HIGH,
    "system": RiskLevel.HIGH,
}
"""Fixed permissions and the lowest risk a tool holding them can have.

``actions:<name>`` is the other kind: the plugin may run that Grandpa action
through ``ctx.run_action``, and its tools are at least as risky as it is.
"""

ACTION_PERMISSION = "actions:"

_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL = re.compile(r"^[a-z][a-z0-9_]*$")
_RISKS = {"low": RiskLevel.LOW, "medium": RiskLevel.MEDIUM, "high": RiskLevel.HIGH}
_ORDER = (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)


class ManifestError(ValueError):
    """The manifest or the code breaks a rule; the plugin is not loaded."""


@dataclass(frozen=True)
class ToolDecl:
    name: str
    description: str
    function: str
    risk: RiskLevel
    parameters: Mapping[str, Any]
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventHook:
    on: str
    handler: str


@dataclass(frozen=True)
class ConfigOption:
    name: str
    default: Any
    description: str = ""


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    description: str
    module: str
    folder: Path
    permissions: tuple[str, ...] = ()
    tools: tuple[ToolDecl, ...] = ()
    events: tuple[EventHook, ...] = ()
    config: tuple[ConfigOption, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    @property
    def allowed_actions(self) -> frozenset[str]:
        return frozenset(
            p[len(ACTION_PERMISSION) :]
            for p in self.permissions
            if p.startswith(ACTION_PERMISSION)
        )

    def config_defaults(self) -> dict[str, Any]:
        return {option.name: option.default for option in self.config}


def max_risk(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=_ORDER.index) if levels else RiskLevel.LOW


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ManifestError(f"{label} must be a list of strings")


def _text(table: Mapping[str, Any], key: str, label: str, default: str = "") -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ManifestError(f"{label}.{key} must be text")
    return value.strip()


def _permissions(values: tuple[str, ...]) -> tuple[str, ...]:
    for permission in values:
        if permission in PERMISSIONS:
            continue
        if (
            permission.startswith(ACTION_PERMISSION)
            and permission[len(ACTION_PERMISSION) :].strip()
        ):
            continue
        known = ", ".join([*PERMISSIONS, "actions:<action name>"])
        raise ManifestError(f"unknown permission {permission!r} (known: {known})")
    return tuple(dict.fromkeys(values))


def _tool(table: Any, index: int) -> ToolDecl:
    label = f"tools[{index}]"
    if not isinstance(table, Mapping):
        raise ManifestError(f"{label} must be a table")
    name = _text(table, "name", label)
    if not _TOOL.match(name):
        raise ManifestError(
            f"{label}.name {name!r}: use lower-case letters, digits and '_'"
        )
    if "__" in name:
        raise ManifestError(f"{label}.name {name!r} cannot contain '__'")
    risk_name = _text(table, "risk", label, "low").lower()
    if risk_name not in _RISKS:
        raise ManifestError(f"{label}.risk must be low, medium or high")
    parameters = table.get("parameters", {})
    if not isinstance(parameters, Mapping) or not all(
        isinstance(v, Mapping) for v in parameters.values()
    ):
        raise ManifestError(
            f"{label}.parameters must be a table of name = {{ type = ... }}"
        )
    required = _strings(table.get("required"), f"{label}.required")
    missing = [r for r in required if r not in parameters]
    if missing:
        raise ManifestError(f"{label}.required names unknown parameters: {missing}")
    function = _text(table, "function", label, name)
    if not function.isidentifier():
        raise ManifestError(f"{label}.function must be a Python function name")
    return ToolDecl(
        name=name,
        description=_text(table, "description", label) or f"{name} (no description)",
        function=function,
        risk=_RISKS[risk_name],
        parameters={str(k): dict(v) for k, v in parameters.items()},
        required=required,
    )


def _event(table: Any, index: int) -> EventHook:
    from grandpa.core.events import EventType

    label = f"events[{index}]"
    if not isinstance(table, Mapping):
        raise ManifestError(f"{label} must be a table")
    on = _text(table, "on", label)
    if on not in {e.value for e in EventType}:
        raise ManifestError(f"{label}.on {on!r} is not a Grandpa event")
    handler = _text(table, "handler", label)
    if not handler.isidentifier():
        raise ManifestError(f"{label}.handler must be a Python function name")
    return EventHook(on=on, handler=handler)


def parse_manifest(data: Mapping[str, Any], folder: Path) -> Manifest:
    """Turn the TOML mapping into a :class:`Manifest`, or raise ManifestError."""
    info = data.get("plugin")
    if not isinstance(info, Mapping):
        raise ManifestError("a [plugin] table is required")
    name = _text(info, "name", "plugin")
    if not _NAME.match(name):
        raise ManifestError(
            f"plugin.name {name!r}: use lower-case letters, digits and '-'"
        )
    if name != folder.name:
        raise ManifestError(
            f"plugin.name {name!r} must match its folder name {folder.name!r}"
        )
    module = _text(info, "module", "plugin", "plugin.py")
    module_path = (folder / module).resolve()
    if module_path.parent != folder.resolve() or module_path.suffix != ".py":
        raise ManifestError("plugin.module must be a .py file inside the plugin folder")
    permissions = _permissions(_strings(info.get("permissions"), "plugin.permissions"))

    tool_tables = data.get("tools", [])
    if not isinstance(tool_tables, list):
        raise ManifestError("tools must be [[tools]] tables")
    tools = tuple(_tool(t, i) for i, t in enumerate(tool_tables))
    names = [t.name for t in tools]
    if len(set(names)) != len(names):
        raise ManifestError("two tools have the same name")

    event_tables = data.get("events", [])
    if not isinstance(event_tables, list):
        raise ManifestError("events must be [[events]] tables")
    events = tuple(_event(t, i) for i, t in enumerate(event_tables))

    config_table = data.get("config", {})
    if not isinstance(config_table, Mapping):
        raise ManifestError("config must be a table of [config.<name>] tables")
    config: list[ConfigOption] = []
    for key, option in config_table.items():
        if not isinstance(option, Mapping) or "default" not in option:
            raise ManifestError(f"config.{key} needs a default")
        config.append(
            ConfigOption(
                name=str(key),
                default=option["default"],
                description=_text(option, "description", f"config.{key}"),
            )
        )

    return Manifest(
        name=name,
        version=_text(info, "version", "plugin", "0.0.0"),
        description=_text(info, "description", "plugin"),
        module=module_path.name,
        folder=folder,
        permissions=permissions,
        tools=tools,
        events=events,
        config=tuple(config),
    )


def read_manifest(folder: Path) -> Manifest:
    import tomllib

    path = folder / MANIFEST
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"{path} could not be read: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{path} is not valid TOML: {exc}") from exc
    return parse_manifest(data, folder)


# --- the code check ------------------------------------------------------------

_NEEDS: Mapping[str, str] = {
    # module (top-level name) -> the permission it needs
    "subprocess": "system",
    "ctypes": "system",
    "winreg": "system",
    "multiprocessing": "system",
    "pty": "system",
    "signal": "system",
    "socket": "network",
    "ssl": "network",
    "urllib": "network",
    "http": "network",
    "requests": "network",
    "httpx": "network",
    "aiohttp": "network",
    "ftplib": "network",
    "smtplib": "network",
    "websocket": "network",
    "websockets": "network",
    "shutil": "files",
}
_OS_CALLS: Mapping[str, str] = {
    "system": "system",
    "popen": "system",
    "startfile": "system",
    "kill": "system",
    "fork": "system",
    "remove": "files",
    "unlink": "files",
    "rmdir": "files",
    "removedirs": "files",
    "rename": "files",
    "replace": "files",
}
_OS_PREFIXES = ("exec", "spawn")
_NEVER_MODULES = frozenset({"importlib", "builtins", "runpy", "code", "codeop"})
_NEVER_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "__builtins__",
        "globals",
        "locals",
        "vars",
        "setattr",
        "delattr",
    }
)
_ALLOWED_DUNDERS = frozenset({"__init__", "__name__", "__doc__"})
_ALLOWED_GRANDPA = frozenset({"grandpa.plugins", "grandpa.plugins.api"})


def _os_call(name: str) -> str | None:
    if name in _OS_CALLS:
        return _OS_CALLS[name]
    if name.startswith(_OS_PREFIXES):
        return "system"
    return None


def check_code(manifest: Manifest, source: str | None = None) -> None:
    """Refuse code that steps outside what the manifest declares."""
    path = manifest.folder / manifest.module
    if source is None:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ManifestError(f"{path} could not be read: {exc}") from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ManifestError(f"{path.name} has a syntax error: {exc}") from exc

    declared = set(manifest.permissions)
    problems: list[str] = []

    def need(permission: str, what: str, line: int) -> None:
        if permission not in declared:
            problems.append(
                f"line {line}: {what} needs the {permission!r} permission, "
                "which the manifest does not declare"
            )

    def module(name: str, line: int) -> None:
        top = name.split(".")[0]
        if top in _NEVER_MODULES:
            problems.append(f"line {line}: importing {name} is not allowed in plugins")
        elif top == "grandpa" and name not in _ALLOWED_GRANDPA:
            problems.append(
                f"line {line}: plugins may import only grandpa.plugins, not {name}; "
                "use ctx.run_action for Grandpa's actions"
            )
        elif top in _NEEDS:
            need(_NEEDS[top], f"importing {name}", line)

    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    os_names = {"os"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "os" and alias.asname
    }
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                module(alias.name, line)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(f"line {line}: relative imports are not allowed")
                continue
            base = node.module or ""
            module(base, line)
            if base == "os":
                for alias in node.names:
                    permission = _os_call(alias.name)
                    if permission:
                        need(permission, f"os.{alias.name}", line)
        elif isinstance(node, ast.Name) and node.id in _NEVER_NAMES:
            problems.append(f"line {line}: {node.id} is not allowed in plugins")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("__")
            and node.attr not in _ALLOWED_DUNDERS
        ):
            problems.append(f"line {line}: .{node.attr} is not allowed in plugins")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and not (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and not node.args[1].value.startswith("_")
            )
        ):
            problems.append(
                f"line {line}: getattr needs a literal, public attribute name"
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in os_names
        ):
            permission = _os_call(str(node.args[1].value))  # type: ignore[attr-defined]
            if permission:
                need(permission, f"os.{node.args[1].value}", line)  # type: ignore[attr-defined]
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in os_names
        ):
            permission = _os_call(node.attr)
            if permission:
                need(permission, f"os.{node.attr}", line)

    for tool in manifest.tools:
        if tool.function not in functions:
            problems.append(f"tool {tool.name!r}: no function {tool.function}()")
    for hook in manifest.events:
        if hook.handler not in functions:
            problems.append(f"event {hook.on!r}: no function {hook.handler}()")
    if problems:
        raise ManifestError("; ".join(problems))
