# Advanced Feature Backlog

This backlog is intentionally not an implementation plan for the current
stabilization phase. These items should wait until Grandpa's daily-use runtime,
tests, packaging, and Windows desktop behavior are consistently reliable.

## Candidate Future Features

| Feature | Goal | Stabilization Gate |
| --- | --- | --- |
| Semantic vector memory | Recall preferences, documents, and project context with embeddings. | Memory DB migrations and privacy controls are tested. |
| Browser DOM control | Interact with visible web pages using safe DOM-level actions. | Approval system supports per-site permissions and clear audit logs. |
| Plugin marketplace | Discover and install assistant extensions. | Plugin sandboxing, signing, and rollback are designed. |
| WhatsApp/Telegram integration | Send and receive assistant messages through personal channels. | Secrets handling and notification routing are hardened. |
| Multi-agent orchestration | Coordinate specialist agents for research, coding, and routines. | Agent lifecycle, trace logs, and cancellation are stable. |
| Offline wake-word engine | Detect "Hey Grandpa" without browser/cloud speech APIs. | Local audio permissions and CPU usage are measurable. |
| Full RAG | Index local documents and answer with citations. | File safety rules, indexing limits, and document permissions are clear. |
| Vision targeting/click planning | Use screen understanding to click visible UI elements. | Screenshot/OCR/automation safety has confirmation and emergency stop flows. |
| Installer/auto-start service | Install Grandpa as a Windows desktop service/app. | Doctor, daily validation, and upgrade rollback are reliable. |

## Non-Negotiables Before Starting

- Keep dangerous actions blocked by default.
- Keep all memory and screen data local unless the user explicitly opts in.
- Keep Docker/Linux behavior graceful when Windows-only features are unavailable.
- Require focused tests for every new permission tier or automation path.
- Keep `uv run grandpa doctor` and `scripts/validate_daily_use.py` green.
