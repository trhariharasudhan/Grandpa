# Grandpa Feature Audit

This audit is generated from repository evidence and is intended to keep GrandpaAssistant original, local-first, and Windows-focused.

## Identity Hygiene

- Active forbidden branding references: 0
- Generated lockfile legacy identity references: 58
- Lockfile entries are generated artifacts; update them only through the relevant package manager/build tool.

## Feature Status Summary

| Feature Area | Status | Completion | Priority | Evidence Count |
| --- | --- | ---: | --- | ---: |
| Core AI Brain | PARTIAL | 78% | P0 | 7 |
| Voice Assistant | PARTIAL | 62% | P1 | 5 |
| PC Control | COMPLETE | 100% | P0 | 10 |
| Browser Control | PARTIAL | 42% | P1 | 3 |
| Mobile Integration | PARTIAL | 84% | P1 | 11 |
| File & Document Intelligence | PARTIAL | 66% | P1 | 4 |
| Office Productivity | MISSING | 12% | P2 | 2 |
| Smart Automation | PARTIAL | 71% | P0 | 5 |
| Screen Awareness | PARTIAL | 58% | P1 | 3 |
| Real World Task Assistance | PARTIAL | 35% | P2 | 4 |
| Chat App Integration | PARTIAL | 46% | P2 | 5 |
| Developer Features | PARTIAL | 69% | P1 | 6 |
| Advanced AI Features | PARTIAL | 53% | P2 | 5 |
| Security & Safety | PARTIAL | 76% | P0 | 5 |
| IoT / Smart Home | MISSING | 5% | P3 | 1 |
| Future-Level Features | MISSING | 18% | P3 | 3 |

## Capability Details

### Core AI Brain

- Current Status: PARTIAL
- Current Level: 78%
- Priority: P0
- Current Evidence:
  - `src/grandpa/cli/ask.py`
  - `src/grandpa/cli/chat_cmd.py`
  - `src/grandpa/engine/ollama.py`
  - `src/grandpa/engine/multi.py`
  - `src/grandpa/server/routes.py`
  - `src/grandpa/agents/_stubs.py`
  - `src/grandpa/response_cleanup.py`
- Missing Pieces:
  - Unified deterministic routing helper shared by CLI, API, and frontend.
  - More model-specific prompt/response conformance tests.
  - Streaming cleanup for untagged reasoning leaks.
- Implementation Plan:
  - Extract deterministic command routing into one service.
  - Add response-quality regression fixtures for local models.
  - Add streaming guardrail tests at API level.
- Tests Needed:
  - CLI ask smoke tests.
  - API chat completion route tests.
  - Ollama payload and response cleanup tests.

### Voice Assistant

- Current Status: PARTIAL
- Current Level: 62%
- Priority: P1
- Current Evidence:
  - `frontend/src/hooks/useSpeech.ts`
  - `frontend/src/hooks/useWakeWord.ts`
  - `frontend/src/components/Chat/MicButton.tsx`
  - `frontend/src/components/Chat/InputArea.tsx`
  - `src/grandpa/speech`
- Missing Pieces:
  - Automated browser permission and SpeechRecognition tests.
  - Backend STT/TTS provider setup validation.
  - Wake-word reliability metrics.
- Implementation Plan:
  - Add Playwright coverage for mic states where browser APIs are mocked.
  - Add speech health details to Settings.
  - Add explicit voice troubleshooting panel.
- Tests Needed:
  - Frontend build.
  - Mocked SpeechRecognition unit tests.
  - Manual Chrome/Edge microphone permission test.

### PC Control

- Current Status: COMPLETE
- Current Level: 100%
- Priority: P0
- Current Evidence:
  - `src/grandpa/pc_control.py`
  - `src/grandpa/local_actions.py`
  - `src/grandpa/windows_app_resolver.py`
  - `src/grandpa/windows_window_control.py`
  - `src/grandpa/desktop_automation.py`
  - `tests/test_local_actions.py`
  - `tests/test_windows_window_control.py`
  - `tests/test_windows_app_resolver.py`
  - `tests/test_pc_control.py`
  - `tests/test_pc_control_api.py`
- Missing Pieces:
  - None for the backend safety contract.
  - Brightness, keyboard, mouse, and power actions remain truthfully unsupported when OS dependencies are unavailable.
  - Live Windows runner validation is still useful for hardware-specific behavior.
- Implementation Plan:
  - Connect the structured local-action endpoint to a reusable frontend action console.
  - Add live local-action activity feed.
  - Add pywin32-specific focus/minimize coverage on a Windows runner.
- Tests Needed:
  - Structured PC control unit tests.
  - Approval, rejection, emergency-stop, and audit-log tests.
  - FastAPI /api/local-action response schema tests.

### Browser Control

- Current Status: PARTIAL
- Current Level: 42%
- Priority: P1
- Current Evidence:
  - `src/grandpa/local_actions.py`
  - `src/grandpa/screen_awareness.py`
  - `frontend/src/components/Chat/InputArea.tsx`
