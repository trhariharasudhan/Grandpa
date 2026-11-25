---
name: grandpa-security-governance
description: Security review and trust-boundary rules for Grandpa - risk tiers and confirmation policy, pc_control approval codes and emergency stop, API key auth, phone device pairing and remote approvals, encrypted credentials (SecretStore / grandpa vault), plugin and MCP trust, screen privacy and redaction, SSRF and file policy, the inherited shell_exec tool, and audit logs. Use before changing any of these, when reviewing a PR for safety, or when a feature seems to need a looser permission.
---

# Grandpa security and governance

Grandpa can type, click, kill processes, delete files, read the screen, send
mail and accept commands from a phone. Each of those is a separate trust
boundary. This skill is the review lens; the mechanics live in the domain
skills. Boundary inventory with file paths: [references/boundaries.md](references/boundaries.md).

## Principles (from the code, not aspirations)

1. **The human at the PC is the only authority.** The model, a phone, a plugin, an
   MCP server, a workflow trigger, a web page or a screen's text cannot approve anything.
2. **One door.** Actions run only through `action_layer.executor.execute`; consent is a
   callback held by an interactive caller. No callback → refused (`confirmation_required`).
3. **Risk only goes up.** Callers, plugin manifests and MCP configs can tighten, never loosen.
4. **Deny by default** for MCP tools (`allow` list), plugins (off until `grandpa plugin enable`,
   file fingerprints pinned), device tokens (`DEVICE_ALLOWED_PATHS`), headless routes (404 filter).
5. **Secrets at rest go through `security/secret_store.SecretStore`** (DPAPI on Windows, keyring
   elsewhere, a loudly-reported `0600` file as last resort). Never write a key into `config.toml`, a
   log, a test fixture or a skill.
6. **Voice is not identity.** Never authenticate or approve by voice match.

## Review workflow (for any change touching a boundary)

1. Identify which boundary moves (actuation, files, processes, network, remote surfaces,
   extension code, perception) – see the reference table.
2. Read the boundary's module docstring and its tests. They state the threat it answers.
3. Check the five questions:
   - Who can trigger this now that could not before (origin, network reachability, unattended runs)?
   - Does every path still pass `execute()` and its confirmation rule?
   - Can a non-human caller supply consent (auto-yes flags, `--yes`, piped stdin)? `cli/_tool_loop.py`
     treats non-interactive stdin as "nobody to ask"; keep that property.
   - Is anything sensitive logged, cached, sent to a model, or sent off-machine (OCR text, mail
     bodies, ElevenLabs text)? Redaction lives in `screen/redaction.py` and is reused by `oops`.
   - Is there an audit record and a kill switch (`pc_control.emergency_stop`, `GRANDPA_MCP_OFF=1`,
     `GRANDPA_PLUGINS_OFF`, `grandpa devices revoke`)?
4. Require tests that prove the refusal, not just the happy path (pattern: tests that assert
   `confirmation_required` when no callback is given).
5. Write the decision down in the PR: boundary, threat, control, test.

## Hard constraints

- Do not lower a tier, remove an `_ALWAYS_CONFIRM` entry, widen `DEVICE_ALLOWED_PATHS`, add a
  headless route, or make an MCP tool non-HIGH without the owner's explicit approval.
- Do not add arbitrary shell/PowerShell execution to the catalogue (`shell_run`, `script_run`
  are in `EXCLUSIONS`). The inherited `tools/shell_exec.py` tool (`shell=True`, confirmation
  required, sanitised env) is reachable only via the agents/tools path – treat changes to it, or new
  callers, as security-critical.
- Do not bind the server to a non-loopback address without an API key (`check_bind_safety`).
- Do not read or capture screens of apps on the privacy list or password fields (`screen/privacy.py`).
- Do not commit personal data (recordings, PATH dumps, user names, tokens). Note: the repo already
  tracks `voice_runtime/diagnostics/user_path_before_ffmpeg.txt`, a PATH dump with a local user path.

## Known gaps to keep in mind (verified 2026-11-25)

- `security/injection_scanner.py` is not called by any product path (only `_rust_bridge.py`).
  Screen/web/mail text reaching the model is not scanned for prompt injection.
- `grandpa-guard` (Llama Guard role) is registered but no action path consults it.
- Two approval mechanisms coexist: inline callbacks (action layer) and staged approval codes
  (`pc_control` + `grandpa approve --code`, HTTP `/api/local-action/{id}/approve`).
- `AuthMiddleware` passes everything when no API key is configured; only `--no-auth` on loopback
  produces that state. Keep it that way.

## Verification

- Security tests: `uv run python -m pytest tests/security tests/devices tests/plugins tests/mcp tests/server tests/action_layer -q`
- Confirmation probe (needs Ollama): `uv run python scripts/verify_confirmation_enforcement.py`
- `GRANDPA_HOME=$(mktemp -d) uv run grandpa doctor` reports the secret-store backend honestly.
