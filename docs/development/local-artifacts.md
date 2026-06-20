# Local Generated Artifacts

The following files and directories are generated during local development,
testing, documentation builds, frontend builds, desktop builds, or mobile
builds. They should not be committed.

| Artifact | Source | Why it is ignored |
| --- | --- | --- |
| `.uv-cache/` | `uv` dependency resolver and installer cache | Local package cache; can be large and machine-specific. |
| `.coverage` | Python coverage tools | Local test coverage result. |
| `site/` | MkDocs build output | Generated documentation site. |
| `target/` | Rust builds | Generated Rust workspace build output. |
| `frontend/dist/` | Vite frontend builds | Generated web assets. |
| `frontend/src-tauri/target/` | Tauri desktop builds | Generated desktop Rust build output. |
| `dist/` | Python or frontend packaging tools | Generated distribution output. |
| `node_modules/` | npm installs | Local JavaScript dependency install tree. |
| `__pycache__/` | Python bytecode cache | Interpreter-generated cache files. |
| `.pytest_cache/` | pytest | Local test cache. |
| `.ruff_cache/` | Ruff | Local lint cache. |
| `logs/` and `*.log` | Runtime and debug logging | Machine-specific runtime output. |
| `mobile/**/build/` | Flutter and Android builds | Generated mobile build output. |

If one of these appears in `git status`, prefer updating `.gitignore` or
cleaning the local workspace instead of committing it.

Do not remove generated artifacts with destructive commands unless you have
confirmed the exact path and understand which tool produced it.
