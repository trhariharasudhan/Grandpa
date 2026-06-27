"""``Grandpa chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import re
import subprocess
import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from grandpa.cli._tool_names import resolve_tool_names
from grandpa.cli.input_ui import read_chat_input, select_from_list
from grandpa.cli.theme import (
    render_assistant_response,
    render_chat_home,
    render_help,
)
from grandpa.core.config import load_config
from grandpa.core.types import Message, Role
from grandpa.engine._base import EngineConnectionError, EngineModelNotFoundError
from grandpa.response_cleanup import GENERATION_ERROR_MESSAGE, clean_assistant_response

NATURAL_MEMORY_LIST_INTENTS = {
    "show my memories",
    "list my memories",
    "show memories",
    "list memories",
}

NATURAL_MEMORY_ALL_INTENTS = {
    "show all memories",
    "list all memories",
}

NATURAL_MEMORY_RECALL_INTENTS = {
    "what do you remember",
    "what do you remember about me",
    "what do you know about me",
}

NATURAL_REMINDER_LIST_INTENTS = {
    "do i have any reminders",
    "list my reminders",
    "show me my reminders",
    "show my reminders",
    "what are my reminders",
    "what reminder do i have",
    "show reminders",
    "list reminders",
    "what reminders do i have",
}


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


def _get_ollama_models() -> list[str]:
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        check=False,
    )

    models = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])

    return models


def _create_one_shot_reminder(text: str, *, store=None) -> str | None:
    from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase
    from grandpa.reminders import ReminderStore

    try:
        parsed = parse_reminder_phrase(text)
    except ReminderParseError:
        return None
    reminder_store = store or ReminderStore()
    reminder = reminder_store.create(
        parsed.message,
        parsed.due_at,
        source={
            "cli": "grandpa chat",
            "input": text,
            "matched_expression": parsed.matched_expression,
        },
    )
    return f"Reminder created: {reminder.message} at {reminder.due_at.isoformat()}."


def _handle_memory_slash_command(command: str, *, store=None) -> str | None:
    if not command.startswith("/memory"):
        return None
    from grandpa.memory_context import MemoryStore

    memory_store = store or MemoryStore()
    parts = command.split(maxsplit=2)
    if len(parts) == 1:
        return (
            "Memory commands:\n"
            "- /memory list\n"
            "- /memory all\n"
            "- /memory search <query>\n"
            "- /memory search <query> --all\n"
            "- /memory forget <query or id>\n"
            "You can also say: remember my name is Hari"
        )
    action = parts[1].lower()
    argument = parts[2].strip() if len(parts) > 2 else ""
    if action == "list":
        return _format_user_memories(memory_store.list_memories())
    if action == "all":
        return _format_memories(memory_store.list_memories())
    if action == "search":
        if not argument:
            return "Usage: /memory search <query>"
        include_internal = _strip_all_flag(argument)
        results = memory_store.search_memories(include_internal[0])
        results = _filter_memory_search_results(include_internal[0], results)
        if not include_internal[1]:
            results = _user_facing_memories(results)
        return _format_memories(results, heading="Matching memories:")
    if action == "forget":
        if not argument:
            return "Usage: /memory forget <query or id>"
        removed = memory_store.forget(argument)
        if removed:
            noun = "memory" if removed == 1 else "memories"
            return f"Forgot {removed} {noun}."
        return "No matching memory found."
    return "Unknown memory command. Try /memory for help."


def _handle_reminders_slash_command(command: str, *, store=None) -> str | None:
    if not command.startswith("/reminders"):
        return None
    from grandpa.reminders import ReminderStore

    reminder_store = store or ReminderStore()
    parts = command.split(maxsplit=2)
    if len(parts) == 1:
        return (
            "Reminder commands:\n"
            "- /reminders list\n"
            "- /reminders all\n"
            "- /reminders cancel <id>\n"
            "You can also say: remind me in 30 minutes to drink water"
        )
    action = parts[1].lower()
    argument = parts[2].strip() if len(parts) > 2 else ""
    if action == "list":
        return _format_reminders(reminder_store.list(status="pending"), empty="No pending reminders found.")
    if action == "all":
        return _format_reminders(reminder_store.list(), empty="No reminders found.")
    if action == "cancel":
        if not argument:
            return "Usage: /reminders cancel <id>"
        reminder = reminder_store.cancel(argument)
        if reminder is None:
            return "Reminder not found."
        if reminder.status == "cancelled":
            return "Reminder cancelled."
        return f"Reminder is already {reminder.status}."
    return "Unknown reminder command. Try /reminders for help."


def _handle_natural_assistant_intent(text: str, *, memory_store=None, reminder_store=None) -> str | None:
    memory_message = _handle_natural_memory_intent(text, store=memory_store)
    if memory_message is not None:
        return memory_message
    return _handle_natural_reminder_intent(text, store=reminder_store)


def _handle_natural_memory_intent(text: str, *, store=None) -> str | None:
    normalized = _normalize_local_intent(text)
    if normalized in NATURAL_MEMORY_ALL_INTENTS:
        from grandpa.memory_context import MemoryStore

        memory_store = store or MemoryStore()
        return _format_memories(memory_store.list_memories())
    if normalized in NATURAL_MEMORY_LIST_INTENTS:
        from grandpa.memory_context import MemoryStore

        memory_store = store or MemoryStore()
        return _format_user_memories(memory_store.list_memories())
    if normalized in NATURAL_MEMORY_RECALL_INTENTS:
        from grandpa.memory_context import MemoryStore, handle_memory_command

        memory_store = store or MemoryStore()
        result = handle_memory_command(text, store=memory_store)
        return result.message if not result.should_fallback else _format_memories(memory_store.list_memories())
    return None


def _handle_natural_reminder_intent(text: str, *, store=None) -> str | None:
    normalized = _normalize_local_intent(text)
    if _is_natural_reminder_list_intent(normalized):
        from grandpa.reminders import ReminderStore

        reminder_store = store or ReminderStore()
        return _format_reminders(
            reminder_store.list(status="pending"),
            empty=(
                "No pending reminders found. You can create one with: "
                "remind me in 30 minutes to drink water"
            ),
        )
    cancel_match = re.match(r"^(cancel|delete|remove)\s+reminder\s+(.+)$", normalized)
    if cancel_match:
        from grandpa.reminders import ReminderStore

        reminder_store = store or ReminderStore()
        reminder_id = cancel_match.group(2).strip()
        reminder = reminder_store.cancel(reminder_id)
        if reminder is None:
            return "Reminder not found. Use /reminders list to see reminder IDs."
        if reminder.status == "cancelled":
            return "Reminder cancelled."
        return f"Reminder is already {reminder.status}."
    return None


def _is_natural_reminder_list_intent(normalized: str) -> bool:
    if normalized in NATURAL_REMINDER_LIST_INTENTS:
        return True
    return bool(
        re.fullmatch(r"(show|list)\s+(me\s+)?(my\s+)?reminders", normalized)
        or re.fullmatch(r"what\s+reminders?\s+do\s+i\s+have", normalized)
        or re.fullmatch(r"what\s+are\s+my\s+reminders", normalized)
        or re.fullmatch(r"do\s+i\s+have\s+any\s+reminders", normalized)
    )


def _format_memories(items: list[dict], *, heading: str = "Saved memories:") -> str:
    if not items:
        return "No memories found."
    lines = [heading]
    for item in items[:20]:
        lines.append(f"- #{item['id']} {item['category']}/{item['key']}: {item['value']}")
    return "\n".join(lines)


def _format_user_memories(items: list[dict]) -> str:
    visible = _user_facing_memories(items)
    if not visible:
        return (
            "No user-facing memories found.\n"
            "Use /memory all to show internal memories.\n"
            "You can save one with: remember my name is Hari"
        )
    grouped: dict[str, list[dict]] = {
        "Personal": [],
        "Projects": [],
        "Tools & Preferences": [],
        "Other": [],
    }
    for item in visible[:15]:
        grouped[_memory_group(item)].append(item)
    lines = ["Saved memories:"]
    for heading, group_items in grouped.items():
        if not group_items:
            continue
        lines.append("")
        lines.append(heading)
        for item in group_items:
            lines.append(f"- {_friendly_memory_line(item)}")
    lines.append("")
    lines.append("Use /memory all to show internal memories.")
    return "\n".join(lines)


def _user_facing_memories(items: list[dict]) -> list[dict]:
    visible = [item for item in items if _is_user_facing_memory(item)]
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in visible:
        fingerprint = _memory_fingerprint(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(item)
    return deduped


def _filter_memory_search_results(query: str, items: list[dict]) -> list[dict]:
    query_terms = _memory_search_terms(query)
    if not query_terms:
        return []
    return [item for item in items if _memory_matches_query_terms(item, query_terms)]


def _memory_matches_query_terms(item: dict, query_terms: list[str]) -> bool:
    candidate = _normalize_memory_text(
        " ".join(
            str(item.get(field) or "")
            for field in ("category", "key", "value", "source")
        )
    )
    if not candidate:
        return False
    phrase = " ".join(query_terms)
    if len(query_terms) > 1 and phrase in candidate:
        return True
    candidate_terms = set(candidate.split())
    return all(term in candidate_terms for term in query_terms)


def _memory_search_terms(query: str) -> list[str]:
    return _normalize_memory_text(query).split()


def _is_user_facing_memory(item: dict) -> bool:
    category = str(item.get("category") or "").lower()
    key = str(item.get("key") or "").lower()
    source = str(item.get("source") or "").lower()
    value = str(item.get("value") or "").lower()
    internal_haystack = f"{category} {key} {value} {source}"
    if category in {"work_context", "diagnostics"}:
        return False
    internal_markers = (
        "agent_goal",
        "burn_in",
        "burn in",
        "diagnostics",
        "multi_agent",
        "diagnostic",
        "readiness",
        "browser",
        "planner",
        "generated",
        "test marker",
        "validation marker",
        "work_context",
    )
    return not any(marker in internal_haystack for marker in internal_markers)


def _memory_fingerprint(item: dict) -> str:
    value = _normalize_memory_text(str(item.get("value") or ""))
    if value:
        return f"{_memory_group(item)}:{value}"
    return f"{_memory_group(item)}:{_normalize_memory_text(str(item.get('key') or ''))}"


def _normalize_memory_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _memory_group(item: dict) -> str:
    category = str(item.get("category") or "")
    key = str(item.get("key") or "")
    key_lower = key.lower()
    if category == "project" or "project" in key:
        return "Projects"
    if (
        category in {"preferences", "apps_tools"}
        or key_lower.startswith("uses")
        or key_lower.startswith("preferred")
    ):
        return "Tools & Preferences"
    if category == "people" or key in {"name", "my_name"}:
        return "Personal"
    return "Other"


def _friendly_memory_line(item: dict) -> str:
    key = str(item.get("key") or "").replace("_", " ")
    value = str(item.get("value") or "")
    if key:
        return f"{key}: {value}"
    return value


def _strip_all_flag(argument: str) -> tuple[str, bool]:
    parts = argument.split()
    filtered = [part for part in parts if part != "--all"]
    return " ".join(filtered).strip(), len(filtered) != len(parts)


def _format_reminders(items: list, *, empty: str) -> str:
    if not items:
        return empty
    lines = ["Reminders:"]
    for reminder in items[:20]:
        lines.append(f"- {reminder.id} [{reminder.status}] {reminder.message} at {reminder.due_at.isoformat()}")
    return "\n".join(lines)


def _normalize_local_intent(text: str) -> str:
    return " ".join(text.lower().strip(" ?!.").split())


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
    console.print()

    render_chat_home(
        console=console,
        engine=engine_name,
        model=model,
        agent=agent_key or "direct",
    )

    from grandpa.cli._bg_state import get_status

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

        try:
            user_input = read_chat_input()
        except Exception as exc:
            if "console" not in exc.__class__.__name__.lower() and "console" not in str(exc).lower():
                raise
            user_input = _read_input()

        if user_input is not None:
            console.print(f"> {user_input}")

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
            models = _get_ollama_models()

            if not models:
                console.print("[red]No Ollama models found.[/red]")
                continue

            selected = select_from_list("Select Model", models)

            if selected:
                model = selected
                console.print(f"[green]✓[/green] Model changed to [cyan]{model}[/cyan]")

            continue
        elif cmd == "/help":
            render_help(console)
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
        elif cmd.startswith("/memory"):
            console.print(_handle_memory_slash_command(user_input) or "Unknown memory command.")
            continue
        elif cmd.startswith("/reminders"):
            console.print(_handle_reminders_slash_command(user_input) or "Unknown reminder command.")
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

        natural_intent_message = _handle_natural_assistant_intent(effective_user_input)
        if natural_intent_message is not None:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=natural_intent_message))
            remember_conversation("assistant", natural_intent_message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=natural_intent_message,
                kind="local",
                target=None,
                status="handled",
            )
            console.print()
            console.print(Markdown(natural_intent_message))
            console.print()
            continue

        reminder_message = _create_one_shot_reminder(effective_user_input)
        if reminder_message is not None:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=reminder_message))
            remember_conversation("assistant", reminder_message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=reminder_message,
                kind="reminder",
                target=None,
                status="handled",
            )
            console.print()
            console.print(Markdown(reminder_message))
            console.print()
            continue

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
            render_assistant_response(console, Markdown(content))
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
