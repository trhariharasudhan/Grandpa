"""Shared text-command processor used by the voice assistant CLI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from grandpa.cli.chat_cmd import (
    _create_one_shot_reminder,
    _engine_unavailable_message,
    _handle_natural_assistant_intent,
    _log_generation_exception,
    _model_load_failure_message,
    _model_not_found_message,
)
from grandpa.core.config import GrandpaConfig, load_config
from grandpa.core.types import Message, Role
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
)
from grandpa.response_cleanup import (
    GENERATION_ERROR_MESSAGE,
    clean_assistant_response,
    clean_error_message,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceAssistantResponse:
    """Structured result returned by the voice command processor."""

    text: str
    status: str = "handled"
    kind: str = "assistant"


@dataclass
class VoiceCommandProcessor:
    """Route recognized speech through Grandpa's existing safe text pipeline."""

    config: GrandpaConfig | None = None
    engine_key: str | None = None
    model_name: str | None = None
    history: list[Message] = field(default_factory=list)
    _engine_name: str = field(default="", init=False)
    _engine: object | None = field(default=None, init=False)
    _model: str = field(default="", init=False)

    def handle_user_input(self, text: str) -> VoiceAssistantResponse:
        """Process recognized text and return a user-facing response string."""

        user_input = text.strip()
        if not user_input:
            return VoiceAssistantResponse(
                "I did not catch a command.", status="empty", kind="voice"
            )

        try:
            from grandpa.core_ai_brain import (
                build_brain_context,
                process_user_message,
                record_assistant_outcome,
            )
            from grandpa.memory_context import (
                handle_memory_command,
                remember_conversation,
            )

            remember_conversation("user", user_input)
            brain_analysis = process_user_message(user_input)
            effective_text = brain_analysis.effective_text

            local_response = self._handle_local_pipeline(effective_text)
            if local_response is not None:
                remember_conversation("assistant", local_response.text)
                record_assistant_outcome(
                    brain_analysis,
                    assistant_text=local_response.text,
                    kind=local_response.kind,
                    target=None,
                    status=local_response.status,
                )
                self._append_turn(user_input, local_response.text)
                return local_response

            memory_result = handle_memory_command(effective_text)
            if not memory_result.should_fallback:
                response = VoiceAssistantResponse(
                    memory_result.message,
                    status=memory_result.status,
                    kind=memory_result.kind,
                )
                remember_conversation("assistant", response.text)
                record_assistant_outcome(
                    brain_analysis,
                    assistant_text=response.text,
                    kind=memory_result.kind,
                    target=memory_result.target,
                    status=memory_result.status,
                )
                self._append_turn(user_input, response.text)
                return response

            generated = self._generate_response(
                effective_text,
                system_context=build_brain_context(brain_analysis),
            )
            remember_conversation("assistant", generated.text)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=generated.text,
                kind=generated.kind,
                target=None,
                status=generated.status,
            )
            self._append_turn(effective_text, generated.text)
            return generated
        except (EngineConnectionError, EngineModelLoadError, EngineModelNotFoundError):
            raise
        except Exception as exc:
            _log_generation_exception(exc)
            logger.debug("Voice command processor failed", exc_info=True)
            return VoiceAssistantResponse(
                clean_error_message(exc, fallback=GENERATION_ERROR_MESSAGE),
                status="error",
                kind="error",
            )

    def _handle_local_pipeline(
        self, effective_text: str
    ) -> VoiceAssistantResponse | None:
        natural_intent_message = _handle_natural_assistant_intent(
            effective_text, spoken=True
        )
        if natural_intent_message is not None:
            return VoiceAssistantResponse(natural_intent_message, kind="local")

        reminder_message = _create_one_shot_reminder(effective_text)
        if reminder_message is not None:
            return VoiceAssistantResponse(reminder_message, kind="reminder")

        from grandpa.calendar import handle_calendar_command

        calendar_action = handle_calendar_command(effective_text)
        if not calendar_action.should_fallback:
            return VoiceAssistantResponse(
                calendar_action.message, status=calendar_action.status, kind="calendar"
            )

        from grandpa.gmail import handle_gmail_command

        gmail_action = handle_gmail_command(effective_text)
        if not gmail_action.should_fallback:
            return VoiceAssistantResponse(
                gmail_action.message, status=gmail_action.status, kind="gmail"
            )

        from grandpa.notes import handle_notes_command

        notes_action = handle_notes_command(effective_text)
        if not notes_action.should_fallback:
            return VoiceAssistantResponse(
                notes_action.message, status=notes_action.status, kind="notes"
            )

        from grandpa.downloads import handle_downloads_command

        downloads_action = handle_downloads_command(effective_text)
        if not downloads_action.should_fallback:
            return VoiceAssistantResponse(
                downloads_action.message,
                status=downloads_action.status,
                kind="downloads",
            )

        from grandpa.web_search import handle_web_search_command

        web_search_action = handle_web_search_command(effective_text)
        if not web_search_action.should_fallback:
            return VoiceAssistantResponse(
                web_search_action.message,
                status=web_search_action.status,
                kind="web_search",
            )

        from grandpa.browser_awareness import handle_browser_awareness_command

        browser_awareness = handle_browser_awareness_command(effective_text)
        if not browser_awareness.should_fallback:
            return VoiceAssistantResponse(
                browser_awareness.message,
                status=browser_awareness.status,
                kind="browser_awareness",
            )

        from grandpa.browser import handle_browser_command

        browser_action = handle_browser_command(effective_text)
        if not browser_action.should_fallback:
            return VoiceAssistantResponse(
                browser_action.message, status=browser_action.status, kind="browser"
            )

        from grandpa.desktop.automation import handle_desktop_command

        desktop_action = handle_desktop_command(effective_text)
        if not desktop_action.should_fallback:
            return VoiceAssistantResponse(
                desktop_action.message,
                status=desktop_action.status,
                kind="desktop",
            )

        from grandpa.local_actions import handle_local_action

        local_action = handle_local_action(effective_text)
        if not local_action.should_fallback:
            return VoiceAssistantResponse(
                local_action.message,
                status=local_action.status,
                kind=local_action.kind or "local",
            )

        from grandpa.file_assistant import handle_file_command

        file_action = handle_file_command(effective_text)
        if not file_action.should_fallback:
            return VoiceAssistantResponse(
                file_action.message,
                status=file_action.status,
                kind=getattr(file_action, "kind", "file"),
            )

        from grandpa.task_scheduler import handle_scheduler_command

        scheduler_action = handle_scheduler_command(effective_text)
        if not scheduler_action.should_fallback:
            return VoiceAssistantResponse(
                scheduler_action.message,
                status=scheduler_action.status,
                kind=getattr(scheduler_action, "kind", "routine"),
            )

        return None

    def _generate_response(
        self, effective_text: str, *, system_context: str
    ) -> VoiceAssistantResponse:
        self._ensure_engine()
        try:
            result = self._engine.generate(  # type: ignore[union-attr]
                [
                    Message(role=Role.SYSTEM, content=system_context),
                    *self.history,
                    Message(role=Role.USER, content=effective_text),
                ],
                model=self._model,
            )
        except EngineModelNotFoundError as exc:
            raise EngineModelNotFoundError(
                exc.model, _model_not_found_message(self._engine_name, exc)
            ) from exc
        except EngineConnectionError as exc:
            raise EngineConnectionError(
                _engine_unavailable_message(self._engine_name, exc)
            ) from exc
        except EngineModelLoadError as exc:
            raise EngineModelLoadError(
                exc.model, _model_load_failure_message(exc), low_memory=exc.low_memory
            ) from exc

        content = result.get("content", "") if isinstance(result, dict) else str(result)
        return VoiceAssistantResponse(
            clean_assistant_response(content), kind="assistant"
        )

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        from grandpa.engine import discover_engines, discover_models, get_engine
        from grandpa.intelligence import register_builtin_models

        config = self.config or load_config()
        register_builtin_models()
        resolved = get_engine(config, self.engine_key)
        if resolved is None:
            raise EngineConnectionError("No inference engine available.")
        self._engine_name, self._engine = resolved
        self._model = self.model_name or config.intelligence.default_model
        if not self._model:
            all_models = discover_models(discover_engines(config))
            engine_models = all_models.get(self._engine_name, [])
            if not engine_models:
                raise EngineModelNotFoundError("", "No model available.")
            self._model = engine_models[0]

    def _append_turn(self, user_text: str, assistant_text: str) -> None:
        self.history.append(Message(role=Role.USER, content=user_text))
        self.history.append(Message(role=Role.ASSISTANT, content=assistant_text))


__all__ = ["VoiceAssistantResponse", "VoiceCommandProcessor"]
