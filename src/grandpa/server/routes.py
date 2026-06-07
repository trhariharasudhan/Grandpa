"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse

from grandpa.core.types import Message, Role
from grandpa.response_cleanup import (
    GENERATION_ERROR_MESSAGE,
    clean_assistant_response,
)
from grandpa.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


def _last_user_text(request_body: ChatCompletionRequest) -> str:
    for message in reversed(request_body.messages):
        if message.role == "user" and message.content:
            return message.content
    return ""


def _local_action_response(
    model: str,
    action_result,
    complexity_info=None,
) -> ChatCompletionResponse:
    choice_msg = ChoiceMessage(role="assistant", content=action_result.message)
    try:
        from grandpa.memory_context import remember_conversation

        remember_conversation("assistant", action_result.message)
    except Exception:
        logging.getLogger("grandpa.server").debug(
            "Assistant memory logging failed",
            exc_info=True,
        )
    return ChatCompletionResponse(
        model=model,
        choices=[Choice(message=choice_msg, finish_reason="stop")],
        usage=UsageInfo(),
        complexity=complexity_info,
        local_action={
            "status": action_result.status,
            "kind": action_result.kind,
            "target": action_result.target,
            "tts_text": action_result.tts_text,
            "permission": getattr(action_result, "permission", None),
            "pending_action": getattr(action_result, "pending_action", None),
        },
    )


def _record_brain_result(brain_analysis, action_result) -> None:
    if brain_analysis is None:
        return
    try:
        from grandpa.core_ai_brain import record_assistant_outcome

        record_assistant_outcome(
            brain_analysis,
            assistant_text=action_result.message,
            kind=getattr(action_result, "kind", None),
            target=getattr(action_result, "target", None),
            status=getattr(action_result, "status", None),
        )
    except Exception:
        logging.getLogger("grandpa.server").debug(
            "Brain outcome logging failed",
            exc_info=True,
        )


def _available_engine_models(engine) -> list[str]:
    try:
        return list(engine.list_models())
    except Exception:
        return []


