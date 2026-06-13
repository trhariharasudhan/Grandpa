"""``Grandpa chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from grandpa.cli._tool_names import resolve_tool_names
from grandpa.core.config import load_config
from grandpa.core.types import Message, Role
from grandpa.engine._base import EngineConnectionError, EngineModelNotFoundError
from grandpa.response_cleanup import GENERATION_ERROR_MESSAGE, clean_assistant_response


def _read_input(prompt: str = "You> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _engine_unavailable_message(engine_name: str, exc: EngineConnectionError) -> str:
    text = str(exc)
    if engine_name == "ollama" or "ollama" in text.lower():
        return (
            "Ollama is not available.\n"
            "Start it with: ollama serve\n"
            "Verify it with: ollama list\n"
            "Then retry the command."
        )
    return f"Inference engine '{engine_name}' is not available. {text}"


def _model_not_found_message(engine_name: str, exc: EngineModelNotFoundError) -> str:
    model = exc.model
    if engine_name == "ollama":
        return f'Ollama is running, but model "{model}" is not installed.'
    return f'Inference engine "{engine_name}" does not have model "{model}" installed.'


def _model_pull_guidance(model: str) -> str:
    return (
        f"Install it with: ollama pull {model}\n"
        "Verify it with: ollama list\n"
        "Then retry the command."
    )


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def chat(
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
) -> None:
    """Start an interactive multi-turn chat session.

    Commands during chat:
      /quit, /exit  — end session
      /clear        — clear conversation history
      /model        — show current model
      /help         — show available commands
      /history      — show conversation history
    """
    console = Console(stderr=True)

    config = load_config()

    # Resolve engine
    from grandpa.engine import get_engine
    from grandpa.intelligence import register_builtin_models

    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    model = model_name or config.intelligence.default_model
    if not model:
        from grandpa.engine import discover_engines, discover_models

        all_engines = discover_engines(config)
        all_models = discover_models(all_engines)
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model = engine_models[0]
        else:
            console.print("[red]No model available.[/red]")
            sys.exit(1)

    # Resolve agent (optional)
    agent = None
    agent_key = agent_name or config.agent.default_agent
    if agent_key and agent_key != "none":
        try:
            import grandpa.agents  # noqa: F401 — trigger registration
            from grandpa.core.events import EventBus
            from grandpa.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                kwargs: dict = {"bus": EventBus()}

                if getattr(agent_cls, "accepts_tools", False):
                    tool_names_list = resolve_tool_names(
                        tools,
                        getattr(config.tools, "enabled", None),
                        getattr(config.agent, "tools", None),
                    )
                    if tool_names_list:
                        import grandpa.tools  # noqa: F401 — trigger registration
                        from grandpa.core.registry import ToolRegistry
                        from grandpa.tools._stubs import BaseTool

                        tool_instances = []
                        for tname in tool_names_list:
                            if ToolRegistry.contains(tname):
                                tcls = ToolRegistry.get(tname)
                                if isinstance(tcls, type) and issubclass(
                                    tcls, BaseTool
                                ):
                                    tool_instances.append(tcls())
                                elif isinstance(tcls, BaseTool):
                                    tool_instances.append(tcls)
                        if tool_instances:
                            kwargs["tools"] = tool_instances
                    kwargs["max_turns"] = config.agent.max_turns

                    def _confirm(prompt: str) -> bool:
                        console.print(
                            f"[yellow]Confirm:[/yellow] {prompt} [y/N] ",
                            end="",
                        )
                        ans = input().strip().lower()
                        return ans in ("y", "yes")

                    kwargs["interactive"] = True
                    kwargs["confirm_callback"] = _confirm
                agent = agent_cls(engine, model, **kwargs)
        except Exception as exc:
            console.print(f"[yellow]Agent '{agent_key}' failed: {exc}[/yellow]")

    # Print banner
    console.print(
        f"[green bold]Grandpa Chat[/green bold]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]  Model: [cyan]{model}[/cyan]"
        f"  Agent: [cyan]{agent_key or 'direct'}[/cyan]\n"
        f"  Type /help for commands, /quit to exit.\n"
    )

    # Background-work status banner (disappears after first user message)
    from grandpa.cli._bg_state import get_status
    from grandpa.cli._chat_banner import render_startup_banner

    _banner = render_startup_banner(get_status())
    if _banner:
        console.print(f"[dim cyan]{_banner}[/dim cyan]")

    # Completion-notification dispatcher (fires once per task per session)
    from grandpa.cli._chat_notifications import NotificationDispatcher

    _notifications = NotificationDispatcher(get_status())

    # Conversation state
    history: List[Message] = []
    if system_prompt:
        history.append(Message(role=Role.SYSTEM, content=system_prompt))

    # REPL loop
    while True:
        for note in _notifications.diff(get_status()):
            console.print(f"[dim cyan]{note}[/dim cyan]")

        user_input = _read_input()
        if user_input is None:
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        cmd = user_input.lower()
        if cmd in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye![/dim]")
            break
        elif cmd == "/clear":
            history = []
            if system_prompt:
                history.append(Message(role=Role.SYSTEM, content=system_prompt))
            console.print("[dim]History cleared.[/dim]")
            continue
        elif cmd == "/model":
            console.print(
                f"Model: [cyan]{model}[/cyan]  Engine: [cyan]{engine_name}[/cyan]"
            )
            continue
        elif cmd == "/help":
            console.print(
                "[bold]Commands:[/bold]\n"
                "  /quit, /exit  — end session\n"
                "  /clear        — clear conversation\n"
                "  /model        — show model info\n"
                "  /history      — show conversation\n"
                "  /help         — this message"
            )
            continue
        elif cmd == "/history":
            if not history:
                console.print("[dim]No history yet.[/dim]")
            else:
                for msg in history:
                    role_str = msg.role if isinstance(msg.role, str) else msg.role.value
                    role = role_str.upper()
                    console.print(f"[bold]{role}:[/bold] {msg.content[:200]}")
            continue

        from grandpa.core_ai_brain import (
            build_brain_context,
            process_user_message,
            record_assistant_outcome,
        )
        from grandpa.memory_context import handle_memory_command, remember_conversation

        remember_conversation("user", user_input)
        brain_analysis = process_user_message(user_input)
        effective_user_input = brain_analysis.effective_text

        memory_result = handle_memory_command(effective_user_input)
        if not memory_result.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=memory_result.message))
            remember_conversation("assistant", memory_result.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=memory_result.message,
                kind=memory_result.kind,
                target=memory_result.target,
                status=memory_result.status,
            )
            console.print()
            console.print(Markdown(memory_result.message))
            console.print()
            continue

        from grandpa.local_actions import handle_local_action

        local_action = handle_local_action(effective_user_input)
        if not local_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=local_action.message))
            remember_conversation("assistant", local_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=local_action.message,
                kind=local_action.kind,
                target=local_action.target,
                status=local_action.status,
            )
            console.print()
            console.print(Markdown(local_action.message))
            console.print()
            continue

        from grandpa.file_assistant import handle_file_command

        file_action = handle_file_command(effective_user_input)
        if not file_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=file_action.message))
            remember_conversation("assistant", file_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=file_action.message,
                kind=getattr(file_action, "kind", "file"),
                target=getattr(file_action, "target", None),
                status=file_action.status,
            )
            console.print()
            console.print(Markdown(file_action.message))
            console.print()
            continue

        from grandpa.task_scheduler import handle_scheduler_command

        scheduler_action = handle_scheduler_command(effective_user_input)
        if not scheduler_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=scheduler_action.message))
            remember_conversation("assistant", scheduler_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=scheduler_action.message,
                kind=getattr(scheduler_action, "kind", "routine"),
                target=getattr(scheduler_action, "target", None),
                status=scheduler_action.status,
            )
            console.print()
            console.print(Markdown(scheduler_action.message))
            console.print()
            continue

        # Add user message
        history.append(Message(role=Role.USER, content=effective_user_input))

        # Generate response
        try:
            model_history = [
                Message(role=Role.SYSTEM, content=build_brain_context(brain_analysis)),
                *history,
            ]
            if agent is not None:
                response = agent.run(effective_user_input)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
            else:
                result = engine.generate(model_history, model=model)
                content = (
                    result.get("content", "")
                    if isinstance(result, dict)
                    else str(result)
                )
            content = clean_assistant_response(content)
            remember_conversation("assistant", content)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=content,
                kind="assistant",
                target=None,
                status="handled",
            )

            history.append(Message(role=Role.ASSISTANT, content=content))
            console.print()
            console.print(Markdown(content))
            console.print()
        except EngineModelNotFoundError as exc:
            console.print(
                f"\n[red]{_model_not_found_message(engine_name, exc)}[/red]\n"
            )
            if engine_name == "ollama":
                model_to_pull = exc.model
                if not click.confirm(f'Pull "{model_to_pull}" now?', default=False):
                    console.print(
                        f"\n[yellow]{_model_pull_guidance(model_to_pull)}[/yellow]\n"
                    )
                    raise click.exceptions.Exit(code=1) from exc
                console.print(
                    f'\n[cyan]Pulling "{model_to_pull}" from Ollama...[/cyan]'
                )
                try:
                    engine.pull_model(model_to_pull)
                except EngineConnectionError as pull_exc:
                    console.print(
                        f"\n[red]{_engine_unavailable_message(engine_name, pull_exc)}[/red]\n"
                    )
                    raise click.exceptions.Exit(code=1) from pull_exc
                console.print(
                    f'[green]Model "{model_to_pull}" was installed. '
                    "Please rerun the chat command.[/green]"
                )
                raise click.exceptions.Exit(code=1) from exc
            raise click.exceptions.Exit(code=1) from exc
        except EngineConnectionError as exc:
            console.print(
                f"\n[red]{_engine_unavailable_message(engine_name, exc)}[/red]\n"
            )
            raise click.exceptions.Exit(code=1) from exc
        except KeyboardInterrupt:
            console.print("\n[dim]Generation interrupted.[/dim]")
        except Exception:
            console.print(f"\n[red]{GENERATION_ERROR_MESSAGE}[/red]\n")


__all__ = ["chat"]
