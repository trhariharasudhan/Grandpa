"""``Grandpa ask --tool-loop`` -- the action layer's proving ground.

Off by default, and deliberately not wired into chat, voice, or any existing
dispatch. This is the one place the new layer can be driven end to end by a
real model, so that what it does and does not manage is observable before
anything depends on it.

The path here is short on purpose: resolve an engine and a model, run the
loop, print what happened. No keyword routing, no memory injection, no agent
-- the point is to see the layer's own behaviour, not the old path's.
"""

from __future__ import annotations

import json as json_mod
import sys
from typing import Any, Mapping

from rich.console import Console

from grandpa.action_layer.loop import DEFAULT_STEP_LIMIT, ToolsUnsupportedError, run
from grandpa.action_layer.model import Origin, RiskLevel

__all__ = ["run_tool_loop", "warn_if_cold"]

# Measured on the development machine: evaluating the tool definitions runs at
# roughly ten tokens a second, and the catalogue is a few thousand tokens. The
# number is only used to set expectations, so a rough rate is enough.
_PROMPT_TOKENS_PER_SECOND = 10.0
_CHARS_PER_TOKEN = 4

_RISK_COLOUR = {
    RiskLevel.LOW: "green",
    RiskLevel.MEDIUM: "yellow",
    RiskLevel.HIGH: "red",
    RiskLevel.BLOCKED: "red",
}


def _describe(parameters: Mapping[str, Any]) -> str:
    if not parameters:
        return ""
    return " ".join(f"{name}={value!r}" for name, value in sorted(parameters.items()))


def _confirm_callback(console: Console, auto_approve: bool):
    """Ask before a confirmable action runs, or refuse when nobody can answer."""
    if auto_approve:
        console.print(
            "[yellow]--yes: confirmable actions will run without prompting.[/yellow]"
        )
        return lambda *_: True

    from grandpa.cli._tty import stdin_is_interactive

    if not stdin_is_interactive():
        # No terminal means no one to ask. Returning None makes the executor
        # refuse rather than treating a piped "y" as consent.
        return None

    def confirm(action: str, parameters: Mapping[str, Any], risk: RiskLevel) -> bool:
        colour = _RISK_COLOUR.get(risk, "yellow")
        detail = _describe(parameters)
        console.print(
            f"[{colour}]{risk.value}[/{colour}] {action}"
            + (f" ({detail})" if detail else "")
        )
        console.print("Run it? [y/N] ", end="")
        try:
            answer = input().strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}

    return confirm


def warn_if_cold(console: Console, engine: object, model: str, tools: list) -> bool:
    """Say so when the first request will be slow, instead of appearing hung.

    Ollama evaluates the whole tool prompt on the first request after a model
    loads, and caches the result alongside the model. That first evaluation is
    minutes with a catalogue this size; every request afterwards is seconds,
    which is what keep_alive is set for. Silence for four minutes reads as a
    broken install, so this prints what is happening and roughly how long.

    Returns whether it warned, so a caller can tell the two cases apart.
    """
    client = getattr(engine, "_client", None)
    get = getattr(client, "get", None)
    if not callable(get):
        return False
    try:
        response = get("/api/ps")
        response.raise_for_status()
        loaded = {
            str(entry.get("model") or entry.get("name") or "")
            for entry in response.json().get("models", [])
        }
    except Exception:  # pragma: no cover - a probe, never a failure
        return False
    if model in loaded:
        return False

    tokens = len(json_mod.dumps(tools)) // _CHARS_PER_TOKEN
    minutes = max(1, round(tokens / _PROMPT_TOKENS_PER_SECOND / 60))
    console.print(
        f"[yellow]{model} is not loaded yet.[/yellow] The first request reads "
        f"{len(tools)} tool definitions (~{tokens} tokens), which takes about "
        f"{minutes} minute{'s' if minutes != 1 else ''} on this machine. "
        "Everything after it takes seconds: the model and its prompt stay "
        "loaded."
    )
    return True


def run_tool_loop(
    goal: str,
    *,
    model_name: str | None = None,
    engine_key: str | None = None,
    auto_approve: bool = False,
    output_json: bool = False,
    step_limit: int = DEFAULT_STEP_LIMIT,
) -> int:
    """Run one goal through the action layer. Returns a process exit code."""
    console = Console(stderr=True)

    from grandpa.core.config import load_config
    from grandpa.engine import get_engine
    from grandpa.runtime.exceptions import (
        RuntimeConnectionError,
        RuntimeModelLoadError,
        RuntimeModelNotFoundError,
    )

    config = load_config()
    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print(
            "[red]No engine is available, so there is nothing to run the loop "
            "with.[/red] Start Ollama, or check `Grandpa doctor`."
        )
        return 1
    engine_name, engine = resolved

    model = (
        model_name
        or config.intelligence.default_model
        or config.intelligence.fallback_model
    )
    if not model:
        console.print("[red]No model configured. Pass --model.[/red]")
        return 1

    confirm = _confirm_callback(console, auto_approve)

    def announce(entry) -> None:
        mark = "[green]ok[/green]" if entry.success else f"[red]{entry.error}[/red]"
        console.print(f"  · {entry.action} {mark}")

    from grandpa.action_layer.tool_schema import core_tool_definitions

    # The first request carries the core block, not the whole catalogue, so
    # that is what the estimate has to be based on.
    warn_if_cold(console, engine, model, core_tool_definitions())

    try:
        result = run(
            goal,
            engine=engine,
            model=model,
            confirm_callback=confirm,
            origin=Origin.USER_CLI,
            step_limit=step_limit,
            on_action=None if output_json else announce,
        )
    except ToolsUnsupportedError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    except RuntimeConnectionError as exc:
        # A local model that has to load can take longer than the adapter's
        # HTTP timeout, especially with the whole catalogue in the prompt.
        # That is a slow backend, not a crash; say so instead of a traceback.
        console.print(
            f"[red]{engine_name} stopped answering while running the loop: {exc}[/red]"
        )
        console.print(
            "A large local model may need longer than the adapter's timeout to "
            "load, especially with the whole catalogue in the prompt. Try a "
            "smaller model with --model."
        )
        return 1
    except (RuntimeModelNotFoundError, RuntimeModelLoadError) as exc:
        console.print(f"[red]{model} could not be used: {exc}[/red]")
        return 1

    if output_json:
        sys.stdout.write(
            json_mod.dumps(
                {
                    "goal": goal,
                    "engine": engine_name,
                    "model": result.model,
                    "content": result.text,
                    "steps": result.steps,
                    "stopped_at_limit": result.stopped_at_limit,
                    "loaded_domains": list(result.loaded_domains),
                    "trace": [
                        {
                            "step": entry.step,
                            "action": entry.action,
                            "parameters": dict(entry.parameters),
                            "success": entry.success,
                            "message": entry.message,
                            "error": entry.error,
                        }
                        for entry in result.trace
                    ],
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    else:
        sys.stdout.write(result.text.rstrip() + "\n")
        if result.trace:
            console.print(
                f"[dim]{len(result.trace)} action(s) in {result.steps} step(s) "
                f"via {result.model}[/dim]"
            )

    failed = [entry for entry in result.trace if not entry.success]
    if result.stopped_at_limit:
        return 1
    return 1 if failed and not any(entry.success for entry in result.trace) else 0
