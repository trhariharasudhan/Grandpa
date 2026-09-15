"""What to tell a user when the inference engine will not cooperate.

These sentences lived as private helpers inside ``cli/chat_cmd.py``, and three
other modules imported them from there -- ``voice/assistant.py`` and
``voice/cli_session.py`` both reached into chat's internals for the wording of
an engine error. That is backwards: an engine error is not a chat concept, and
voice should not depend on the chat REPL to describe one.

Moved verbatim, so every message a user sees is unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
)
from grandpa.response_cleanup import clean_error_message

__all__ = [
    "engine_unavailable_message",
    "log_generation_exception",
    "model_load_failure_message",
    "model_not_found_message",
    "model_pull_guidance",
]

logger = logging.getLogger(__name__)


def engine_unavailable_message(engine_name: str, exc: EngineConnectionError) -> str:
    text = str(exc)
    if engine_name == "ollama" or "ollama" in text.lower():
        return (
            "Ollama is not available.\n"
            "Start it with: ollama serve\n"
            "Verify it with: ollama list\n"
            "Then retry the command."
        )
    return f"Inference engine '{engine_name}' is not available. {text}"


def model_not_found_message(engine_name: str, exc: EngineModelNotFoundError) -> str:
    model = exc.model
    if engine_name == "ollama":
        return f'Ollama is running, but model "{model}" is not installed.'
    return f'Inference engine "{engine_name}" does not have model "{model}" installed.'


def model_pull_guidance(model: str) -> str:
    return (
        f"Install it with: ollama pull {model}\n"
        "Verify it with: ollama list\n"
        "Then retry the command."
    )


def model_load_failure_message(exc: EngineModelLoadError) -> str:
    if exc.low_memory:
        return str(exc)
    return clean_error_message(
        exc,
        fallback=f"Ollama could not load {exc.model}. Check `ollama serve` and try again.",
    )


def _generation_log_path() -> Path:
    return Path.home() / ".grandpa" / "server.log"


def log_generation_exception(exc: BaseException) -> None:
    """Write one generation failure to the server log, and never raise."""
    log_path = _generation_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.ERROR)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        diagnostic_logger = logging.getLogger(f"{__name__}.generation")
        diagnostic_logger.propagate = False
        diagnostic_logger.addHandler(handler)
        try:
            diagnostic_logger.error(
                "Chat generation failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        finally:
            diagnostic_logger.removeHandler(handler)
            handler.close()
    except Exception:
        logger.debug("Failed to write chat generation diagnostics", exc_info=True)
