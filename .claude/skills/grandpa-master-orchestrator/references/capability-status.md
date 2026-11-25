# Capability status matrix

Status meanings: **Implemented** (code path exists, is reachable from a user
surface, and has tests), **Partial** (reachable but incomplete, weak, or with a
known defect), **Experimental** (exists behind an opt-in or a manual flow),
**Planned** (vision only, no code), **Missing** (expected by the vision, absent).

Evidence is a path in the repo at `main` @ `fde2164` (2026-11-24). The repo's
own deeper audit is `docs/audit/CAPABILITY-MAP.md` (2026-10-27, 96 items);
prefer it for per-item run evidence, and this file for what changed since.

| Capability | Status | Evidence / notes |
|---|---|---|
| Text chat with local LLM | Implemented | `cli/chat_cmd.py`, `cli/ask.py`, `runtime/ollama_adapter.py` |
| Tool use by the model (catalogue as tools) | Implemented | `action_layer/loop.py`; on by default in chat (`[tools] chat_tool_loop`) |
| Deterministic phrase commands | Implemented | `local/router.py`, `cli/_*_route.py` |
| Risk tiers + confirmation + audit | Implemented | `action_layer/executor.py`, `catalogue.py` (`_ALWAYS_CONFIRM`) |
| Windows app/window/volume/brightness/power control | Implemented (Windows only) | `desktop/control/*.py` |
| Keyboard/mouse synthetic input | Implemented, always confirmed | `desktop/control/automation.py`; refused when no confirm callback (voice) |
| File operations | Implemented | `files/executor.py`; `file_delete` HIGH |
| Process kill | Implemented, HIGH, confirmed | `apps/process_kill.py` (PR #23) |
| Visible-browser control | Partial | `browser_control.py`, `browser/`; no hidden/headless sessions by design; form fill/download excluded as stubs (`catalogue.EXCLUSIONS`) |
| Screen capture, OCR, describe | Implemented | `screen/`, Tesseract via `pytesseract`; `grandpa screen describe` uses grandpa-eyes |
| Read window text / press named button (UIA) | Implemented | `screen/window_text.py`, `screen/window_click.py` (PRs #43, #44) |
| Screen privacy list | Implemented | `screen/privacy.py`, `~/.grandpa/screen-private.txt` |
| Push-to-talk voice | Implemented | `voice/push_to_talk.py`, default chord Ctrl+Win |
| Hands-free VAD voice | Partial | `voice/vad.py`; README documents threshold problems; push-to-talk recommended |
| "Hey Grandpa" wake word | Implemented, needs a trained `.onnx` | `voice/wake_engine.py`, `voice/hands_free.py`; `grandpa wake setup` |
| Local STT | Implemented | `speech/faster_whisper.py` (only registered STT backend; config comment lists openai/deepgram but none exist) |
| TTS | Implemented | default `pyttsx3` (SAPI); registry backends `piper`, `mms_tamil`, `kokoro`, `grandpa_voice` (F5 service), `elevenlabs` (cloud, opt-in) |
| Own cloned voice training | Experimental | `notebooks/grandpa_voice_piper.ipynb`, `voice_runtime/`, Colab-based |
| Desktop bubble / 3D avatar | Implemented | `ui/bubble.py`, `ui/tk_view.py`, `cli/avatar_cmd.py` (pywebview, Windows) |
| Odin model roles | Implemented | `intelligence/odin_registry.py`, `models/Modelfile.*`, `grandpa models roles/setup/eval` |
| Odin-1 LoRA fine-tune | Experimental | `scripts/odin/make_dataset.py`, `notebooks/odin_brain_lora.ipynb` |
| Safety classifier model (grandpa-guard) | Planned in practice | role registered in `odin_registry.py`; no action path calls it |
| Personal memory (facts, activity) | Implemented | `memory_context.py` (`personal_memory.db`), Ollama embeddings with hashed fallback |
| Memory V1 store / retrieval | Implemented, parallel system | `memory/` (`memory.db`) |
| Document RAG / knowledge | Partial | `knowledge/`, `connectors/`, `tools/storage/sqlite.py` also writes `memory.db` |
| Reminders | Implemented | `reminders.py`, `grandpa reminders add --in 10m`; delivery needs `reminders watch` or `scheduler.enabled` |
| Routines / scheduled tasks | Implemented | `task_scheduler.py`, `scheduler/`, `scheduler_daemon.py` |
| YAML workflows + triggers | Implemented | `workflow/loader.py` (`load_yaml_workflow`), `workflow/triggers.py` |
| Plugins | Implemented | `plugins/host.py`, `plugins/manifest.py` |
| External MCP servers (stdio) | Implemented | `mcp/servers.py`; MCP server side also exists (inherited) |
| Gmail / Google Calendar | Implemented, optional extra | `gmail/`, `calendar/`; needs `--extra gmail/calendar` and OAuth |
| Web search | Implemented | `web_search/` (ddgs default) |
| Local API server | Implemented | `server/`, API key by default, `grandpa serve` |
| Phone pairing + remote commands | Implemented | `devices/` (D1–D4) |
| Home-server node (Raspberry Pi "Pironman") | Implemented | `server/headless.py`, `docker/headless.Dockerfile` |
| Encrypted credentials | Implemented | `security/secret_store.py` (DPAPI / keyring / 0600 file fallback) |
| Prompt-injection scanning | Orphaned | `security/injection_scanner.py` only referenced by `_rust_bridge.py` |
| Autonomous agents / planning | Partial | `agents/`, `agent/`, `planner/`; CAPABILITY-MAP rates goal understanding BROKEN |
| Rust acceleration | Optional, inherited | `rust/`; every caller has a Python fallback (PR #59) |
| Voice identity / speaker verification | Missing (and must not be used as auth) | none |
| Hardware / IoT / home automation | Planned | no MQTT, Home Assistant, or device-control code |
| Robotics | Planned | none |
