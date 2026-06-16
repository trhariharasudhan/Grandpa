"""Voice session orchestration for Grandpa."""

from __future__ import annotations

import base64
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from grandpa.voice.conversation import VoiceConversation
from grandpa.voice.errors import (
    MICROPHONE_UNAVAILABLE_MESSAGE,
    VOICE_DEPENDENCY_MESSAGE,
    VoiceError,
)
from grandpa.voice.speech_input import SpeechInputEngine
from grandpa.voice.speech_output import SpeechOutputEngine
from grandpa.voice.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)

HIGH_RISK_VOICE_PATTERNS = (
    r"\bshutdown\b",
    r"\brestart\b",
    r"\breboot\b",
    r"\bsleep\b",
    r"\block\s+(?:screen|computer|pc)\b",
    r"\bdelete\b",
    r"\bformat\b",
    r"\bwipe\b",
    r"\bpurchase\b",
    r"\bpayment\b",
    r"\bpassword\b",
    r"\bcredential",
    r"\bregistry\b",
    r"\bpowershell\b",
    r"\bcmd\b",
)


@dataclass
class VoiceRuntime:
    """A local-first voice interface over Grandpa's existing brain."""

    wake_detector: WakeWordDetector = field(default_factory=WakeWordDetector)
    speech_input: SpeechInputEngine = field(default_factory=SpeechInputEngine)
    speech_output: SpeechOutputEngine = field(default_factory=SpeechOutputEngine)
    conversation: VoiceConversation = field(default_factory=VoiceConversation)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _last_latency_ms: float = 0.0

    def start(self) -> dict[str, Any]:
        with self._lock:
            self.conversation.start()
        return {"status": "started", "session": self.conversation.to_dict(), "voice": self.status()}

    def stop(self) -> dict[str, Any]:
        self.speech_output.stop()
        with self._lock:
            self.conversation.stop()
        return {"status": "stopped", "session": self.conversation.to_dict()}

    def status(self) -> dict[str, Any]:
        speech_input = self.speech_input.diagnostics()
        speech_output = self.speech_output.diagnostics()
        stt_available = bool(speech_input.get("browser_transcript_supported") or speech_input.get("local_whisper_available"))
        tts_available = speech_output.get("status") == "ready"
        mode = "browser_transcript" if speech_input.get("browser_transcript_supported") else "unavailable"
        if speech_input.get("local_whisper_available"):
            mode = "local_audio"
        setup_message = "" if stt_available else VOICE_DEPENDENCY_MESSAGE
        return {
            "available": stt_available,
            "stt_available": stt_available,
            "tts_available": tts_available,
            "microphone_available": "unknown",
            "mode": mode,
            "setup_message": setup_message,
            "message": "Voice push-to-talk is ready." if stt_available else setup_message,
            "status": "active" if self.conversation.active else "idle",
            "session": self.conversation.to_dict(),
            "wake_word": self.wake_detector.diagnostics(),
            "speech_input": speech_input,
            "speech_output": speech_output,
            "latency_ms": self._last_latency_ms,
            "local_first": True,
            "high_risk_voice_block": True,
        }

    def speak(self, text: str, *, interrupt: bool = False, dry_run: bool = False) -> dict[str, Any]:
        self.conversation.set_state("speaking")
        try:
            result = self.speech_output.speak(text, interrupt=interrupt, dry_run=dry_run)
        except VoiceError as exc:
            self.conversation.set_state("idle")
            return _voice_error_response(exc, self.conversation, speech_output=True)
        self.conversation.add_message("assistant", result.spoken_text or text, {"speech_output": result.to_dict()})
        self.conversation.set_state("idle")
        return result.to_dict()

    def listen(
        self,
        *,
        text: str | None = None,
        audio_base64: str | None = None,
        speak_response: bool = False,
        require_wake_word: bool = False,
    ) -> dict[str, Any]:
        return self.command(
            text=text,
            audio_base64=audio_base64,
            speak_response=speak_response,
            require_wake_word=require_wake_word,
        )

    def capture(
        self,
        *,
        text: str | None = None,
        audio_base64: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        audio_bytes = _decode_audio(audio_base64)
        try:
            input_result = self.speech_input.listen(text=text, audio_bytes=audio_bytes)
        except VoiceError as exc:
            self._last_latency_ms = _elapsed_ms(started)
            return _voice_error_response(exc, self.conversation, latency_ms=self._last_latency_ms)
        transcript = input_result.transcript.strip()
        self._last_latency_ms = _elapsed_ms(started)
        if not transcript:
            return {
                "ok": False,
                "status": "recognition_failed",
                "message": MICROPHONE_UNAVAILABLE_MESSAGE if not audio_base64 and text is None else "I could not understand the audio.\nPlease try speaking again.",
                "transcript": "",
                "confidence": input_result.confidence,
                "speech_input": input_result.to_dict(),
                "session": self.conversation.to_dict(),
                "latency_ms": self._last_latency_ms,
            }
        return {
            "ok": True,
            "status": input_result.status,
            "message": "Voice transcript captured.",
            "transcript": transcript,
            "confidence": input_result.confidence,
            "speech_input": input_result.to_dict(),
            "session": self.conversation.to_dict(),
            "latency_ms": self._last_latency_ms,
        }

    def command(
        self,
        *,
        text: str | None = None,
        audio_base64: str | None = None,
        speak_response: bool = False,
        require_wake_word: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        self.conversation.start()
        self.conversation.set_state("listening")
        audio_bytes = _decode_audio(audio_base64)
        try:
            input_result = self.speech_input.listen(text=text, audio_bytes=audio_bytes)
        except VoiceError as exc:
            self.conversation.set_state("idle")
            self._last_latency_ms = _elapsed_ms(started)
            return _voice_error_response(exc, self.conversation, latency_ms=self._last_latency_ms)
        transcript = input_result.transcript.strip()
        wake_match = self.wake_detector.detect(transcript)

        if require_wake_word and self.wake_detector.config.enabled and not wake_match.matched:
            self.conversation.set_state("idle")
            self._last_latency_ms = _elapsed_ms(started)
            return {
                "ok": False,
                "status": "wake_word_not_detected",
                "message": "Wake word was not detected. Use push-to-talk or say Hey Grandpa.",
                "transcript": transcript,
                "speech_input": input_result.to_dict(),
                "wake_word": wake_match.to_dict(),
                "session": self.conversation.to_dict(),
                "latency_ms": self._last_latency_ms,
            }

        command_text = wake_match.command_text if wake_match.matched else transcript
        if not command_text:
            self.conversation.set_state("idle")
            self._last_latency_ms = _elapsed_ms(started)
            return {
                "ok": False,
                "status": "empty",
                "message": "I did not catch a command.",
                "transcript": transcript,
                "speech_input": input_result.to_dict(),
                "session": self.conversation.to_dict(),
                "latency_ms": self._last_latency_ms,
            }

        self.conversation.add_message("user", command_text, {"transcript": transcript, "wake_word": wake_match.to_dict()})
        self.conversation.current_task = command_text

        if _is_high_risk_voice(command_text):
            response = "I cannot run high-risk PC actions from voice alone. Please use the approval flow."
            self.conversation.add_message("assistant", response, {"risk_level": "HIGH", "blocked_from_voice": True})
            self.conversation.set_state("idle")
            self._last_latency_ms = _elapsed_ms(started)
            return {
                "ok": False,
                "status": "blocked",
                "risk_level": "HIGH",
                "approval_required": True,
                "message": response,
                "transcript": transcript,
                "command_text": command_text,
                "session": self.conversation.to_dict(),
                "latency_ms": self._last_latency_ms,
            }

        self.conversation.set_state("thinking")
        response = _route_voice_request(command_text)
        message = response.get("message") or "I handled that voice request."
        self.conversation.add_message("assistant", message, response)
        if speak_response:
            self.conversation.set_state("speaking")
            try:
                response["speech_output"] = self.speech_output.speak(message, interrupt=True, dry_run=False).to_dict()
            except VoiceError as exc:
                response["speech_output"] = _voice_error_response(exc, self.conversation, speech_output=True)
        self.conversation.set_state("idle")
        self._last_latency_ms = _elapsed_ms(started)
        return {
            "ok": response.get("status") not in {"blocked", "error"},
            "status": response.get("status", "handled"),
            "message": message,
            "assistant_text": message,
            "action_status": response.get("status", "handled"),
            "transcript": transcript,
            "command_text": command_text,
            "speech_input": input_result.to_dict(),
            "wake_word": wake_match.to_dict(),
            "planner": response.get("planner"),
            "knowledge_context": response.get("knowledge_context"),
            "memory_context": response.get("memory_context"),
            "agent": response.get("agent"),
            "risk_level": response.get("risk_level", "LOW"),
            "approval_required": response.get("approval_required", False),
            "session": self.conversation.to_dict(),
            "latency_ms": self._last_latency_ms,
            "speech_output": response.get("speech_output"),
        }


_RUNTIME: VoiceRuntime | None = None
_RUNTIME_LOCK = threading.RLock()


def get_voice_runtime() -> VoiceRuntime:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = VoiceRuntime()
        return _RUNTIME


def _route_voice_request(command_text: str) -> dict[str, Any]:
    planner = _safe_planner(command_text)
    knowledge = _safe_knowledge_context(command_text)
    memory = _safe_memory_context(command_text)

    try:
        from grandpa.local_actions import handle_local_action

        result = handle_local_action(command_text, execute=True)
        if not result.should_fallback and result.status != "error":
            return {
                "status": result.status,
                "message": result.tts_text or result.message,
                "kind": result.kind,
                "target": result.target,
                "approval_required": result.status == "requires_confirmation" or result.permission == "requires_confirmation",
                "risk_level": _risk_from_permission(result.permission),
                "planner": planner,
                "knowledge_context": knowledge,
                "memory_context": memory,
            }
    except Exception:
        logger.debug("Voice local action route failed", exc_info=True)

    agent = _safe_agent_goal(command_text)
    if agent:
        return {
            "status": agent.get("status", "handled"),
            "message": agent.get("result_summary") or "I prepared a safe local plan.",
            "risk_level": (planner or {}).get("estimated_risk", "LOW"),
            "approval_required": bool(agent.get("approvals_needed")),
            "planner": planner,
            "knowledge_context": knowledge,
            "memory_context": memory,
            "agent": agent,
        }

    return {
        "status": "handled",
        "message": "I heard you. I prepared context for Grandpa's chat brain to answer this in the main conversation.",
        "risk_level": (planner or {}).get("estimated_risk", "LOW"),
        "approval_required": False,
        "planner": planner,
        "knowledge_context": knowledge,
        "memory_context": memory,
    }


def _safe_planner(command_text: str) -> dict[str, Any] | None:
    try:
        from grandpa.planner import analyze_request

        analysis = analyze_request(command_text)
        return {
            "intent": analysis.intent,
            "goal_class": analysis.goal_class,
            "confidence": analysis.confidence,
            "estimated_risk": analysis.estimated_risk,
            "required_skills": list(analysis.required_skills),
            "workflow_suitable": analysis.workflow_suitable,
        }
    except Exception:
        logger.debug("Voice planner context unavailable", exc_info=True)
        return None


def _safe_knowledge_context(command_text: str) -> dict[str, Any] | None:
    try:
        from grandpa.knowledge import knowledge_context

        context = knowledge_context(command_text, limit=3)
        return {
            "mode": context.get("mode"),
            "truthful_note": context.get("truthful_note"),
            "document_count": len(context.get("documents", [])),
            "chunk_count": len(context.get("chunks", [])),
            "summary": context.get("summary"),
        }
    except Exception:
        logger.debug("Voice knowledge context unavailable", exc_info=True)
        return None


def _safe_memory_context(command_text: str) -> dict[str, Any] | None:
    try:
        from grandpa.memory.intelligence import ranked_memory_context

        context = ranked_memory_context(command_text, limit=3)
        matches = context.get("matches", []) if isinstance(context, dict) else []
        return {
            "available": bool(context.get("available")) if isinstance(context, dict) else False,
            "confidence": float(context.get("confidence", 0.0)) if isinstance(context, dict) else 0.0,
            "count": len(matches),
            "items": matches,
        }
    except Exception:
        logger.debug("Voice memory context unavailable", exc_info=True)
        return None


def _safe_agent_goal(command_text: str) -> dict[str, Any] | None:
    try:
        from grandpa.agents.goal_mode import create_goal

        goal = create_goal(command_text, execute=True)
        return goal.to_dict()
    except Exception:
        logger.debug("Voice agent goal unavailable", exc_info=True)
        return None


def _decode_audio(audio_base64: str | None) -> bytes | None:
    if not audio_base64:
        return None
    try:
        return base64.b64decode(audio_base64)
    except Exception:
        return None


def _voice_error_response(
    exc: VoiceError,
    conversation: VoiceConversation,
    *,
    latency_ms: float = 0.0,
    speech_output: bool = False,
) -> dict[str, Any]:
    response = exc.to_dict()
    response.update(
        {
            "session": conversation.to_dict(),
            "latency_ms": latency_ms,
            "speech_output": speech_output,
        }
    )
    return response


def _is_high_risk_voice(text: str) -> bool:
    normalized = text.lower()
    return any(re.search(pattern, normalized) for pattern in HIGH_RISK_VOICE_PATTERNS)


def _risk_from_permission(permission: str | None) -> str:
    if permission == "blocked":
        return "BLOCKED"
    if permission == "requires_confirmation":
        return "MEDIUM"
    if permission == "unsupported":
        return "LOW"
    return "LOW"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["VoiceRuntime", "get_voice_runtime"]
