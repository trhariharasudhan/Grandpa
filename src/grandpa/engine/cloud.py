"""Cloud model providers, reached through their OpenAI-compatible APIs.

Grandpa is local-first: Ollama stays the default and nothing here runs until
the user adds a provider and its key (the desktop app's Settings, "Models &
API keys"). Then that provider's chosen models show up next to the local ones
as ``@<provider>/<model>`` (``@groq/llama-3.3-70b-versatile``). ``@`` can't
start an Ollama model name, so the two never collide.

* Providers live in ``<grandpa home>/providers.toml``; **keys never do**: they
  go to the secret store (DPAPI on Windows) as ``provider.<id>.api_key``.
* The Ollama adapter hands any ``@`` model to :func:`client_for`, so the chat,
  the tool loop, streaming and tool calls all work the same way.
* Only the user's own request reaches the provider's address; nothing else
  is sent anywhere.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

import httpx

from grandpa.runtime.utils import messages_to_dicts

logger = logging.getLogger(__name__)

PREFIX = "@"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
MAX_MODELS = 60

#: Known providers: label, OpenAI-compatible base URL, whether a key is needed.
PRESETS: dict[str, tuple[str, str, bool]] = {
    "openai": ("OpenAI", "https://api.openai.com/v1", True),
    "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com/v1", True),
    "gemini": (
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        True,
    ),
    "groq": ("Groq", "https://api.groq.com/openai/v1", True),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", True),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1", True),
    "mistral": ("Mistral", "https://api.mistral.ai/v1", True),
    "together": ("Together AI", "https://api.together.xyz/v1", True),
    "lmstudio": ("LM Studio (this PC)", "http://127.0.0.1:1234/v1", False),
}


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str
    models: tuple[str, ...]
    needs_key: bool = True


def providers_path() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "providers.toml"


def key_name(provider_id: str) -> str:
    return f"provider.{provider_id}.api_key"


def is_cloud(model: str) -> bool:
    return str(model or "").startswith(PREFIX)


def split_model(model: str) -> tuple[str, str]:
    """``"@groq/llama-3"`` -> ``("groq", "llama-3")``. ValueError otherwise."""
    if not is_cloud(model) or "/" not in model:
        raise ValueError(f"not a cloud model name: {model!r}")
    provider, name = model[len(PREFIX) :].split("/", 1)
    if not _ID.match(provider) or not name:
        raise ValueError(f"not a cloud model name: {model!r}")
    return provider, name


def check_id(provider_id: str) -> str:
    if not _ID.match(str(provider_id or "")):
        raise ValueError("Provider ids use lowercase letters, digits and '-'.")
    return provider_id


def check_url(url: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if not re.match(r"^https://[^\s/]+(/\S*)?$", url) and not re.match(
        r"^http://(127\.0\.0\.1|localhost)(:\d+)?(/\S*)?$", url
    ):
        raise ValueError("The address must be https://..., or http:// on this PC.")
    return url


# --- the providers file ----------------------------------------------------------


def load_providers(path: Path | None = None) -> dict[str, Provider]:
    import tomllib

    path = path or providers_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("providers.toml unreadable: %s", exc)
        return {}
    found: dict[str, Provider] = {}
    for pid, table in (data.get("providers") or {}).items():
        try:
            check_id(pid)
            url = check_url(table.get("base_url", ""))
        except (ValueError, AttributeError):
            continue
        models = tuple(
            str(m)
            for m in (table.get("models") or [])
            if isinstance(m, str) and m.strip()
        )[:MAX_MODELS]
        preset = PRESETS.get(pid)
        found[pid] = Provider(
            id=pid,
            label=str(table.get("label") or (preset[0] if preset else pid)),
            base_url=url,
            models=models,
            needs_key=bool(table.get("needs_key", preset[2] if preset else True)),
        )
    return found


def save_providers(providers: dict[str, Provider], path: Path | None = None) -> None:
    import tomlkit

    path = path or providers_path()
    doc = tomlkit.document()
    doc.add(
        tomlkit.comment("Cloud model providers (keys are in Grandpa's secret store).")
    )
    table = tomlkit.table(is_super_table=True)
    for p in providers.values():
        entry = tomlkit.table()
        entry["label"] = p.label
        entry["base_url"] = p.base_url
        entry["needs_key"] = p.needs_key
        entry["models"] = list(p.models)
        table[p.id] = entry
    doc["providers"] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    tmp.replace(path)


def cloud_model_names(providers: dict[str, Provider] | None = None) -> List[str]:
    providers = load_providers() if providers is None else providers
    return [f"{PREFIX}{p.id}/{m}" for p in providers.values() for m in p.models]


# --- talking to a provider -----------------------------------------------------------


def _openai_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    out = messages_to_dicts(messages)
    for message in out:
        for call in message.get("tool_calls", []) or []:
            fn = call.get("function", {})
            if not isinstance(fn.get("arguments"), str):
                fn["arguments"] = json.dumps(fn.get("arguments") or {})
    return out


def _openai_tools(tools: Any) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        t if t.get("type") == "function" else {"type": "function", "function": t}
        for t in tools
    ]


class CloudClient:
    """One provider. Same call shapes and results as the Ollama adapter."""

    def __init__(
        self, provider: Provider, api_key: str | None, *, timeout: float = 120.0
    ) -> None:
        self.provider = provider
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=provider.base_url, headers=headers, timeout=timeout
        )

    def _payload(self, messages, model, temperature, max_tokens, tools, stream) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _openai_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        openai_tools = _openai_tools(tools)
        if openai_tools:
            payload["tools"] = openai_tools
        return payload

    def _error(self, resp: httpx.Response) -> RuntimeError:
        try:
            detail = resp.json().get("error", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:  # noqa: BLE001
            message = resp.text[:200]
        hint = (
            " (check the API key in Settings)" if resp.status_code in (401, 403) else ""
        )
        return RuntimeError(
            f"{self.provider.label}: HTTP {resp.status_code}: {message}{hint}"
        )

    @staticmethod
    def _result(
        text: str, calls: list[dict], model: str, usage: dict | None
    ) -> Dict[str, Any]:
        usage = usage or {}
        result: Dict[str, Any] = {
            "content": text,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "model": model,
            "finish_reason": "stop",
        }
        if calls:
            result["tool_calls"] = [
                {
                    "id": c.get("id") or f"call_{i}",
                    "name": c.get("name", ""),
                    "arguments": c.get("arguments") or "{}",
                }
                for i, c in enumerate(calls)
            ]
        return result

    def generate(
        self,
        messages,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ) -> Dict[str, Any]:
        resp = self._client.post(
            "/chat/completions",
            json=self._payload(
                messages, model, temperature, max_tokens, kwargs.get("tools"), False
            ),
        )
        if resp.status_code >= 400:
            raise self._error(resp)
        data = resp.json()
        message = (data.get("choices") or [{}])[0].get("message", {}) or {}
        calls = [
            {
                "id": c.get("id"),
                "name": (c.get("function") or {}).get("name", ""),
                "arguments": (c.get("function") or {}).get("arguments", "{}"),
            }
            for c in message.get("tool_calls") or []
        ]
        return self._result(
            message.get("content") or "",
            calls,
            data.get("model", model),
            data.get("usage"),
        )

    def generate_streaming(
        self,
        messages,
        *,
        model: str,
        on_text: Callable[[str], None],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ) -> Dict[str, Any]:
        text: list[str] = []
        calls: dict[int, dict] = {}
        payload = self._payload(
            messages, model, temperature, max_tokens, kwargs.get("tools"), True
        )
        with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise self._error(resp)
            for line in resp.iter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    chunk = json.loads(body)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0]).get("delta", {}) or {}
                piece = delta.get("content") or ""
                if piece:
                    text.append(piece)
                    try:
                        on_text(piece)
                    except Exception:  # noqa: BLE001 - a display never stops a reply
                        logger.debug("stream sink failed", exc_info=True)
                for part in delta.get("tool_calls") or []:
                    slot = calls.setdefault(
                        int(part.get("index", 0)),
                        {"id": None, "name": "", "arguments": ""},
                    )
                    slot["id"] = part.get("id") or slot["id"]
                    fn = part.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
        return self._result(
            "".join(text), [calls[i] for i in sorted(calls)], model, None
        )

    async def stream(
        self,
        messages,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ):
        pieces: list[str] = []
        self.generate_streaming(
            messages,
            model=model,
            on_text=pieces.append,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        for piece in pieces:
            yield piece

    def list_remote_models(self) -> list[str]:
        resp = self._client.get("/models")
        if resp.status_code >= 400:
            raise self._error(resp)
        data = resp.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        names = []
        for item in items or []:
            name = item.get("id") if isinstance(item, dict) else item
            if isinstance(name, str):
                names.append(name.removeprefix("models/"))
        return sorted(set(names))


def client_for(model: str) -> tuple[CloudClient, str]:
    """The client and the provider's own model name for an ``@`` model."""
    provider_id, name = split_model(model)
    provider = load_providers().get(provider_id)
    if provider is None:
        raise RuntimeError(
            f"No provider called {provider_id!r}; add it in Settings, Models & API keys."
        )
    key = None
    if provider.needs_key:
        from grandpa.security.secret_store import SecretStore

        key = SecretStore().get(key_name(provider_id))
        if not key:
            raise RuntimeError(
                f"{provider.label} has no API key yet; add it in Settings."
            )
    return CloudClient(provider, key), name


__all__ = [
    "PRESETS",
    "PREFIX",
    "CloudClient",
    "Provider",
    "check_id",
    "check_url",
    "client_for",
    "cloud_model_names",
    "is_cloud",
    "key_name",
    "load_providers",
    "providers_path",
    "save_providers",
    "split_model",
]
