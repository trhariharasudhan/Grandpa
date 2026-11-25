# Trust boundaries in Grandpa (file map)

| Boundary | Controls | Files | Tests |
|---|---|---|---|
| Desktop actuation | risk tiers, `_ALWAYS_CONFIRM`, no-callback refusal, foreground/protected-window checks, cooldowns, emergency stop | `action_layer/catalogue.py`, `action_layer/executor.py`, `desktop/control/automation.py`, `desktop_context.py` (`active_window_is_protected`), `pc_control.py`, `desktop/kernel/` | `tests/action_layer/`, `tests/test_pc_control*.py`, `tests/desktop/` |
| Staged approvals | approval codes bound to origin, TTL, audit of decisions | `pc_control.py` (`approve_local_action`), `desktop/kernel/approvals.py`, `local_action_approvals.py`, `cli/approve_cmd.py`, `server/approval_routes.py` | `tests/test_pc_control_kernel.py`, `tests/cli/` |
| Files | sensitive-file policy, safe roots (`GRANDPA_FILE_SAFE_ROOTS`), HIGH delete, recycle bin | `files/`, `security/file_policy.py`, `security/file_utils.py` | `tests/test_file_*.py` |
| Processes / shell | no arbitrary shell in catalogue; `process_kill` HIGH and refuses system processes; inherited `shell_exec` tool with sanitised env + confirmation | `apps/process_kill.py`, `tools/shell_exec.py`, `security/subprocess_sandbox.py` | `tests/action_layer/test_process_kill.py`, `tests/tools/` |
| Network egress | SSRF block (private IPs, metadata), web search provider config | `security/ssrf.py`, `web_search/` | `tests/security/` |
| HTTP API | API key by default (`gp_sk_…`), loopback bind safety, upload limits | `server/auth_middleware.py`, `cli/serve.py`, `server/upload_router.py` | `tests/server/` |
| Phones (devices) | one-time 6-digit code, 5-minute window, 5 attempts, hashed tokens, path allow-list, approvals only at the PC, revoke | `devices/pairing.py`, `devices/approvals.py`, `devices/commands.py`, `server/device_routes.py` | `tests/devices/` |
| Headless node | route filter (404) in front of auth; no desktop/browser/file routes | `server/headless.py` | `tests/server/` |
| Credentials | DPAPI / keyring / 0600 file, migration only to a secure backend, `grandpa vault` | `security/secret_store.py`, `core/credentials.py`, `cli/vault_cmd.py` | `tests/security/test_secret_store.py`, `tests/core/test_credentials.py` |
| Plugins | off until enabled, permission prompt, file fingerprints, static code check (no grandpa internals, no eval/dynamic import), risk up from permissions, `ctx.run_action` limited to declared actions | `plugins/host.py`, `plugins/manifest.py` | `tests/plugins/` |
| MCP servers (client) | `~/.grandpa/mcp.toml`, `allow` list, HIGH + confirmation, timeouts, kill switch `GRANDPA_MCP_OFF=1` / `grandpa mcp off` | `mcp/servers.py`, `mcp/transport.py` | `tests/mcp/` |
| MCP server (inherited) | exposes Grandpa tools to third parties | `mcp/server.py` | `tests/mcp/` |
| Screen perception | private-apps list (`~/.grandpa/screen-private.txt`), no capture in password boxes, redaction | `screen/privacy.py`, `screen/redaction.py` | `tests/test_screen_privacy.py` |
| Browser | visible browser only, no password fields, form submit/purchase excluded | `browser_control.py`, `browser/` | `tests/test_browser_*.py` |
| Microphone | hardware tests gated; audio denied by default in tests | `voice/microphone.py`, `voice/live_capture.py` | `tests/test_audio_is_denied_by_default.py` |
| Cloud voice (opt-in) | ElevenLabs key via env/secret store; cache to avoid re-sending | `speech/elevenlabs_tts.py` | `tests/speech/` |
| Model output | deterministic phrase handlers never receive model text | `local/router.py`, `cli/chat_cmd.py` | `tests/test_action_origin_invariant.py` |

## Inherited platform security modules

`security/guardrails.py` (GuardrailsEngine wrapper), `capabilities.py` (RBAC), `taint.py`,
`audit.py` (SQLite + Merkle chain), `signing.py`, `scanner.py`, `injection_scanner.py`,
`credential_stripper.py`, `boundary.py`. Several are wired only into the agents/`SystemBuilder`
path (`system/`), not into the action layer; `injection_scanner.py` has no product caller.
Verify a module's callers (`rg -n "<module>" src`) before claiming it protects a path.
