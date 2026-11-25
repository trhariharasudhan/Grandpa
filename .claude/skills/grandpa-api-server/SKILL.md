---
name: grandpa-api-server
description: Work on Grandpa's local HTTP API - the FastAPI app factory, OpenAI-compatible /v1/chat/completions, the /v1 domain routers and /api local-action routes, API-key auth middleware, approval routes, uploads, WebSocket bridge, phone device routes, and the headless Pironman home-server node (grandpa server --headless). Use when adding or changing an endpoint, debugging grandpa serve, exposing a feature over HTTP or to a paired phone, or deploying the headless Docker image.
---

# Grandpa API server

`grandpa serve` runs a FastAPI app built by `server/app.py:create_app(...)`
(title "Grandpa API", OpenAI-compatible). It is **loopback-first and
authenticated by default**; the API is a second door to the same capabilities as
chat, so every route that acts must use the action-layer executor and must not
gain a weaker consent model than the CLI.

## Map (≈188 route decorators at `fde2164`)

| File | Routes | Notes |
|---|---|---|
| `server/routes.py` | ~60 | `/v1/chat/completions`, `/v1/models`, desktop, browser, screen, routines, memory, personal-memory, `/api/local-action/*` (staged approvals, emergency stop via `pc_control`) |
| `server/api_routes.py` | ~114 | inherited `/v1/agents`, `/v1/memory`, `/v1/traces`, … sub-routers |
| `server/approval_routes.py` | 3 | approve/deny staged actions |
| `server/device_routes.py` | 7 | `/v1/devices/*` pairing, command, voice, notifications, pending, llm |
| `server/upload_router.py` | 2 | `/v1/connectors/upload` with size limits |
| `server/ws_bridge.py`, `stream_bridge.py` | 1 | WebSocket / streaming bridges |
| `server/headless.py` | 1 + filter | `/v1/workflows` (read-only) + `HeadlessRouteFilter` |
| `server/auth_middleware.py` | – | API key (`gp_sk_…`), device tokens on `DEVICE_ALLOWED_PATHS` only, `check_bind_safety` |
| `cli/serve.py`, `cli/server_cmd.py` | – | key resolution (env `GRANDPA_API_KEY` → SecretStore → config migration), `--host/--port/--no-auth`, `grandpa server --headless --pc …`, `server pair/status` |

## Workflow: add or change an endpoint

1. Decide whether it should exist on HTTP at all. If it performs an action, route it through
   `action_layer.executor.execute` with `Origin.HTTP`; an HTTP caller usually **cannot** confirm inline,
   so confirmable actions must either be refused or staged for approval at the PC
   (pattern: `devices/approvals.py`, `pc_control` approval codes).
2. Put thin handlers in the router and the logic in the domain/service package (`services/` façades exist).
3. Auth: every new path is behind `AuthMiddleware` automatically. Never add an auth exemption; for phones,
   widening `DEVICE_ALLOWED_PATHS` is a security decision (one route at a time, owner approval).
4. Headless: new routes are 404 on the node unless explicitly allowed in `server/headless.py`. Only add
   routes that need no desktop, screen, browser or files.
5. Tests with FastAPI's TestClient in `tests/server/` (and `tests/devices/` for device routes): cover
   401 without key, 200 with key, device-token refusal on non-allowed paths, headless 404.
6. Run `uv run python -m pytest tests/server tests/devices -q`.

## Running locally (sandboxed)

```bash
GRANDPA_HOME=$(mktemp -d) uv run grandpa serve --host 127.0.0.1 --port 8000
# prints the generated key once; send:  Authorization: Bearer <key>
```

Binding to a non-loopback address without a key exits (`check_bind_safety`); `--no-auth` is
loopback-only in practice. The headless node: `grandpa server --headless --pc http://<pc>:8000`,
`grandpa server pair`, image `docker/headless.Dockerfile` (built by `.github/workflows/docker-headless.yml`
for arm64).

## Constraints

- No route may accept consent from the HTTP caller for HIGH or `_ALWAYS_CONFIRM` actions.
- Never log Authorization headers, device tokens, upload contents or memory bodies.
- Keep CORS restrictive; do not add `*` origins.
- Many `/v1` routers are inherited platform API (agents, traces); they are not product requirements –
  ask before extending them.