def _apply_ai_routing(engine, request_body: ChatCompletionRequest, user_text: str) -> dict[str, Any] | None:
    if not user_text:
        return None
    try:
        from grandpa.advanced_ai import build_plan

        models = _available_engine_models(engine)
        cloud_allowed = any(
            model.startswith(("gpt-", "o1-", "o3-", "o4-", "claude-", "gemini-", "openrouter/"))
            for model in models
        )
        plan = build_plan(
            user_text,
            requested_model=request_body.model,
            available_models=models,
            cloud_allowed=cloud_allowed,
        )
        selected = plan.routing.selected_model
        if selected and selected != request_body.model:
            request_body.model = selected
        return plan.to_dict()
    except Exception:
        logging.getLogger("grandpa.server").debug(
            "Advanced AI routing failed",
            exc_info=True,
        )
        return None


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    original_user_text = _last_user_text(request_body)
    brain_analysis = None
    effective_user_text = original_user_text
    if original_user_text:
        try:
            from grandpa.core_ai_brain import process_user_message
            from grandpa.memory_context import remember_conversation

            remember_conversation("user", original_user_text)
            brain_analysis = process_user_message(original_user_text)
            effective_user_text = brain_analysis.effective_text
            if effective_user_text != original_user_text:
                for message in reversed(request_body.messages):
                    if message.role == "user" and message.content:
                        message.content = effective_user_text
                        break
        except Exception:
            logging.getLogger("grandpa.server").debug(
                "Conversation brain/memory logging failed",
                exc_info=True,
            )

    _apply_ai_routing(engine, request_body, effective_user_text)
    model = request_body.model

    # Inject memory context into messages before dispatching
    config = getattr(request.app.state, "config", None)
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        config is not None
        and memory_backend is not None
        and config.agent.context_from_memory
        and request_body.messages
    ):
        try:
            from grandpa.tools.storage.context import ContextConfig, inject_context

            # Extract query from the last user message
            query_text = ""
            for m in reversed(request_body.messages):
                if m.role == "user" and m.content:
                    query_text = m.content
                    break

            if query_text:
                messages = _to_messages(request_body.messages)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                enriched = inject_context(
                    query_text,
                    messages,
                    memory_backend,
                    config=ctx_cfg,
                )
                # Rebuild request messages from enriched Message objects
                if len(enriched) > len(messages):
                    from grandpa.server.models import ChatMessage

                    new_msgs = []
                    for msg in enriched:
                        new_msgs.append(
                            ChatMessage(
                                role=msg.role.value,
                                content=msg.content,
                                name=msg.name,
                                tool_call_id=getattr(msg, "tool_call_id", None),
                            )
                        )
                    request_body.messages = new_msgs
        except Exception:
            logging.getLogger("grandpa.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    # Run complexity analysis on the last user message
    complexity_info = None
    query_text_for_complexity = effective_user_text
    if query_text_for_complexity:
        try:
            from grandpa.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text_for_complexity)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("grandpa.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    if original_user_text:
        try:
            from grandpa.core_ai_brain import build_brain_context

            if brain_analysis is not None:
                request_body.messages.insert(
                    0,
                    ChatMessage(
                        role="system",
                        content=build_brain_context(brain_analysis),
                    ),
                )
        except Exception:
            logging.getLogger("grandpa.server").debug(
                "Brain context injection failed",
                exc_info=True,
            )

        from grandpa.file_assistant import handle_file_command
        from grandpa.local_actions import handle_local_action
        from grandpa.memory_context import handle_memory_command
        from grandpa.task_scheduler import handle_scheduler_command

        memory_result = handle_memory_command(effective_user_text)
        if not memory_result.should_fallback:
            _record_brain_result(brain_analysis, memory_result)
            if request_body.stream:
                return await _handle_local_action_stream(
                    model,
                    memory_result,
                    complexity_info,
                )
            return _local_action_response(model, memory_result, complexity_info)

        action_result = handle_local_action(effective_user_text)
        if not action_result.should_fallback:
            _record_brain_result(brain_analysis, action_result)
            if request_body.stream:
                return await _handle_local_action_stream(
                    model,
                    action_result,
                    complexity_info,
                )
            return _local_action_response(model, action_result, complexity_info)

        file_result = handle_file_command(effective_user_text)
        if not file_result.should_fallback:
            _record_brain_result(brain_analysis, file_result)
            if request_body.stream:
                return await _handle_local_action_stream(
                    model,
                    file_result,
                    complexity_info,
                )
            return _local_action_response(model, file_result, complexity_info)

        scheduler_result = handle_scheduler_command(effective_user_text)
        if not scheduler_result.should_fallback:
            _record_brain_result(brain_analysis, scheduler_result)
            if request_body.stream:
                return await _handle_local_action_stream(
                    model,
                    scheduler_result,
                    complexity_info,
                )
            return _local_action_response(model, scheduler_result, complexity_info)

    if request_body.stream:
        bus = getattr(request.app.state, "bus", None)
        # Use the agent stream bridge only when tools are present (the
        # bridge runs agent.run() synchronously and word-splits the result,
        # so it can't stream tokens in real-time).  For plain chat, stream
        # directly from the engine for true token-by-token output.
        if agent is not None and bus is not None and request_body.tools:
            return await _handle_agent_stream(agent, bus, model, request_body)
        return await _handle_stream(engine, model, request_body, complexity_info)

    # Non-streaming: use agent if available, otherwise direct engine call
    if agent is not None:
        return _handle_agent(agent, model, request_body, complexity_info)

    bus = getattr(request.app.state, "bus", None)
    return _handle_direct(
        engine,
        model,
        request_body,
        bus=bus,
        complexity_info=complexity_info,
    )


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if bus:
        from grandpa.telemetry.wrapper import instrumented_generate

        result = instrumented_generate(
            engine,
            messages,
            model=model,
            bus=bus,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = clean_assistant_response(result.get("content", ""))
    result["content"] = content
    try:
        from grandpa.memory_context import remember_conversation

        remember_conversation("assistant", content)
    except Exception:
        logging.getLogger("grandpa.server").debug(
            "Assistant memory logging failed",
            exc_info=True,
        )
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Run through agent."""
    from grandpa.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one
    original_model = agent._model
    if model:
        agent._model = model
    try:
        result = agent.run(input_text, context=ctx)
    finally:
        agent._model = original_model

    content = clean_assistant_response(result.content)
    try:
        from grandpa.memory_context import remember_conversation

        remember_conversation("assistant", content)
    except Exception:
        logging.getLogger("grandpa.server").debug(
            "Assistant memory logging failed",
            exc_info=True,
        )

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from grandpa.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_agent_stream(agent, bus, model, req):
    """Stream agent response with EventBus events via SSE."""
    from grandpa.server.stream_bridge import create_agent_stream

    return await create_agent_stream(agent, bus, model, req)


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
):
    """Stream response using SSE format."""
    from grandpa.server.cloud_router import (
        is_cloud_model,
        stream_cloud,
        stream_local,
    )

    messages = _to_messages(req.messages)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = is_cloud_model(model)

    async def generate():
        full_content = ""
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from grandpa.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                else:
                    token_iter = engine.stream(
                        messages,
                        model=model,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                    )
            async for token in token_iter:
                full_content += token
                chunk = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=token),
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("grandpa.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\n{GENERATION_ERROR_MESSAGE}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        if full_content:
            try:
                from grandpa.memory_context import remember_conversation

                remember_conversation(
                    "assistant",
                    clean_assistant_response(full_content),
                )
            except Exception:
                logging.getLogger("grandpa.server").debug(
                    "Assistant memory logging failed",
                    exc_info=True,
                )

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the correct engine label.
        # We use the routing decision (use_cloud) directly rather than
        # unwrapping the engine chain, which can be in a broken state.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _handle_local_action_stream(model: str, action_result, complexity_info=None):
    """Stream a local-action confirmation in OpenAI-compatible SSE shape."""
    import json as _json

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def generate():
        role_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
        yield f"data: {role_chunk.model_dump_json()}\n\n"

        if action_result.message:
            content_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(delta=DeltaMessage(content=action_result.message))
                ],
            )
            yield f"data: {content_chunk.model_dump_json()}\n\n"
            try:
                from grandpa.memory_context import remember_conversation

                remember_conversation("assistant", action_result.message)
            except Exception:
                logging.getLogger("grandpa.server").debug(
                    "Assistant memory logging failed",
                    exc_info=True,
                )

        finish_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
        )
        finish_dict = _json.loads(finish_chunk.model_dump_json())
        finish_dict["local_action"] = {
            "status": action_result.status,
            "kind": action_result.kind,
            "target": action_result.target,
            "tts_text": action_result.tts_text,
            "permission": getattr(action_result, "permission", None),
            "pending_action": getattr(action_result, "pending_action", None),
        }
        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()
        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List locally installed models (Ollama).

    Cloud models are not included here — they live in the Cloud Models tab
    of the UI and are selected there, not from this endpoint.
    """
    from grandpa.server.cloud_router import is_cloud_model, list_local_models

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out any cloud model IDs that may appear via MultiEngine.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = engine.list_models()
    model_ids = [m for m in all_ids if not is_cloud_model(m)]
    if not model_ids:
        model_ids = await list_local_models()

    return ModelListResponse(
        data=[ModelObject(id=mid) for mid in model_ids],
    )


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=600.0)
    try:
        resp = client.post(
            "/api/pull",
            json={"name": model_name, "stream": False},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=30.0)
    try:
        resp = client.request(
            "DELETE",
            "/api/delete",
            json={"name": model_name},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "deleted", "model": model_name}


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os
    from pathlib import Path

    # Re-read ~/.grandpa/cloud-keys.env and update the running process env.
    keys_path = Path.home() / ".grandpa" / "cloud-keys.env"
    if keys_path.exists():
        for raw_line in keys_path.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    # Try to build a fresh CloudEngine.
    try:
        from grandpa.engine.cloud import CloudEngine
        from grandpa.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from grandpa.core.config import DEFAULT_CONFIG_DIR
    from grandpa.server.savings import compute_savings, savings_to_dict
    from grandpa.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        summary = agg.summary(since=session_start)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from grandpa.core.config import DEFAULT_CONFIG_DIR
    from grandpa.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    agent = getattr(request.app.state, "agent", None)
    agent_id = getattr(agent, "agent_id", None) if agent else None
    # Fall back to configured agent name if agent didn't instantiate
    if agent_id is None:
        agent_id = getattr(request.app.state, "agent_name", None)
    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
    }


