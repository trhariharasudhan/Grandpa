# Local API Server

Grandpa includes an optional FastAPI server for trusted local clients.

```powershell
uv sync --extra server
uv run grandpa serve --host 127.0.0.1 --port 8000
```

Keep the host on `127.0.0.1`. Public network exposure is not part of the
supported runtime.

## Authentication

The API is authenticated by default. Every route under `/v1` and `/api` can
read personal memory or drive the desktop, and loopback alone does not isolate
it — any process on the machine can reach it.

On first run `grandpa serve` generates a key, prints it, and saves it to
`~/.grandpa/config.toml` under `[server.auth] api_key`. Send it as a bearer
token:

```powershell
curl -H "Authorization: Bearer gp_sk_..." http://127.0.0.1:8000/v1/models
```

`GET /health` is intentionally left open so liveness probes work.

To pin a specific key instead, set `GRANDPA_API_KEY`. (`Grandpa_API_KEY` is the
deprecated pre-rename spelling; it is still read, with a warning.)

To serve without authentication — only on a machine where every local process
is trusted — pass `--no-auth`.

## Action Approvals

Actions that require confirmation are staged, not executed, and the approval
code is printed on the Grandpa console rather than returned in the HTTP
response. Approving takes both the action id and that code:

```powershell
curl -X POST http://127.0.0.1:8000/api/local-action/<action_id>/approve `
  -H "Authorization: Bearer gp_sk_..." `
  -H "Content-Type: application/json" `
  -d '{\"token\": \"<approval code>\"}'
```

This keeps the request channel and the approval channel separate: a client that
stages an action cannot approve its own request.

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