- Missing Pieces:
  - Browser DOM/page extraction layer.
  - Current tab title/content integration.
  - Safe browser automation permission model beyond URL/search actions.
- Implementation Plan:
  - Add browser page summary endpoint using accessible text only.
  - Add tab/window detection for supported browsers.
  - Create browser-control safety policy tests.
- Tests Needed:
  - Open/search URL parser tests.
  - Blocked purchase/payment browser action tests.
  - Manual browser search smoke test.

### Mobile Integration

- Current Status: PARTIAL
- Current Level: 84%
- Priority: P1
- Current Evidence:
  - `src/grandpa/mobile_integration.py`
  - `src/grandpa/server/routes.py`
  - `frontend/src/pages/MobileCompanionPage.tsx`
  - `frontend/src/lib/api.ts`
  - `mobile/android_companion/pubspec.yaml`
  - `mobile/android_companion/lib/main.dart`
  - `mobile/android_companion/android/app/src/main/AndroidManifest.xml`
  - `mobile/android_companion/android/app/src/main/kotlin/com/grandpa/companion/GrandpaNotificationListenerService.kt`
  - `mobile/android_companion/android/app/src/main/kotlin/com/grandpa/companion/MainActivity.kt`
  - `tests/test_mobile_companion.py`
  - `tests/test_integration_foundations.py`
- Missing Pieces:
  - Physical Android-device validation for notification listener behavior.
  - Physical Android-device validation for microphone relay quality.
  - Flutter SDK build validation on a machine where the SDK cache is writable.
- Implementation Plan:
  - Test APK on a real Android phone and verify notification-listener consent flow.
  - Tune microphone relay latency and reconnect behavior on real Wi-Fi.
  - Move Flutter SDK to a user-writable location or fix cache permissions for CI builds.
- Tests Needed:
  - Flutter widget tests for pairing and reconnect states.
  - Android instrumentation tests for notification permission flow.
  - Backend WebSocket reconnect and malformed-event tests.

### File & Document Intelligence

- Current Status: PARTIAL
- Current Level: 66%
- Priority: P1
- Current Evidence:
  - `src/grandpa/file_assistant.py`
  - `frontend/src/pages/FileAssistantPage.tsx`
  - `tests/test_file_assistant.py`
  - `src/grandpa/tools/storage`
- Missing Pieces:
  - Robust PDF/document extraction test fixtures.
  - Semantic document search.
  - Safe edit/overwrite approval workflow.
- Implementation Plan:
  - Add fixture-based txt/md/pdf summarization tests.
  - Add local vector index for document chunks.
  - Add safe note editing with confirmation.
- Tests Needed:
  - File assistant CLI command tests.
  - Recent file tracking tests.
  - Document extraction tests.

### Office Productivity

- Current Status: MISSING
- Current Level: 12%
- Priority: P2
- Current Evidence:
  - `src/grandpa/file_assistant.py`
  - `docs/development/advanced-feature-backlog.md`
- Missing Pieces:
  - Word/Excel/PowerPoint automation.
  - Calendar and email drafting workflows.
  - Office document creation/editing UI.
- Implementation Plan:
  - Define local document generation boundaries.
  - Add safe export workflows for notes and reports.
  - Plan optional Microsoft/Google integrations.
- Tests Needed:
  - Document generation fixture tests.
  - Permission tests for external account integrations.

### Smart Automation

- Current Status: PARTIAL
- Current Level: 71%
- Priority: P0
- Current Evidence:
  - `src/grandpa/task_scheduler.py`
  - `src/grandpa/scheduler_daemon.py`
  - `frontend/src/pages/RoutinesPage.tsx`
  - `tests/test_task_scheduler.py`
  - `tests/test_scheduler_daemon.py`
- Missing Pieces:
  - Frontend creation/editing flows for routines.
  - Full approval lifecycle display for scheduled risky actions.
  - Long-running daemon resilience tests.
- Implementation Plan:
  - Add routine creation UI.
  - Add scheduler daemon heartbeat to HUD.
  - Add missed-run recovery policy.
- Tests Needed:
  - Routine parser tests.
  - Daemon due-item tests.
  - Approval-required scheduled action tests.

### Screen Awareness

- Current Status: PARTIAL
- Current Level: 58%
- Priority: P1
- Current Evidence:
  - `src/grandpa/screen_awareness.py`
  - `frontend/src/components/Chat/InputArea.tsx`
  - `src/grandpa/cli/doctor_cmd.py`
- Missing Pieces:
  - Reliable OCR setup flow for Tesseract.
  - Visual target detection/click planning.
  - Privacy controls for screenshot retention.
- Implementation Plan:
  - Add screen-awareness settings and diagnostics.
  - Add OCR fixture tests.
  - Add explicit no-upload privacy audit.
- Tests Needed:
  - Unsupported-platform tests.
  - Screenshot backend detection tests.
  - OCR optional dependency tests.

### Real World Task Assistance