@router.get("/v1/ai/diagnostics")
async def ai_diagnostics(request: Request, query: str = ""):
    """Return local-first AI orchestration diagnostics."""
    from grandpa.advanced_ai import ai_diagnostics as build_diagnostics

    engine = getattr(request.app.state, "engine", None)
    model = getattr(request.app.state, "model", "")
    return build_diagnostics(engine=engine, model=model, query=query)


@router.post("/v1/ai/plan")
async def ai_plan(request: Request):
    """Build a read-only plan for a user request without executing it."""
    from grandpa.advanced_ai import build_plan

    body = await request.json()
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="'query' field is required")
    requested_model = str(body.get("model") or getattr(request.app.state, "model", "")).strip()
    engine = getattr(request.app.state, "engine", None)
    models = _available_engine_models(engine) if engine is not None else []
    cloud_allowed = bool(body.get("cloud_allowed", False)) or any(
        model.startswith(("gpt-", "o1-", "o3-", "o4-", "claude-", "gemini-", "openrouter/"))
        for model in models
    )
    return build_plan(
        query,
        requested_model=requested_model,
        available_models=models,
        cloud_allowed=cloud_allowed,
    ).to_dict()


@router.get("/v1/personal-memory")
async def personal_memory():
    """Return local personal memory and recent activity."""
    from grandpa.memory_context import memory_summary

    return memory_summary()


