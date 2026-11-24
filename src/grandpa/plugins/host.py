"""Finding, enabling and running plugins (G2).

A plugin is a folder ``plugins/<name>/`` holding ``plugin.toml`` and one
Python file. Folders are searched in ``~/.grandpa/plugins`` and the
``plugins`` folder of the Grandpa checkout (``GRANDPA_PLUGINS_DIR``, a
``;``-separated list on Windows, replaces both).

Each tool in a manifest becomes the action ``plugin__<name>__<tool>`` and runs
only through the action layer's executor, so it is validated, confirmed and
audited like every other action. The rules:

* **Off until enabled.** ``grandpa plugin enable <name>`` shows the
  permissions, asks, and records a fingerprint of every file in the folder.
  If any file changes afterwards the plugin stops working until it is
  enabled again.
* **Risk only goes up.** A tool is at least as risky as its permissions
  (``network`` MEDIUM, ``files`` and ``system`` HIGH, ``actions:<x>`` as
  risky as ``x``). Anything above LOW asks first, every time.
* **Permission check.** ``ctx.run_action`` runs only actions the manifest
  lists as ``actions:<name>``, through the executor, with the same way of
  asking the user that the plugin's own call had. A plugin has no way to
  answer a confirmation itself. Event handlers have nobody to ask, so
  anything that needs a yes is refused there.
* **Kill switch.** ``GRANDPA_PLUGINS_OFF=1`` makes every plugin action unknown.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Callable, Mapping

from grandpa.action_layer.catalogue import (
    PLUGIN_PREFIX,
    ActionSpec,
    Binding,
    Confirmation,
)
from grandpa.action_layer.model import ActionResult, RiskLevel
from grandpa.plugins.manifest import (
    ACTION_PERMISSION,
    PERMISSIONS,
    Manifest,
    ManifestError,
    ToolDecl,
    check_code,
    max_risk,
    read_manifest,
)

logger = logging.getLogger(__name__)

__all__ = [
    "IMPLEMENTATION",
    "PLUGIN_PREFIX",
    "PluginContext",
    "PluginHost",
    "PluginInfo",
    "action_name",
    "call_action",
    "fingerprint",
    "is_off",
    "tool_spec",
    "get_host",
    "plugin_dirs",
    "reset_host",
    "spec_for",
    "start_events",
]

IMPLEMENTATION = "grandpa.plugins.host.call_action"
_EVENT_QUEUE_SIZE = 256

ConfirmCallback = Callable[[str, Mapping[str, Any], RiskLevel], bool]


def is_off() -> bool:
    value = os.environ.get("GRANDPA_PLUGINS_OFF", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def plugin_dirs() -> list[Path]:
    override = os.environ.get("GRANDPA_PLUGINS_DIR")
    if override:
        return [Path(p).expanduser() for p in override.split(os.pathsep) if p.strip()]
    from grandpa.runtime_paths import grandpa_home

    dirs = [grandpa_home() / "plugins"]
    checkout = Path(__file__).resolve().parents[3] / "plugins"
    if checkout.is_dir():
        dirs.append(checkout)
    return dirs


def state_path() -> Path:
    from grandpa.runtime_paths import runtime_path

    return runtime_path("plugins.json")


def user_config_path() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "plugins.toml"


def fingerprint(folder: Path) -> str:
    """SHA-256 over every file in the folder (names and bytes)."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def action_name(plugin: str, tool: str) -> str:
    return f"{PLUGIN_PREFIX}{plugin}__{tool}"


def _split(name: str) -> tuple[str, str]:
    if not name.startswith(PLUGIN_PREFIX):
        raise KeyError(name)
    plugin, sep, tool = name[len(PLUGIN_PREFIX) :].partition("__")
    if not sep or not plugin or not tool:
        raise KeyError(name)
    return plugin, tool


def _load_state() -> dict[str, Any]:
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"enabled": {}}
    except (OSError, ValueError):
        logger.warning("%s is unreadable; treating every plugin as disabled", path)
        return {"enabled": {}}
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), dict):
        return {"enabled": {}}
    return data


