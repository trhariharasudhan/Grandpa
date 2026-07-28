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