@router.get("/v1/browser/context")
async def browser_context():
    """Return safe visible-browser context for the HUD."""
    from grandpa.browser_control import (
        BrowserContextStore,
        get_visible_browser_context,
        latest_browser_snapshot,
    )

    context = get_visible_browser_context()
    latest = latest_browser_snapshot()
    return {
        "context": context.to_dict(),
        "recent_activity": BrowserContextStore().recent(limit=8),
        "extension": {
            "connected": bool(latest.get("connected")),
            "snapshot_age_seconds": (
                latest.get("snapshot", {}).get("age_seconds")
                if latest.get("snapshot")
                else None
            ),
        },
    }


@router.post("/v1/browser/snapshot")
async def browser_snapshot_ingest(request: Request):
    """Ingest a safe visible-page snapshot from the local browser extension."""
    from grandpa.browser_control import store_browser_snapshot

    body = await request.json()
    return {"status": "ok", "snapshot": store_browser_snapshot(body)}


@router.get("/v1/browser/snapshot/latest")
async def browser_snapshot_latest():
    """Return the latest safe browser extension snapshot."""
    from grandpa.browser_control import latest_browser_snapshot

    return latest_browser_snapshot()


@router.get("/v1/browser/diagnostics")
async def browser_diagnostics():
    """Return local-only browser adapter diagnostics."""
    from grandpa.browser_control import execute_browser_action

    result = execute_browser_action("diagnostics", "browser")
    return {
        "status": result.status,
        "message": result.message,
        "risk_level": result.risk_level,
        "details": json.loads(result.target) if result.target.startswith("{") else {},
        "context": result.context.to_dict() if result.context else {},
    }


@router.delete("/v1/browser/snapshot")
async def browser_snapshot_clear():
    """Clear stored browser extension snapshots."""
    from grandpa.browser_control import clear_browser_snapshot

    return clear_browser_snapshot()


@router.get("/v1/browser/command/next")
async def browser_command_next(url: str = ""):
    """Return the next localhost-only browser command for the visible page adapter."""
    from grandpa.browser_control import next_browser_command

    return next_browser_command(url)


@router.post("/v1/browser/command/{command_id}/complete")
async def browser_command_complete(command_id: int, request: Request):
    """Mark a browser extension command as completed or failed."""
    from grandpa.browser_control import complete_browser_command

    body = await request.json()
    return complete_browser_command(command_id, body)


@router.get("/v1/screen/diagnostics")
async def screen_awareness_diagnostics():
    """Return local-only screen-awareness diagnostics for the HUD."""
    from grandpa.screen_awareness import screen_diagnostics

    return screen_diagnostics()


@router.get("/v1/screen/context")
async def screen_awareness_context():
    """Return structured screen context without exposing it outside localhost."""
    from grandpa.screen_awareness import describe_screen

    context = describe_screen(include_ocr=True)
    return context.to_dict()


@router.post("/v1/personal-memory/search")
async def personal_memory_search(request: Request):
    """Search local personal memory with semantic recall metadata."""
    from grandpa.memory_context import search_personal_memory

    body = await request.json()
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="'query' field is required")
    category = body.get("category")
    if category is not None:
        category = str(category).strip() or None
    limit = int(body.get("limit", 8))
    return search_personal_memory(query, category=category, limit=max(1, min(limit, 25)))


@router.get("/v1/file-assistant")
async def file_assistant():
    """Return local file assistant history and notes."""
    from grandpa.file_assistant import file_assistant_summary

    return file_assistant_summary()


@router.get("/v1/file-intelligence/diagnostics")
async def file_intelligence_diagnostics():
    from grandpa.document_intelligence import diagnostics

    return diagnostics()


@router.post("/v1/file-intelligence/search")
async def file_intelligence_search(request: Request):
    from grandpa.document_intelligence import search_documents

    body = await request.json()
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="'query' field is required")
    result = search_documents(query)
    return {"status": result.status, "message": result.message, **result.data}


