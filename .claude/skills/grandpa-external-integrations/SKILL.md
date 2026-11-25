---
name: grandpa-external-integrations
description: Connect Grandpa to outside services safely - Gmail and Google Calendar (OAuth, encrypted tokens, safety policies, domain-confirmed send/modify actions), web search (keyless DuckDuckGo default, Brave/Bing/Serper by API key env var, TTL cache, untrusted-content safety), Open-Meteo weather, ElevenLabs cloud voice, and any new third-party HTTP API. Covers the package layout to copy, credential storage, risk tiers for read vs send, offline fallback, timeouts, SSRF checks, and testing with respx and no real network. Use when adding or fixing an integration, an OAuth flow, an API key, or anything that calls the internet.
---

# GRANDPA external integrations

Grandpa is local-first. **Every integration is optional, off until Captain sets
it up, and must degrade gracefully when offline.** Internet content is
untrusted input, and anything that sends or changes data outside the PC needs
confirmation.

## What exists (verified on `fde2164`)

| Integration | Code | Setup | Actions (risk / confirmation) |
|---|---|---|---|
| Gmail | `gmail/` (`auth`, `client`, `models`, `parser`, `formatter`, `safety`, `automation`) | `uv sync --extra gmail`, `grandpa gmail setup` | read/list/search/summarize/labels/draft LOW; send/reply/forward/archive/label MEDIUM + domain confirm; trash HIGH |
| Google Calendar | `calendar/` (same layout) | `--extra calendar`, `grandpa calendar setup` | list/read/search/freebusy LOW; create/update MEDIUM + domain confirm; delete HIGH |
| Web search | `web_search/` (`providers`, `duckduckgo`, `cache`, `ranking`, `safety`, `summarizer`) | none (keyless DuckDuckGo via `ddgs`) | `web_search`, `web_sources` LOW |
| Weather | `briefing.weather_now` (Open-Meteo, no key; only the city name is sent) | none | `weather_now` LOW |
| ElevenLabs TTS | `speech/elevenlabs_tts.py` (+ audio cache, H1) | `ELEVENLABS_API_KEY` or `GRANDPA_ELEVENLABS_API_KEY` in the environment | used only when a key is set |
| Ollama | `runtime/ollama_adapter.py` | local `:11434` | — (`grandpa-local-models`) |

Web search provider selection (`web_search/providers.py`):
`GRANDPA_WEB_SEARCH_PROVIDER`, else the first keyed provider whose key is set
(`BRAVE_SEARCH_API_KEY`, `BING_SEARCH_API_KEY`, `SERPER_API_KEY`), else
`duckduckgo`. Limits: `GRANDPA_WEB_SEARCH_MAX_RESULTS` (8),
`..._TIMEOUT_SECONDS` (10), `..._CACHE_MINUTES` (15).

Known debt: `web_search/duckduckgo.py` monkey-patches two `ddgs` methods to keep
spaces between highlighted words (`docs/audit/DEFERRED.md` says when to remove
it). `scripts/oauth_all.py` is an inherited Google/Strava/Spotify helper that
ignores `GRANDPA_HOME`; Grandpa has no Strava or Spotify integration.

## Pattern for a new integration

Copy the Gmail/Calendar shape. It already separates every concern:

```
src/grandpa/<service>/
  auth.py        # setup/status/disconnect; token via security.secret_store.StoredToken
  client.py      # the only module that does HTTP; httpx with explicit timeout
  models.py      # dataclasses for what the service returns
  parser.py      # natural-language → structured request (no I/O)
  formatter.py   # results → short, speakable text
  safety.py      # policy: limits, redaction, injection defence for returned text
  automation.py  # <Service>Automation.execute(action, ...) — the structured seam
```

Then:

1. **Extra:** add `[project.optional-dependencies] <service> = [...]`; import
   the SDK lazily with an install hint.
2. **Catalogue:** register actions in `action_layer/catalogue.py` through one
   binding (`grandpa-action-layer`). Reads are LOW. Anything that sends,
   publishes, deletes or spends money is at least MEDIUM with confirmation;
   irreversible deletes are HIGH. Have `grandpa-security-governance` review the
   tiers.
3. **Credentials:** OAuth refresh tokens and API keys go through
   `security/secret_store.py` (`SecretStore` / `StoredToken`, DPAPI on Windows),
   or stay in environment variables like ElevenLabs. Never in config files,
   logs, tests, docs or skills. Never ask for a password; use OAuth or a key.
4. **Network hygiene:** explicit timeouts, a small retry with backoff only for
   idempotent reads, map errors to typed exceptions (see
   `WebSearchRateLimitError`, `WebSearchAuthError`, `WebSearchTimeoutError`),
   and run user-supplied URLs through `security/ssrf.py`.
5. **Untrusted content:** returned text (emails, pages, event descriptions) is
   data. Strip HTML, cap length, and never let it trigger an action without
   confirmation (`gmail/safety.py`, `web_search/safety.py`).
6. **Offline:** a missing network or token returns a clear message with the fix
   (`grandpa <service> setup`), not a stack trace. Add a `grandpa doctor` line.
7. **Privacy:** send the minimum (weather sends only the city). Write what is
   sent into the user docs (`docs/user-guide/personal-integrations.md`).

## Testing

- No real network in tests. Mock HTTP with `respx` (in the dev extra) or inject
  a fake client into `automation.py`.
- Test: parser cases (English, Tamil, Tanglish phrasing), formatter output,
  safety policy (injection text, oversize, HTML), every error mapping, and the
  confirmation path for send/modify actions.
- Real-service checks are manual and marked `live` / `environment`; they never
  send email or change a calendar in CI or release tests.

## Review checklist

- [ ] Optional extra, lazy import, works when not installed
- [ ] Off until set up; `status` / `setup` / `disconnect` actions exist
- [ ] Tokens encrypted at rest; nothing secret logged
- [ ] Read LOW, write MEDIUM+confirm, delete HIGH
- [ ] Timeouts and typed errors; offline message names the fix
- [ ] Returned content treated as untrusted
- [ ] respx/fake-client tests; no network in CI