def _save_state(state: Mapping[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _user_config(name: str) -> dict[str, Any]:
    import tomllib

    path = user_config_path()
    if not path.is_file():
        return {}
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get(name, {})
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning("%s could not be read; using plugin defaults", path)
        return {}
    return dict(table) if isinstance(table, Mapping) else {}


# --- what a plugin sees ----------------------------------------------------------


class PluginContext:
    """The only door from a plugin back into Grandpa.

    The way of asking the user lives in a closure, not an attribute, so a
    plugin cannot swap it for one that always says yes (the code check
    refuses the dunder attributes that would reach into a closure).
    """

    __slots__ = ("name", "config", "log", "run_action")

    def __init__(
        self,
        manifest: Manifest,
        config: Mapping[str, Any],
        confirm_callback: ConfirmCallback | None,
    ) -> None:
        plugin = manifest.name
        allowed = manifest.allowed_actions
        plugin_logger = logging.getLogger(f"grandpa.plugin.{plugin}")

        def log(message: str) -> None:
            plugin_logger.info("%s", message)

        def run_action(action: str, **parameters: Any) -> ActionResult:
            """Run a Grandpa action the manifest lists as ``actions:<name>``."""
            if action not in allowed:
                return ActionResult.failed(
                    "plugin_permission_denied",
                    message=(
                        f"Plugin {plugin!r} may not run {action!r}: its manifest "
                        f"does not list '{ACTION_PERMISSION}{action}'."
                    ),
                )
            from grandpa.action_layer.catalogue import get
            from grandpa.action_layer.executor import execute
            from grandpa.action_layer.model import ActionRequest, Origin

            try:
                spec = get(action)
            except KeyError:
                return ActionResult.failed(
                    "unknown_action", message=f"There is no action called {action!r}."
                )
            request = ActionRequest(
                action=spec.name,
                parameters=parameters,
                origin=Origin.SKILL,
                risk=spec.risk,
                requires_confirmation=spec.requires_confirmation,
            )
            return execute(request, confirm_callback=confirm_callback)

        object.__setattr__(self, "name", plugin)
        object.__setattr__(self, "config", MappingProxyType(dict(config)))
        object.__setattr__(self, "log", log)
        object.__setattr__(self, "run_action", run_action)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("the plugin context is read-only")


# --- discovery -------------------------------------------------------------------


@dataclass(frozen=True)
class PluginInfo:
    name: str
    folder: Path
    state: str
    """enabled, disabled, changed (files differ from when enabled) or broken."""
    manifest: Manifest | None = None
    problem: str = ""
    fingerprint: str = ""


def _tool_risk(manifest: Manifest, tool: ToolDecl) -> RiskLevel:
    levels = [tool.risk]
    for permission in manifest.permissions:
        if permission in PERMISSIONS:
            levels.append(PERMISSIONS[permission])
        elif permission.startswith(ACTION_PERMISSION):
            target = permission[len(ACTION_PERMISSION) :]
            try:
                from grandpa.action_layer.catalogue import get

                levels.append(get(target).risk)
            except KeyError:
                levels.append(RiskLevel.HIGH)  # unknown today: assume the worst
    return max_risk(*levels)


class PluginHost:
    def __init__(self, dirs: list[Path] | None = None) -> None:
        self._dirs = dirs
        self._modules: dict[tuple[str, str], ModuleType] = {}
        self._lock = threading.RLock()
        self._events: queue.Queue[tuple[Callable[..., Any], Any]] | None = None
        self._subscribed: list[tuple[Any, Callable[..., Any]]] = []

    @property
    def dirs(self) -> list[Path]:
        return self._dirs if self._dirs is not None else plugin_dirs()

    def discover(self) -> list[PluginInfo]:
        enabled = _load_state()["enabled"]
        found: dict[str, PluginInfo] = {}
        for base in self.dirs:
            if not base.is_dir():
                continue
            for folder in sorted(p for p in base.iterdir() if p.is_dir()):
                if not (folder / "plugin.toml").is_file():
                    continue
                name = folder.name
                if name in found:
                    logger.warning("plugin %r in %s is shadowed", name, folder)
                    continue
                found[name] = self._inspect(folder, enabled.get(name))
        return list(found.values())

    @staticmethod
    def _inspect(folder: Path, record: Any) -> PluginInfo:
        name = folder.name
        try:
            manifest = read_manifest(folder)
            check_code(manifest)
            print_ = fingerprint(folder)
        except (ManifestError, OSError) as exc:
            return PluginInfo(name, folder, "broken", problem=str(exc))
        if not isinstance(record, Mapping):
            return PluginInfo(name, folder, "disabled", manifest, fingerprint=print_)
        if record.get("fingerprint") != print_:
            return PluginInfo(
                name,
                folder,
                "changed",
                manifest,
                problem="its files changed after it was enabled; enable it again",
                fingerprint=print_,
            )
        return PluginInfo(name, folder, "enabled", manifest, fingerprint=print_)

    def find(self, name: str) -> PluginInfo:
        for info in self.discover():
            if info.name == name:
                return info
        raise KeyError(f"no plugin called {name!r} in {', '.join(map(str, self.dirs))}")

    def enable(self, name: str) -> PluginInfo:
        info = self.find(name)
        if info.state == "broken":
            raise ManifestError(info.problem)
        state = _load_state()
        state["enabled"][name] = {
            "fingerprint": info.fingerprint,
            "folder": str(info.folder),
        }
        _save_state(state)
        return self.find(name)

    def disable(self, name: str) -> bool:
        state = _load_state()
        removed = state["enabled"].pop(name, None) is not None
        if removed:
            _save_state(state)
        with self._lock:
            for key in [k for k in self._modules if k[0] == name]:
                del self._modules[key]
        return removed

    def _active(self, name: str) -> PluginInfo:
        if is_off():
            raise KeyError("plugins are off (GRANDPA_PLUGINS_OFF is set)")
        info = self.find(name)
        if info.state != "enabled":
            reason = info.problem or "it is not enabled ('grandpa plugin enable')"
            raise KeyError(f"plugin {name!r} is {info.state}: {reason}")
        return info

    def _module(self, info: PluginInfo) -> ModuleType:
        assert info.manifest is not None
        key = (info.name, info.fingerprint)
        with self._lock:
            module = self._modules.get(key)
            if module is not None:
                return module
            path = info.folder / info.manifest.module
            module_name = f"grandpa_plugin_{info.name.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules.pop(module_name, None)
            self._modules[key] = module
            return module

    def _context(
        self, manifest: Manifest, confirm_callback: ConfirmCallback | None
    ) -> PluginContext:
        config = manifest.config_defaults()
        for key, value in _user_config(manifest.name).items():
            if key in config:
                config[key] = value
            else:
                logger.warning("plugins.toml: %s has no option %r", manifest.name, key)
        return PluginContext(manifest, config, confirm_callback)

    def spec_for(self, action: str) -> ActionSpec:
        plugin, tool_name = _split(action)
        info = self._active(plugin)
        assert info.manifest is not None
        for tool in info.manifest.tools:
            if tool.name == tool_name:
                return tool_spec(info.manifest, tool)
        raise KeyError(f"plugin {plugin!r} has no tool {tool_name!r}")

    def call(
        self,
        action: str,
        arguments: Mapping[str, Any],
        confirm_callback: ConfirmCallback | None = None,
    ) -> ActionResult:
        """Run one tool. Only the executor calls this, after it has asked."""
        try:
            plugin, tool_name = _split(action)
            info = self._active(plugin)
        except KeyError as exc:
            return ActionResult.failed(
                "plugin_unavailable", message=str(exc.args[0] if exc.args else exc)
            )
        assert info.manifest is not None
        tool = next((t for t in info.manifest.tools if t.name == tool_name), None)
        if tool is None:
            return ActionResult.failed(
                "unknown_action", message=f"{plugin!r} has no tool {tool_name!r}."
            )
        function = getattr(self._module(info), tool.function)
        ctx = self._context(info.manifest, confirm_callback)
        returned = function(ctx, **dict(arguments))
        if isinstance(returned, ActionResult):
            return returned
        if isinstance(returned, Mapping):
            return ActionResult(
                success=True, message=f"{tool.name} finished.", data=dict(returned)
            )
        return ActionResult(success=True, message=str(returned))

    # --- events ------------------------------------------------------------------

    def start_events(self) -> int:
        """Subscribe every enabled plugin's event handlers. Returns how many."""
        if is_off():
            return 0
        from grandpa.core.events import EventType, get_event_bus

        self.stop_events()
        bus = get_event_bus()
        with self._lock:
            if self._events is None:
                self._events = queue.Queue(maxsize=_EVENT_QUEUE_SIZE)
                threading.Thread(
                    target=self._event_worker,
                    args=(self._events,),
                    name="grandpa-plugin-events",
                    daemon=True,
                ).start()
            outbox = self._events
        count = 0
        for info in self.discover():
            if info.state != "enabled" or info.manifest is None:
                continue
            for hook in info.manifest.events:
                try:
                    handler = getattr(self._module(info), hook.handler)
                except Exception:  # noqa: BLE001 - one bad plugin must not stop others
                    logger.warning("plugin %r failed to load", info.name, exc_info=True)
                    break
                ctx = self._context(info.manifest, None)  # nobody to ask

                def deliver(event: Any, _h=handler, _c=ctx) -> None:
                    try:
                        outbox.put_nowait((lambda: _h(_c, dict(event.data)), None))
                    except queue.Full:
                        logger.debug("plugin event dropped")

                event_type = EventType(hook.on)
                bus.subscribe(event_type, deliver)
                self._subscribed.append((event_type, deliver))
                count += 1
        return count

    def stop_events(self) -> None:
        from grandpa.core.events import get_event_bus

        bus = get_event_bus()
        for event_type, callback in self._subscribed:
            bus.unsubscribe(event_type, callback)
        self._subscribed.clear()

    @staticmethod
    def _event_worker(inbox: queue.Queue) -> None:
        while True:
            job, _ = inbox.get()
            try:
                job()
            except Exception:  # noqa: BLE001 - a plugin handler must not kill the worker
                logger.warning("plugin event handler failed", exc_info=True)
            finally:
                inbox.task_done()


def _schema(tool: ToolDecl) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: dict(v) for k, v in tool.parameters.items()},
        "required": list(tool.required),
        "additionalProperties": False,
    }


