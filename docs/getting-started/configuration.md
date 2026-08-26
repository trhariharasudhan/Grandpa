# Configuration

Grandpa reads user configuration from:

```text
%USERPROFILE%\.grandpa\config.toml
```

Generate a local configuration with:

```powershell
uv run grandpa init
uv run grandpa doctor
```

## Local Inference

Ollama is the supported inference runtime:

```toml
[engine]
default = "ollama"

[engine.ollama]
host = "http://127.0.0.1:11434"
model = "qwen2.5:3b"
```

The host should remain loopback unless you have independently secured the
network path.

## Local API

The optional API is disabled unless started explicitly:

```toml
[server]
host = "127.0.0.1"
port = 8000
```

Do not bind the API publicly without authentication and a reviewed deployment
model.

## Local Data

Grandpa stores configuration, reminders, notes, logs, audit records, and
optional OAuth credentials below `%USERPROFILE%\.grandpa`. Keep that directory
private and exclude it from source control.

## Optional Features

Install only the local capabilities you need:

```powershell
uv sync --extra server --extra voice --extra screen
```

Gmail and Calendar each have a dedicated optional extra. Their OAuth tokens
remain local and must never be pasted into chat or committed.

## Safety

Permission policy and confirmation settings should be changed through supported
configuration commands. Grandpa does not support remote skill marketplaces,
cloud inference fallback, social messaging channels, or external analytics.

## Environment Variables

Grandpa reads environment variables straight from the process environment. It
does **not** load a `.env` file — nothing in the codebase reads one and
`python-dotenv` is not a dependency, so a value written to `.env` has no
effect. (A `.env.example` used to ship and the README told you to copy it; both
were removed, because the file never did anything.)

Set variables in your shell, or prefer `config.toml` where an equivalent key
exists — that is the supported configuration mechanism and it persists:

```powershell
# One session
$env:GRANDPA_API_KEY = "gp_sk_..."

# Persist for your user
[Environment]::SetEnvironmentVariable("GRANDPA_API_KEY", "gp_sk_...", "User")
```

Commonly used variables:

| Variable | Purpose |
|----------|---------|
| `GRANDPA_HOME` | Config and data directory (default `~/.grandpa`) |
| `Grandpa_CONFIG` | Path to `config.toml` |
| `GRANDPA_API_KEY` | Local API bearer key; equivalent to `[server.auth] api_key` |
| `OLLAMA_HOST` | Ollama endpoint; equivalent to `[engine.ollama] host` |
| `GRANDPA_TESSERACT_CMD` | Path to `tesseract.exe` for OCR |
| `TAVILY_API_KEY` / `BRAVE_SEARCH_API_KEY` | Optional web-search providers |

Anything with a `config.toml` equivalent should be set there instead; the
environment variable wins when both are present.

## Removed Options

Configuration keys that no code path read have been removed rather than left
looking functional. Loading a `config.toml` that still sets one prints a
warning naming the key. The current list lives in `REMOVED_CONFIG_KEYS` in
`grandpa/core/config.py`; see [Security](../user-guide/security.md) for the
security-specific entries.