@router.post("/v1/file-intelligence/organize-plan")
async def file_intelligence_organize_plan(request: Request):
    from grandpa.document_intelligence import organization_plan

    body = await request.json()
    result = organization_plan(str(body.get("query", "")).strip(), dry_run=bool(body.get("dry_run", True)))
    return {"status": result.status, "message": result.message, **result.data}


@router.post("/v1/file-assistant/search")
async def file_assistant_search(request: Request):
    """Search safe local document folders."""
    from grandpa.file_assistant import search_files

    body = await request.json()
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="'query' field is required")
    return search_files(query)


@router.get("/v1/office/diagnostics")
async def office_diagnostics():
    from grandpa.office_productivity import diagnostics

    return diagnostics()


@router.post("/v1/office/report")
async def office_report(request: Request):
    from grandpa.office_productivity import generate_report

    body = await request.json()
    result = generate_report(str(body.get("title", "Report")), str(body.get("source_text", "")))
    return {"status": result.status, "message": result.message, **result.data}


@router.post("/v1/office/presentation-outline")
async def office_presentation_outline(request: Request):
    from grandpa.office_productivity import create_presentation_outline

    body = await request.json()
    result = create_presentation_outline(str(body.get("topic", "Grandpa Assistant")), slides=int(body.get("slides", 6)))
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/automation/diagnostics")
async def smart_automation_diagnostics():
    from grandpa.smart_automation import diagnostics

    return diagnostics()


@router.post("/v1/automation/workflows")
async def smart_automation_create_workflow(request: Request):
    from grandpa.smart_automation import create_workflow_from_text

    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="'text' field is required")
    result = create_workflow_from_text(text)
    return {"status": result.status, "message": result.message, **result.data}


@router.post("/v1/automation/workflows/{name}/simulate")
async def smart_automation_simulate(name: str):
    from grandpa.smart_automation import simulate_workflow

    result = simulate_workflow(name)
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/developer/diagnostics")
async def developer_diagnostics():
    from grandpa.developer_assistant import diagnostics

    return diagnostics()


@router.post("/v1/developer/terminal-plan")
async def developer_terminal_plan(request: Request):
    from grandpa.developer_assistant import terminal_plan

    body = await request.json()
    command = str(body.get("command", "")).strip()
    if not command:
        raise HTTPException(status_code=400, detail="'command' field is required")
    result = terminal_plan(command, dry_run=bool(body.get("dry_run", True)))
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/security/diagnostics")
async def security_diagnostics():
    from grandpa.security_safety import diagnostics

    return diagnostics()


@router.post("/v1/security/suspicious-action")
async def security_suspicious_action(request: Request):
    from grandpa.security_safety import suspicious_action_score

    body = await request.json()
    return suspicious_action_score(str(body.get("text", "")))


@router.get("/v1/mobile/diagnostics")
async def mobile_diagnostics():
    from grandpa.mobile_integration import diagnostics

    return diagnostics()