def tool_spec(manifest: Manifest, tool: ToolDecl) -> ActionSpec:
    risk = _tool_risk(manifest, tool)
    return ActionSpec(
        name=action_name(manifest.name, tool.name),
        description=f"[plugin '{manifest.name}'] {tool.description}",
        parameters=_schema(tool),
        risk=risk,
        confirmation=Confirmation.NONE if risk is RiskLevel.LOW else Confirmation.LAYER,
        implementation=IMPLEMENTATION,
        notes="A tool from a plugin. Anything above LOW asks first.",
        binding=Binding.PLUGIN_TOOL,
    )


# --- the process-wide host -------------------------------------------------------

_HOST: PluginHost | None = None
_HOST_LOCK = threading.Lock()


def get_host() -> PluginHost:
    global _HOST
    with _HOST_LOCK:
        if _HOST is None:
            _HOST = PluginHost()
        return _HOST


def reset_host(host: PluginHost | None = None) -> None:
    global _HOST
    with _HOST_LOCK:
        old, _HOST = _HOST, host
    if old is not None and old is not host:
        old.stop_events()


def spec_for(name: str) -> ActionSpec:
    """What :func:`grandpa.action_layer.catalogue.get` calls for ``plugin__`` names."""
    return get_host().spec_for(name)


def call_action(
    name: str,
    arguments: Mapping[str, Any],
    confirm_callback: ConfirmCallback | None = None,
) -> ActionResult:
    """The implementation every plugin ActionSpec names."""
    return get_host().call(name, arguments, confirm_callback)


def start_events() -> int:
    return get_host().start_events()
