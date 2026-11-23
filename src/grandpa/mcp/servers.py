"""External stdio MCP servers, exposed to the action layer (G1).

Captain lists servers in ``~/.grandpa/mcp.toml`` (``GRANDPA_MCP_CONFIG``
points elsewhere)::

    # enabled = false switches every MCP server off
    [servers.files]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/Notes"]
    allow = ["read_text_file", "list_directory"]   # "*" allows every tool
    timeout = 30                                   # seconds per request

Each allowed tool becomes the action ``mcp__<server>__<tool>``. The rules,
none of which a config file can loosen:

* **Deny by default.** A tool is reachable only if its server's ``allow``
  list names it (or says ``"*"``). Nothing is allowed when ``allow`` is
  missing.
* **Always asks.** Every MCP action is ``HIGH`` with layer confirmation, so
  the executor asks before each call and refuses when nobody can be asked.
  An external server is code Grandpa did not write; its tool descriptions
  are its own claims.
* **Timeout.** Every request has a deadline; a server that misses it is
  killed, and the next call starts it again.
* **Kill switch.** ``GRANDPA_MCP_OFF=1``, ``enabled = false`` in the file,
  or ``grandpa mcp off`` (a flag file under the runtime folder) makes every
  MCP action unknown at once and stops running servers. ``grandpa mcp on``
  removes the flag.

The older ``[tools.mcp] servers`` JSON setting is read by
``SystemBuilder._discover_external_mcp`` for the agent tool executor, without
these rules. This module does not use it, so a server is only reachable
through the gated path if it is listed here.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from grandpa.action_layer.catalogue import (
    MCP_PREFIX,
    ActionSpec,
    Binding,
    Confirmation,
)
from grandpa.action_layer.model import ActionResult, RiskLevel

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TIMEOUT",
    "IMPLEMENTATION",
    "MCPHub",
    "MCPSettings",
    "ServerConfig",
    "action_name",
    "call_action",
    "config_path",
    "get_hub",
    "is_off",
    "kill_switch_path",
    "load_settings",
    "reset_hub",
    "set_off",
    "spec_for",
]

DEFAULT_TIMEOUT = 30.0
IMPLEMENTATION = "grandpa.mcp.servers.call_action"
_SERVER_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]|_(?!_))*$")
_MESSAGE_LIMIT = 600


# --- configuration -----------------------------------------------------------


@dataclass(frozen=True)
class ServerConfig:
    """One ``[servers.<name>]`` table."""

    name: str
    command: tuple[str, ...]
    allow: tuple[str, ...] = ()
    timeout: float = DEFAULT_TIMEOUT
    enabled: bool = True
    cwd: str | None = None

    def allows(self, tool: str) -> bool:
        return "*" in self.allow or tool in self.allow


@dataclass(frozen=True)
class MCPSettings:
    enabled: bool = True
    servers: Mapping[str, ServerConfig] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    path: Path | None = None


def config_path() -> Path:
    override = os.environ.get("GRANDPA_MCP_CONFIG")
    if override:
        return Path(override).expanduser()
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "mcp.toml"


def kill_switch_path() -> Path:
    from grandpa.runtime_paths import runtime_path

    return runtime_path("mcp.off")


def _as_strings(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return tuple(value)
    return None


def parse_settings(data: Mapping[str, Any], path: Path | None = None) -> MCPSettings:
    """Turn the TOML mapping into settings. Bad servers are skipped, not fatal."""
    problems: list[str] = []
    servers: dict[str, ServerConfig] = {}
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        problems.append("'enabled' must be true or false; treating MCP as off")
        enabled = False
    tables = data.get("servers", {})
    if not isinstance(tables, Mapping):
        problems.append("'servers' must be a table of [servers.<name>] tables")
        tables = {}
    for name, table in tables.items():
        label = f"servers.{name}"
        if not _SERVER_NAME.match(str(name)):
            problems.append(
                f"{label}: use letters, digits, '-' and single '_' in server names"
            )
            continue
        if not isinstance(table, Mapping):
            problems.append(f"{label}: must be a table")
            continue
        command = _as_strings(table.get("command"))
        args = _as_strings(table.get("args", [])) if "args" in table else ()
        if not command or not command[0].strip():
            problems.append(f"{label}: 'command' is required")
            continue
        if args is None:
            problems.append(f"{label}: 'args' must be a list of strings")
            continue
        allow = _as_strings(table.get("allow", []))
        if allow is None:
            problems.append(f"{label}: 'allow' must be a list of tool names")
            continue
        timeout = table.get("timeout", DEFAULT_TIMEOUT)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            problems.append(f"{label}: 'timeout' must be a positive number of seconds")
            continue
        server_enabled = table.get("enabled", True)
        if not isinstance(server_enabled, bool):
            problems.append(f"{label}: 'enabled' must be true or false")
            continue
        cwd = table.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            problems.append(f"{label}: 'cwd' must be a folder path")
            continue
        servers[str(name)] = ServerConfig(
            name=str(name),
            command=tuple(command) + tuple(args),
            allow=tuple(allow),
            timeout=float(min(timeout, 600)),
            enabled=server_enabled,
            cwd=cwd,
        )
    return MCPSettings(
        enabled=enabled, servers=servers, problems=tuple(problems), path=path
    )


def load_settings(path: Path | None = None) -> MCPSettings:
    """Read ``mcp.toml``. A missing file means no servers, not an error."""
    import tomllib

    path = path or config_path()
    if not path.is_file():
        return MCPSettings(path=path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return MCPSettings(
            enabled=False, problems=(f"{path} could not be read: {exc}",), path=path
        )
    return parse_settings(data, path)


def _env_off() -> bool:
    return os.environ.get("GRANDPA_MCP_OFF", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_off(settings: MCPSettings | None = None) -> str | None:
    """Why MCP is switched off, or ``None`` when it is on."""
    if _env_off():
        return "GRANDPA_MCP_OFF is set"
    if kill_switch_path().exists():
        return "switched off with 'grandpa mcp off'"
    settings = settings if settings is not None else load_settings()
    if not settings.enabled:
        return f"enabled = false in {settings.path}"
    return None


def set_off(off: bool) -> None:
    """The kill switch: write or remove the flag file, and stop servers."""
    flag = kill_switch_path()
    if off:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("MCP switched off by 'grandpa mcp off'\n", encoding="utf-8")
        hub = _HUB
        if hub is not None:
            hub.close_all()
    else:
        try:
            flag.unlink()
        except FileNotFoundError:
            pass


# --- names and specs ---------------------------------------------------------


def action_name(server: str, tool: str) -> str:
    return f"{MCP_PREFIX}{server}__{tool}"


def _split(name: str) -> tuple[str, str]:
    if not name.startswith(MCP_PREFIX):
        raise KeyError(name)
    server, sep, tool = name[len(MCP_PREFIX) :].partition("__")
    if not sep or not server or not tool:
        raise KeyError(name)
    return server, tool


def _clean_rules(rules: Any) -> dict[str, Any]:
    """Keep only what the executor's validator understands safely.

    MCP schemas may say ``"type": ["string", "null"]``; the validator checks
    one type name, so a list type is dropped (the server still validates).
    """
    if not isinstance(rules, Mapping):
        return {}
    cleaned = dict(rules)
    if not isinstance(cleaned.get("type", ""), str):
        cleaned.pop("type", None)
    items = cleaned.get("items")
    if items is not None:
        cleaned["items"] = _clean_rules(items)
    for bound in ("minimum", "maximum"):
        value = cleaned.get(bound)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            cleaned.pop(bound)
    if "minItems" in cleaned and not isinstance(cleaned["minItems"], int):
        cleaned.pop("minItems")
    if "enum" in cleaned and not isinstance(cleaned["enum"], list):
        cleaned.pop("enum")
    return cleaned


def _clean_schema(schema: Any) -> dict[str, Any]:
    schema = schema if isinstance(schema, Mapping) else {}
    properties = schema.get("properties", {})
    properties = properties if isinstance(properties, Mapping) else {}
    required = schema.get("required", [])
    required = (
        [r for r in required if isinstance(r, str)]
        if isinstance(required, list)
        else []
    )
    return {
        "type": "object",
        "properties": {str(k): _clean_rules(v) for k, v in properties.items()},
        "required": required,
        "additionalProperties": False,
    }


def _spec(server: str, tool: str, description: str, schema: Any) -> ActionSpec:
    about = " ".join(str(description or "").split())[:300] or "No description."
    return ActionSpec(
        name=action_name(server, tool),
        description=f"[MCP server '{server}'] {about}",
        parameters=_clean_schema(schema),
        risk=RiskLevel.HIGH,
        confirmation=Confirmation.LAYER,
        implementation=IMPLEMENTATION,
        notes=(
            "A tool on an external MCP server. Always asks first; its output "
            "comes from that server and is not trusted."
        ),
        binding=Binding.MCP_TOOL,
    )


# --- the hub -------------------------------------------------------------------


TransportFactory = Callable[[ServerConfig], Any]


def _stdio_transport(server: ServerConfig) -> Any:
    from grandpa.mcp.transport import StdioTransport

    return StdioTransport(list(server.command), timeout=server.timeout, cwd=server.cwd)


@dataclass
class _Connection:
    client: Any
    tools: dict[str, Any]  # tool name -> ToolSpec


class MCPHub:
    """Starts configured servers on first use and keeps them for the process."""

    def __init__(
        self,
        settings: MCPSettings | None = None,
        *,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        self._fixed_settings = settings
        self._factory = transport_factory or _stdio_transport
        self._connections: dict[str, _Connection] = {}
        self._lock = threading.RLock()

    @property
    def settings(self) -> MCPSettings:
        return self._fixed_settings or load_settings()

    def _server(self, name: str, settings: MCPSettings) -> ServerConfig:
        server = settings.servers.get(name)
        if server is None:
            raise KeyError(f"no MCP server called {name!r} in {settings.path}")
        if not server.enabled:
            raise KeyError(f"MCP server {name!r} is disabled")
        return server

    def _connect(self, server: ServerConfig) -> _Connection:
        with self._lock:
            existing = self._connections.get(server.name)
            if existing is not None:
                return existing
            from grandpa.mcp.client import MCPClient

            transport = self._factory(server)
            client = MCPClient(transport)
            try:
                client.initialize()
                tools = {spec.name: spec for spec in client.list_tools()}
            except BaseException:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - already failing
                    pass
                raise
            connection = _Connection(client=client, tools=tools)
            self._connections[server.name] = connection
            logger.info(
                "MCP server %r started with %d tool(s)", server.name, len(tools)
            )
            return connection

    def _drop(self, name: str) -> None:
        with self._lock:
            connection = self._connections.pop(name, None)
        if connection is not None:
            try:
                connection.client.close()
            except Exception:  # noqa: BLE001 - closing a broken server
                logger.debug("closing MCP server %r failed", name, exc_info=True)

    def close_all(self) -> None:
        for name in list(self._connections):
            self._drop(name)

    def spec_for(self, name: str) -> ActionSpec:
        server_name, tool = _split(name)
        settings = self.settings
        why = is_off(settings)
        if why:
            raise KeyError(f"MCP is off ({why})")
        server = self._server(server_name, settings)
        if not server.allows(tool):
            raise KeyError(f"{tool!r} is not on the allow list of {server_name!r}")
        try:
            connection = self._connect(server)
        except Exception as exc:  # noqa: BLE001 - reported as "no such action"
            raise KeyError(f"MCP server {server_name!r} did not start: {exc}") from exc
        found = connection.tools.get(tool)
        if found is None:
            raise KeyError(f"MCP server {server_name!r} has no tool {tool!r}")
        return _spec(server_name, tool, found.description, found.parameters)

    def call(self, name: str, arguments: Mapping[str, Any]) -> ActionResult:
        """Call one tool. Only the executor calls this, after it has asked."""
        from grandpa.mcp.protocol import MCPError
        from grandpa.mcp.transport import MCPTimeoutError

        try:
            server_name, tool = _split(name)
        except KeyError:
            return ActionResult.failed("unknown_action", message=f"{name} is not MCP.")
        settings = self.settings
        why = is_off(settings)
        if why:
            return ActionResult.failed(
                "mcp_off", message=f"MCP is off ({why}), so nothing was done."
            )
        try:
            server = self._server(server_name, settings)
        except KeyError as exc:
            return ActionResult.failed("mcp_unavailable", message=str(exc.args[0]))
        if not server.allows(tool):
            return ActionResult.failed(
                "mcp_not_allowed",
                message=f"{tool!r} is not on the allow list of {server_name!r}.",
            )
        try:
            connection = self._connect(server)
            raw = connection.client.call_tool(tool, dict(arguments))
        except MCPTimeoutError as exc:
            self._drop(server_name)
            return ActionResult.failed("mcp_timeout", message=str(exc))
        except MCPError as exc:
            return ActionResult.failed("mcp_error", message=str(exc))
        except Exception as exc:  # noqa: BLE001 - a broken server is a failure
            self._drop(server_name)
            return ActionResult.failed(
                "mcp_error", message=f"MCP server {server_name!r} failed: {exc}"
            )
        return _as_result(server_name, tool, raw)

    def status(self, *, connect: bool = True) -> list[dict[str, Any]]:
        """One row per configured server, for ``grandpa mcp list``."""
        settings = self.settings
        why = is_off(settings)
        rows: list[dict[str, Any]] = []
        for server in settings.servers.values():
            row: dict[str, Any] = {
                "name": server.name,
                "command": " ".join(server.command),
                "allow": list(server.allow),
                "timeout": server.timeout,
                "state": "ready",
                "tools": [],
            }
            if why:
                row["state"] = f"off ({why})"
            elif not server.enabled:
                row["state"] = "disabled"
            elif connect:
                try:
                    connection = self._connect(server)
                except Exception as exc:  # noqa: BLE001 - shown to the user
                    row["state"] = f"error: {exc}"
                else:
                    row["tools"] = [
                        {
                            "tool": spec.name,
                            "action": action_name(server.name, spec.name),
                            "allowed": server.allows(spec.name),
                            "description": " ".join(spec.description.split())[:80],
                        }
                        for spec in connection.tools.values()
                    ]
            rows.append(row)
        return rows

    def test(self, name: str) -> dict[str, Any]:
        """Start one server fresh, handshake, list its tools, and stop it."""
        settings = self.settings
        server = settings.servers.get(name)
        if server is None:
            raise KeyError(f"no MCP server called {name!r} in {settings.path}")
        self._drop(name)
        started = time.monotonic()
        connection = self._connect(server)
        elapsed = time.monotonic() - started
        tools = sorted(connection.tools)
        self._drop(name)
        return {
            "name": name,
            "seconds": round(elapsed, 2),
            "tools": tools,
            "allowed": [t for t in tools if server.allows(t)],
            "unknown_in_allow": sorted(
                set(server.allow) - set(tools) - {"*"},
            ),
        }


def _as_result(server: str, tool: str, raw: Any) -> ActionResult:
    raw = raw if isinstance(raw, Mapping) else {}
    parts = raw.get("content", [])
    texts = [
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, Mapping) and part.get("type", "text") == "text"
    ]
    other = [
        str(part.get("type"))
        for part in parts
        if isinstance(part, Mapping) and part.get("type", "text") != "text"
    ]
    text = "\n".join(t for t in texts if t)
    data: dict[str, Any] = {
        "server": server,
        "tool": tool,
        "content": text,
        "untrusted": True,
    }
    if other:
        data["non_text_parts"] = other
    if isinstance(raw.get("structuredContent"), Mapping):
        data["structured"] = dict(raw["structuredContent"])
    message = text if len(text) <= _MESSAGE_LIMIT else text[:_MESSAGE_LIMIT] + "..."
    if raw.get("isError"):
        return ActionResult(
            success=False,
            message=message or f"{tool} on {server} reported an error.",
            data=data,
            error="mcp_tool_error",
        )
    return ActionResult(
        success=True, message=message or f"{tool} on {server} finished.", data=data
    )


# --- the process-wide hub ------------------------------------------------------


_HUB: MCPHub | None = None
_HUB_LOCK = threading.Lock()


def get_hub() -> MCPHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = MCPHub()
        return _HUB


def reset_hub(hub: MCPHub | None = None) -> None:
    """Stop the current hub's servers and install ``hub`` (tests)."""
    global _HUB
    with _HUB_LOCK:
        old, _HUB = _HUB, hub
    if old is not None and old is not hub:
        old.close_all()


def spec_for(name: str) -> ActionSpec:
    """What :func:`grandpa.action_layer.catalogue.get` calls for ``mcp__`` names."""
    return get_hub().spec_for(name)


def call_action(name: str, arguments: Mapping[str, Any]) -> ActionResult:
    """The implementation every MCP ActionSpec names."""
    return get_hub().call(name, arguments)


@atexit.register
def _close_at_exit() -> None:  # pragma: no cover - interpreter shutdown
    hub = _HUB
    if hub is not None:
        hub.close_all()