@router.post("/v1/mobile/pairing")
async def mobile_pairing(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore

    body = await request.json()
    result = MobileBridgeStore().create_pairing(str(body.get("name", "Android device")))
    host = str(body.get("host", "")).strip()
    if host:
        result["qr_payload"]["host"] = host
    return result


@router.get("/v1/mobile/pairing/{device_id}/qr")
async def mobile_pairing_qr(device_id: str, code: str = Query(default="")):
    from grandpa.mobile_integration import pairing_qr_payload

    if not code:
        raise HTTPException(status_code=400, detail="'code' query parameter is required")
    return pairing_qr_payload(device_id, code)


@router.post("/v1/mobile/pairing/confirm")
async def mobile_pairing_confirm(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore

    body = await request.json()
    result = MobileBridgeStore().confirm_pairing(
        str(body.get("device_id", "")),
        str(body.get("pairing_code", "")),
        status=body.get("status") if isinstance(body.get("status"), dict) else None,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "Pairing failed"))
    return result


@router.get("/v1/mobile/devices")
async def mobile_devices():
    from grandpa.mobile_integration import MobileBridgeStore

    store = MobileBridgeStore()
    return {"devices": store.devices(), "events": store.events(limit=20)}


@router.post("/v1/mobile/heartbeat")
async def mobile_heartbeat(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore

    body = await request.json()
    store = MobileBridgeStore()
    device_id = str(body.get("device_id", ""))
    token = str(body.get("trusted_token", body.get("token", "")))
    if not store.authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Mobile device is not paired or token is invalid")
    status = body.get("status") if isinstance(body.get("status"), dict) else {}
    return store.update_status(device_id, status)


@router.post("/v1/mobile/notifications")
async def mobile_notification_sync(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore

    body = await request.json()
    store = MobileBridgeStore()
    device_id = str(body.get("device_id", ""))
    token = str(body.get("trusted_token", body.get("token", "")))
    if not store.authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Mobile device is not paired or token is invalid")
    return store.record_notification(
        device_id,
        str(body.get("kind", "app")),
        str(body.get("app", "Android")),
        str(body.get("title", "")),
        str(body.get("summary", "")),
    )


@router.post("/v1/mobile/remote-command")
async def mobile_remote_command(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore, plan_remote_command

    body = await request.json()
    store = MobileBridgeStore()
    device_id = str(body.get("device_id", ""))
    token = str(body.get("trusted_token", body.get("token", "")))
    if token and not store.authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Mobile device is not paired or token is invalid")
    result = plan_remote_command(str(body.get("command", "")), device_id=device_id)
    return store.record_remote_command(device_id, str(body.get("command", "")), result)


@router.post("/v1/mobile/voice-relay")
async def mobile_voice_relay(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore, voice_relay_plan

    body = await request.json()
    store = MobileBridgeStore()
    device_id = str(body.get("device_id", ""))
    token = str(body.get("trusted_token", body.get("token", "")))
    if not store.authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Mobile device is not paired or token is invalid")
    result = voice_relay_plan(str(body.get("transcript", "")), device_id=device_id)
    return store.record_remote_command(device_id, str(body.get("transcript", "")), result)


@router.post("/v1/mobile/clipboard-sync-plan")
async def mobile_clipboard_sync_plan(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore, clipboard_sync_plan

    body = await request.json()
    store = MobileBridgeStore()
    device_id = str(body.get("device_id", ""))
    token = str(body.get("trusted_token", body.get("token", "")))
    if not store.authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Mobile device is not paired or token is invalid")
    result = clipboard_sync_plan(device_id, str(body.get("direction", "phone_to_desktop")))
    return store.record_remote_command(device_id, "clipboard sync", result)


@router.post("/v1/mobile/push")
async def mobile_push_notification(request: Request):
    from grandpa.mobile_integration import MobileBridgeStore

    body = await request.json()
    store = MobileBridgeStore()
    device_id = str(body.get("device_id", ""))
    return store.queue_push_notification(
        device_id,
        str(body.get("title", "Grandpa")),
        str(body.get("body", "")),
    )


@router.get("/v1/mobile/outbox/{device_id}")
async def mobile_outbox(device_id: str):
    from grandpa.mobile_integration import MobileBridgeStore

    store = MobileBridgeStore()
    return {"items": store.pending_outbox(device_id)}


@router.websocket("/v1/mobile/ws")
async def mobile_companion_websocket(websocket: WebSocket):
    """Local LAN WebSocket for the Android companion app."""
    from grandpa.mobile_integration import (
        MobileBridgeStore,
        plan_remote_command,
        voice_relay_plan,
    )

    await websocket.accept()
    store = MobileBridgeStore()
    device_id = ""
    authenticated = False
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "message": "Grandpa mobile companion bridge ready.",
                "local_only": True,
            }
        )
        while True:
            message = await websocket.receive_json()
            event_type = str(message.get("type", ""))
            if event_type == "pair_request":
                pairing = store.create_pairing(str(message.get("device_name", "Android device")))
                device_id = pairing["device_id"]
                await websocket.send_json({"type": "pairing_code", **pairing})
                continue

            if event_type == "pair_confirm":
                result = store.confirm_pairing(
                    str(message.get("device_id", "")),
                    str(message.get("pairing_code", "")),
                    status=message.get("status") if isinstance(message.get("status"), dict) else None,
                )
                authenticated = bool(result.get("ok"))
                device_id = str(result.get("device_id", message.get("device_id", "")))
                await websocket.send_json({"type": "paired" if authenticated else "error", **result})
                continue

            if event_type == "authenticate":
                device_id = str(message.get("device_id", ""))
                token = str(message.get("trusted_token", message.get("token", "")))
                authenticated = store.authenticate(device_id, token)
                await websocket.send_json({"type": "authenticated", "ok": authenticated})
                if authenticated:
                    pending = store.pending_outbox(device_id)
                    if pending:
                        await websocket.send_json({"type": "outbox", "items": pending})
                        store.mark_outbox_delivered([int(item["id"]) for item in pending])
                continue

            if not authenticated:
                await websocket.send_json({"type": "error", "message": "Pair or authenticate before sending events."})
                continue

            if event_type == "heartbeat":
                status = message.get("status") if isinstance(message.get("status"), dict) else {}
                await websocket.send_json({"type": "heartbeat_ack", **store.update_status(device_id, status)})
                pending = store.pending_outbox(device_id)
                if pending:
                    await websocket.send_json({"type": "outbox", "items": pending})
                    store.mark_outbox_delivered([int(item["id"]) for item in pending])
            elif event_type == "notification":
                notification = message.get("notification") if isinstance(message.get("notification"), dict) else message
                recorded = store.record_notification(
                    device_id,
                    str(notification.get("kind", "app")),
                    str(notification.get("app", "Android")),
                    str(notification.get("title", "")),
                    str(notification.get("summary", "")),
                )
                await websocket.send_json({"type": "notification_ack", "notification": recorded})
            elif event_type == "remote_command":
                command = str(message.get("command", ""))
                result = plan_remote_command(command, device_id=device_id)
                recorded = store.record_remote_command(device_id, command, result)
                await websocket.send_json({"type": "remote_command_result", **recorded})
            elif event_type == "voice_relay":
                transcript = str(message.get("transcript", ""))
                result = voice_relay_plan(transcript, device_id=device_id)
                recorded = store.record_remote_command(device_id, transcript, result)
                await websocket.send_json({"type": "voice_relay_result", **recorded})
            else:
                await websocket.send_json({"type": "error", "message": f"Unsupported mobile event: {event_type}"})
    except WebSocketDisconnect:
        return


@router.get("/v1/communication/diagnostics")
async def communication_diagnostics():
    from grandpa.communication_integration import diagnostics

    return diagnostics()


@router.post("/v1/communication/reply-plan")
async def communication_reply_plan(request: Request):
    from grandpa.communication_integration import reply_plan

    body = await request.json()
    result = reply_plan(str(body.get("service", "gmail")), str(body.get("recipient", "")), str(body.get("intent", "")))
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/real-world/diagnostics")
async def real_world_diagnostics():
    from grandpa.real_world_tasks import diagnostics

    return diagnostics()


@router.post("/v1/real-world/shopping-plan")
async def real_world_shopping_plan(request: Request):
    from grandpa.real_world_tasks import shopping_plan

    body = await request.json()
    result = shopping_plan(str(body.get("query", "")))
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/iot/diagnostics")
async def iot_diagnostics():
    from grandpa.iot_smart_home import diagnostics

    return diagnostics()


@router.post("/v1/iot/discovery-plan")
async def iot_discovery_plan(request: Request):
    from grandpa.iot_smart_home import discovery_plan

    body = await request.json()
    result = discovery_plan(str(body.get("cidr", "192.168.1.0/24")))
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/future/diagnostics")
async def future_diagnostics():
    from grandpa.future_features import diagnostics

    return diagnostics()


@router.post("/v1/future/overlay-simulation")
async def future_overlay_simulation():
    from grandpa.future_features import overlay_simulation

    result = overlay_simulation()
    return {"status": result.status, "message": result.message, **result.data}


@router.get("/v1/routines")
async def routines(request: Request):
    """Return local routines and reminders."""
    from grandpa.task_scheduler import scheduler_summary

    summary = scheduler_summary()
    daemon = getattr(request.app.state, "routine_scheduler_daemon", None)
    summary["daemon"] = (
        daemon.status()
        if daemon is not None
        else {
            "running": False,
            "poll_interval_seconds": None,
            "started_at": None,
            "last_tick_at": None,
            "last_result": None,
            "last_error": "not configured",
        }
    )
    return summary


@router.post("/v1/routines/tick")
async def tick_routine_scheduler(request: Request):
    """Run one scheduler tick for diagnostics/tests."""
    daemon = getattr(request.app.state, "routine_scheduler_daemon", None)
    if daemon is not None:
        return daemon.tick()
    from grandpa.task_scheduler import execute_due_once

    return execute_due_once()


@router.post("/v1/routines/{routine_name:path}/run")
async def run_routine_endpoint(routine_name: str):
    """Run a stored routine by name."""
    from grandpa.task_scheduler import run_routine

    return run_routine(routine_name)


@router.post("/v1/routines/{routine_name:path}/enable")
async def enable_routine_endpoint(routine_name: str):
    """Enable a stored routine."""
    from grandpa.task_scheduler import set_routine_enabled

    return set_routine_enabled(routine_name, True)


@router.post("/v1/routines/{routine_name:path}/disable")
async def disable_routine_endpoint(routine_name: str):
    """Disable a stored routine."""
    from grandpa.task_scheduler import set_routine_enabled

    return set_routine_enabled(routine_name, False)


@router.delete("/v1/personal-memory")
async def clear_personal_memory():
    """Clear local personal memory and recent activity."""
    from grandpa.memory_context import clear_memory

    return clear_memory()


@router.post("/api/local-action")
async def run_structured_local_action(payload: dict[str, Any]):
    """Run or stage a structured local PC action."""
    from grandpa.pc_control import run_local_action

    return run_local_action(payload).to_dict()


@router.get("/api/local-action/pending")
async def pending_structured_local_actions():
    """List structured PC actions awaiting user confirmation."""
    from grandpa.pc_control import list_pending_actions

    return {"actions": list_pending_actions()}


@router.get("/api/local-action/approvals")
async def structured_local_action_approvals(limit: int = Query(default=100, ge=1, le=500)):
    """List structured PC approval records across lifecycle states."""
    from grandpa.pc_control import get_pc_control_runtime_health, list_approval_records

    health = get_pc_control_runtime_health()
    return {
        "actions": list_approval_records(limit=limit),
        "storage": health["storage"],
        "retention": health["retention"],
        "maintenance": health["maintenance"],
        "counts": health["counts"],
    }


@router.get("/api/local-action/health")
async def structured_local_action_health():
    """Return safe storage, retention, and cleanup health for PC actions."""
    from grandpa.pc_control import get_pc_control_runtime_health

    return get_pc_control_runtime_health()


@router.get("/v1/desktop/diagnostics")
async def desktop_control_diagnostics():
    """Return read-only desktop control domain diagnostics."""
    from grandpa.desktop.control import desktop_control_diagnostics

    return desktop_control_diagnostics()


@router.get("/v1/desktop/services")
async def desktop_control_services():
    """Return registered desktop control services and readiness metadata."""
    from grandpa.desktop.control import list_desktop_services

    return {"services": list_desktop_services(), "local_only": True}


@router.get("/v1/desktop/kernel")
async def desktop_control_kernel():
    """Return PC-control kernel diagnostics."""
    from grandpa.desktop.kernel import diagnostics

    return diagnostics()


@router.get("/api/local-action/audit")
async def recent_structured_local_action_audit(limit: int = Query(default=100, ge=1, le=500)):
    """Read recent redacted structured PC action audit entries."""
    from grandpa.pc_control import read_recent_audit_entries

    return {"entries": read_recent_audit_entries(limit)}


@router.post("/api/local-action/emergency-stop")
async def emergency_stop_local_actions():
    """Cancel pending structured PC actions and pause risky queued actions."""
    from grandpa.pc_control import emergency_stop

    return emergency_stop().to_dict()


@router.post("/api/local-action/{action_id}/approve")
async def approve_structured_local_action(action_id: str):
    """Approve a pending structured PC action."""
    from grandpa.pc_control import approve_local_action

    return approve_local_action(action_id).to_dict()


@router.post("/api/local-action/{action_id}/reject")
async def reject_structured_local_action(action_id: str):
    """Reject a pending structured PC action."""
    from grandpa.pc_control import reject_local_action

    return reject_local_action(action_id).to_dict()


@router.get("/v1/local-actions/pending")
async def pending_local_actions():
    """List pending local actions awaiting user confirmation."""
    from grandpa.local_action_approvals import LocalActionApprovalStore

    return {"actions": LocalActionApprovalStore().list_pending()}


@router.post("/v1/local-actions/{action_id}/approve")
async def approve_local_action(action_id: str):
    """Approve and run a pending local action."""
    from grandpa.local_actions import approve_pending_action

    result = approve_pending_action(action_id)
    return {
        "message": result.message,
        "local_action": {
            "status": result.status,
            "kind": result.kind,
            "target": result.target,
            "tts_text": result.tts_text,
            "permission": result.permission,
            "pending_action": result.pending_action,
        },
    }


@router.post("/v1/local-actions/{action_id}/deny")
async def deny_local_action(action_id: str):
    """Deny a pending local action."""
    from grandpa.local_actions import deny_pending_action

    result = deny_pending_action(action_id)
    return {
        "message": result.message,
        "local_action": {
            "status": result.status,
            "kind": result.kind,
            "target": result.target,
            "tts_text": result.tts_text,
            "permission": result.permission,
            "pending_action": result.pending_action,
        },
    }


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from grandpa.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = scanner.run_all()
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


__all__ = ["router"]
