"""Optional local vision model analysis via Ollama-compatible APIs."""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

DEFAULT_VISION_PROMPT = "Describe this image clearly and mention any visible text."
FALLBACK_VISION_MODELS = ("grandpa-eyes", "llava:latest")
OLLAMA_ENGINE = "ollama"
OLLAMA_UNAVAILABLE = "Ollama is not available. Start it with: ollama serve"


def local_model_status() -> dict[str, Any]:
    configured_model = configured_vision_model()
    return {
        "available": _ollama_available(),
        "configured_model": configured_model,
        "fallback_models": list(FALLBACK_VISION_MODELS),
        "engine": OLLAMA_ENGINE,
    }


def configured_vision_model() -> str | None:
    for key in ("GRANDPA_VISION_MODEL", "GRANDPA_EYES_MODEL", "OLLAMA_VISION_MODEL"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    try:
        from grandpa.core.config import load_config

        config = load_config()
        vision = getattr(config, "vision", None)
        model = getattr(vision, "model", None) if vision is not None else None
        if model:
            return str(model)
    except Exception:
        return None
    return None


def analyze_image_with_local_model(
    data: bytes,
    filename: str | None,
    mime_type: str | None,
    prompt: str | None,
) -> dict[str, Any]:
    if not data:
        return _response(False, None, "", "Empty image file.")

    final_prompt = (prompt or DEFAULT_VISION_PROMPT).strip() or DEFAULT_VISION_PROMPT
    models = _candidate_models()
    host = _ollama_host()
    image_payload = base64.b64encode(data).decode("ascii")

    try:
        with httpx.Client(base_url=host, timeout=120.0) as client:
            tags = client.get("/api/tags", timeout=5.0)
            tags.raise_for_status()
            installed = _installed_models(tags.json())
            if installed:
                model = next((candidate for candidate in models if _model_installed(candidate, installed)), None)
                if model is None:
                    return _response(
                        False,
                        models[0],
                        "",
                        f"Vision model is not installed. Run: ollama pull {models[0]}",
                    )
            else:
                model = models[0]

            response = client.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": final_prompt,
                    "images": [image_payload],
                    "stream": False,
                },
            )
            if _is_model_missing_response(response):
                return _response(
                    False,
                    model,
                    "",
                    f"Vision model is not installed. Run: ollama pull {model}",
                )
            response.raise_for_status()
            body = response.json()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
        return _response(False, None, "", OLLAMA_UNAVAILABLE)
    except httpx.HTTPStatusError as exc:
        text = exc.response.text[:300] if exc.response is not None else ""
        if _is_model_missing_text(text):
            model = models[0]
            return _response(False, model, "", f"Vision model is not installed. Run: ollama pull {model}")
        return _response(False, None, "", f"Ollama vision analysis failed: {text or exc}")
    except Exception as exc:
        return _response(False, None, "", f"Ollama vision analysis failed: {exc}")

    analysis = str(body.get("response") or body.get("message", {}).get("content") or "").strip()
    return _response(True, str(body.get("model") or model), analysis, None)


def _response(available: bool, model: str | None, analysis: str, error: str | None) -> dict[str, Any]:
    return {
        "available": available,
        "model": model,
        "analysis": analysis,
        "error": error,
    }


def _candidate_models() -> list[str]:
    candidates = []
    configured = configured_vision_model()
    if configured:
        candidates.append(configured)
    candidates.extend(FALLBACK_VISION_MODELS)
    deduped = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _ollama_host() -> str:
    return (
        os.environ.get("GRANDPA_OLLAMA_HOST")
        or os.environ.get("OLLAMA_HOST")
        or "http://localhost:11434"
    ).rstrip("/")


def _ollama_available() -> bool:
    try:
        with httpx.Client(base_url=_ollama_host(), timeout=2.0) as client:
            response = client.get("/api/tags")
            return response.status_code == 200
    except Exception:
        return False


def _installed_models(payload: dict[str, Any]) -> set[str]:
    models = payload.get("models")
    if not isinstance(models, list):
        return set()
    names = set()
    for item in models:
        if isinstance(item, dict) and item.get("name"):
            name = str(item["name"])
            names.add(name)
            if name.endswith(":latest"):
                names.add(name.removesuffix(":latest"))
    return names


def _model_installed(model: str, installed: set[str]) -> bool:
    return model in installed or f"{model}:latest" in installed


def _is_model_missing_response(response: httpx.Response) -> bool:
    return response.status_code == 404 or _is_model_missing_text(response.text)


def _is_model_missing_text(text: str) -> bool:
    lowered = text.lower()
    return "model" in lowered and ("not found" in lowered or "pull" in lowered or "not installed" in lowered)