- Current Status: PARTIAL
- Current Level: 35%
- Priority: P2
- Current Evidence:
  - `src/grandpa/memory_context.py`
  - `src/grandpa/task_scheduler.py`
  - `src/grandpa/channels`
  - `docs/user-guide/morning-digest.md`
- Missing Pieces:
  - End-to-end task planning with confirmations.
  - Calendar/email/reminder ecosystem integrations.
  - Multi-step execution review UI.
- Implementation Plan:
  - Create task plan object model.
  - Add approval checkpoints for multi-step tasks.
  - Add daily agenda workflow.
- Tests Needed:
  - Task decomposition tests.
  - Approval checkpoint tests.
  - Failure recovery tests.

### Chat App Integration

- Current Status: PARTIAL
- Current Level: 46%
- Priority: P2
- Current Evidence:
  - `src/grandpa/channels`
  - `src/grandpa/connectors`
  - `src/grandpa/server/channel_bridge.py`
  - `docs/tutorials/messaging-hub.md`
  - `tests/channels`
- Missing Pieces:
  - WhatsApp and Telegram daily-use setup flow.
  - Unified message permission model.
  - Frontend channel diagnostics.
- Implementation Plan:
  - Audit channel route coverage.
  - Add Telegram/WhatsApp integration plan.
  - Add inbound/outbound message approval UI.
- Tests Needed:
  - Gateway route tests.
  - Connector auth failure tests.
  - Message safety tests.

### Developer Features

- Current Status: PARTIAL
- Current Level: 69%
- Priority: P1
- Current Evidence:
  - `src/grandpa/cli`
  - `src/grandpa/sdk.py`
  - `src/grandpa/mcp`
  - `src/grandpa/workflow`
  - `tests/daemon`
  - `tests/a2a`
- Missing Pieces:
  - Stable plugin developer guide.
  - End-to-end workflow authoring UI.
  - Public API compatibility matrix.
- Implementation Plan:
  - Document CLI/API extension points.
  - Add workflow fixture examples.
  - Add SDK smoke tests to daily validation.
- Tests Needed:
  - CLI command tests.
  - SDK import tests.
  - MCP/gateway tests.

### Advanced AI Features

- Current Status: PARTIAL
- Current Level: 53%
- Priority: P2
- Current Evidence:
  - `src/grandpa/agents`
  - `src/grandpa/learning`
  - `src/grandpa/intelligence`
  - `src/grandpa/operators`
  - `src/grandpa/evals`
- Missing Pieces:
  - Production semantic vector memory.
  - Robust multi-agent orchestration UI.
  - Vision planning for screen targeting.
- Implementation Plan:
  - Prioritize semantic memory architecture.
  - Add agent orchestration dashboard tests.
  - Add eval pack for local assistant tasks.
- Tests Needed:
  - Agent unit tests.
  - Learning/routing tests.
  - Evaluation smoke tests.

### Security & Safety

- Current Status: PARTIAL
- Current Level: 76%
- Priority: P0
- Current Evidence:
  - `src/grandpa/security`
  - `src/grandpa/local_action_approvals.py`
  - `src/grandpa/local_actions.py`
  - `frontend/src/components/Chat/MessageBubble.tsx`
  - `tests/test_local_actions.py`
- Missing Pieces:
  - Central policy viewer in frontend.
  - Complete audit log review UI.
  - Formal threat model for desktop automation.
- Implementation Plan:
  - Add Safety page or panel.
  - Add local action audit export.
  - Write desktop automation threat model.
- Tests Needed:
  - Blocked command tests.
  - Approval expiry tests.
  - Security middleware tests.

### IoT / Smart Home

- Current Status: MISSING
- Current Level: 5%
- Priority: P3
- Current Evidence:
  - `docs/development/advanced-feature-backlog.md`
- Missing Pieces:
  - Home Assistant/Matter integration.
  - Device discovery.
  - Local network permissions and safety controls.
- Implementation Plan:
  - Create IoT integration design doc.
  - Define allowlisted smart-home actions.
  - Plan Home Assistant connector.
- Tests Needed:
  - Future mocked device connector tests.
  - Permission and safety tests.

### Future-Level Features

- Current Status: MISSING
- Current Level: 18%
- Priority: P3
- Current Evidence:
  - `docs/development/advanced-feature-backlog.md`
  - `src/grandpa/operators`
  - `src/grandpa/learning`
- Missing Pieces:
  - Plugin marketplace.
  - Offline wake-word engine.
  - Full RAG and vision targeting.
  - Installer/autostart service hardening.
- Implementation Plan:
  - Keep backlog scoped behind stable daily-use milestones.
  - Choose one advanced feature only after P0 features are stable.
  - Add feature flags for experimental modules.
- Tests Needed:
  - Feature flag tests.
  - Experimental module import tests.

## Safe Migration Notes

- Do not rename `src/grandpa` or `frontend` without updating imports, build configuration, Docker packaging, and tests.
- Do not hand-edit Cargo or uv lockfiles; regenerate them through their package managers if stale generated names need to be refreshed.
- Treat desktop automation, browser control, file operations, and scheduled routines as safety-gated features.
