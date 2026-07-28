# Local API Server

Grandpa includes an optional FastAPI server for trusted local clients.

```powershell
uv sync --extra server
uv run grandpa serve --host 127.0.0.1 --port 8000
```

Keep the host on `127.0.0.1`. Public network exposure is not part of the
supported runtime.

## Core Routes

- `GET /health`: local health and engine state.
- `POST /v1/chat/completions`: OpenAI-compatible local chat.
- `GET /v1/models`: models visible through Ollama.
- `GET /v1/info`: local runtime information.
- `/api/local-action/*`: permission-aware local action flow.
- `/v1/approvals/*`: pending action confirmation.
- `/v1/screen/*`, `/v1/browser/*`, and `/v1/automation/*`: local diagnostics
  and bounded assistant operations.

The server does not serve a dashboard, public webhooks, research routes, or
remote usage tracking. Authentication and approval policy remain required where
configured.
