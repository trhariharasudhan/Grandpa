---
name: grandpa-agent-engineering
description: Work on how Grandpa thinks and talks - the path from a user message to a reply (phrase handlers, intent router, model tool loop), the identity and system prompts, the 8-message conversation window, context and token budget, the local conversational brain (language en/ta/ta-en, tone, follow-ups), response cleanup, and the agent and planner frameworks (agents/, agent/, planner/, goal mode, loop guard). Use when replies are wrong, vague, repetitive or forget context, when changing a prompt, when the model calls the wrong tool or loops, or when building multi-step or autonomous behaviour.
---

# GRANDPA agent and conversation engineering

The model is the least predictable part of Grandpa. This skill keeps changes to
prompts, context and agents measured and safe. Model choice, Ollama and
latency belong to `grandpa-local-models`; the catalogue and executor belong to
`grandpa-action-layer`.

## How a message becomes a reply (chat and voice)

```
text / transcript
  │ 1. deterministic first: grandpa.local.handle_local_action (allowlisted
  │    phrases), cli/_*_route.py, router/intent_router.py, workflow phrase triggers
  │ 2. brain context: core_ai_brain.process_user_message → language, tone,
  │    follow-up resolution, habits (local, deterministic, no cloud)
  │ 3. model turn: action_layer/loop.py (tool loop, on by default in chat via
  │    [tools] chat_tool_loop) with history[-CONVERSATION_WINDOW_MESSAGES:]
  │       every tool call → action_layer.executor.execute (confirm + audit)
  │ 4. response_cleanup.clean_assistant_response → strip reasoning, emoji,
  │    duplicates, over-length
  ▼
reply (printed, spoken by TTS, shown in bubble/avatar)
```

Key facts (verified on `fde2164`):

| Thing | Where | Notes |
|---|---|---|
| Conversation window | `core/types.py: CONVERSATION_WINDOW_MESSAGES = 8` | four exchanges; the docstring records the measurements behind 8. Shared by chat and voice |
| Tool loop | `action_layer/loop.py` | `DEFAULT_STEP_LIMIT = 8` model turns; short core tool list plus `load_tools(<subject>)` for other domains; the subject list is sorted so the prompt stays byte-identical (Ollama prompt cache) |
| Identity | `prompt/identity.py` | Grandpa is the name; Odin is the model family; never claim to be Qwen/Llama/etc.; plain text, **no emoji** |
| Prompt limits | `core/config.py: SystemPromptConfig`, `CompressionConfig` | soul 4000, memory 2500, user 1500 chars; head_tail truncation |
| Brain | `core_ai_brain.py` | `detect_language` returns `en`, `ta`, `ta-en`; `resolve_follow_up` |
| Cleanup | `response_cleanup.py` | dependency-free, used by CLI, server and engine |
| Loop guard | `agents/loop_guard.py` | detects degenerate tool-calling loops |

## Agent and planner frameworks (duplicated; know which one you touch)

| Package | What it is | Reached from |
|---|---|---|
| `agents/` | inherited framework: `OrchestratorAgent` (function_calling or structured ReAct), `NativeReActAgent`, `goal_mode` (Observe → Plan → Act → Reflect, bounded), manager | `grandpa agents`, `voice/session.py`, `server/api_routes.py` |
| `agent/` | Agent Runtime V1, incl. `agent/development/` (retained as product, AD-020) | `cli/agent_run_cmd.py` |
| `planner/` | Executive Planner: verified, bounded, session-scoped state machine | `cli/plan_cmd.py`, `voice/operator.py`, `router/intent_router.py` |

AD-008/AD-009 say `agents/` is the framework and `planner/` the planner, but
they are not consolidated. `docs/audit/CAPABILITY-MAP.md` rates goal
understanding **BROKEN**. Don't claim autonomy that the code does not have.

User docs: `docs/user-guide/executive-planner.md`, `agent-execution-v2.md`,
`project-engineer-mode-v1.md`.

## Rules

1. **Model output never bypasses policy.** Agents, planners and skills act only
   through the executor, with the right `Origin` (`MODEL`, `AGENT`, `PLAN`,
   `SKILL`). AD-022: safety rests on the policy layer.
2. **External text is data, not instructions.** Email, web pages, OCR text and
   file contents can carry prompt injection. Keep them in clearly delimited
   context; `gmail/safety.py` and `web_search/safety.py` show the pattern.
3. **Bounded loops.** Every loop has a step limit and a stop condition, and it
   reports partial progress honestly. Never raise a limit to make a demo pass.
4. **Keep the prompt cache warm.** Tool lists and system prompts must be
   deterministic (sorted, no timestamps) or every turn pays the cold
   prompt-evaluation cost (minutes with the full catalogue; see
   `runtime/ollama_adapter.py`).
5. **Never say done unless a tool result says so.** This is in the loop's own
   system prompt. Keep it.
6. **Tamil and Tanglish are normal input.** Test new routing or prompts with
   `ta` and `ta-en` text, not only English.

## Workflow for a prompt, context or agent change

1. **Reproduce** with a concrete transcript. Save the exact input and the bad
   output (`grandpa oops` records context).
2. **Find the stage** that went wrong: phrase handler, brain, model choice,
   tool selection, tool result, or cleanup. Fix it at that stage, not by
   adding prompt text downstream.
3. **Prefer code over prompt.** If a deterministic rule can decide it (a
   phrase, a parser, a validator), do that. Prompts are the last resort.
4. **Measure before and after** on a fixed set of phrases (3+ runs per phrase,
   include Tamil/Tanglish). Use `grandpa models eval` (see
   `grandpa-local-models`) and keep the numbers in the PR.
5. **Test deterministically.** Unit tests use a fake engine that returns
   scripted tool calls (`tests/action_layer/`, `tests/agents/`,
   `tests/test_core_ai_brain.py`, `tests/test_response_cleanup.py`). No test
   may need a live model unless it is marked `live`.
6. **Check token cost.** Report the prompt size change; the target machine
   evaluates roughly 50–230 tokens/s warm.

## Common failure patterns

| Symptom | Usual cause | Look at |
|---|---|---|
| Answers a follow-up as a new topic | history not passed, or window too small | `_recent_exchanges` in `cli/chat_cmd.py`, `CONVERSATION_WINDOW_MESSAGES` |
| "I can't do that" for a catalogued action | domain not loaded; model didn't call `load_tools` | `action_layer/loop.py`, catalogue `CORE_DOMAINS` |
| Claims success without acting | prompt drift or a model without tool support | loop system prompt; model capability in `grandpa-local-models` |
| Repeats the same tool call | degenerate loop | `agents/loop_guard.py`, step limit |
| Says it is Qwen/Llama | identity prompt missing on that path | `prompt/identity.py`, `runtime/ollama_adapter.py` |
| Emoji or "Thinking:" text in the reply | cleanup skipped on that surface | `response_cleanup.py` |
