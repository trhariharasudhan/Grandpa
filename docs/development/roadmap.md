# Roadmap

Grandpa is focused on one product direction: a reliable, private, local Windows
assistant controlled by voice and command-line input.

## Priorities

1. Reliable voice-command pipeline
2. Accurate intent parsing
3. Windows application control
4. Screen understanding
5. Mouse and keyboard automation
6. File and folder management
7. Safe system operations
8. Context-aware multi-step automation
9. Local AI performance improvements
10. Voice feedback and error recovery
11. Permission controls and audit logs
12. Comprehensive Windows regression testing

## Engineering Principles

- Local inference and local data by default
- Typed actions instead of arbitrary shell execution
- Explicit confirmation for destructive or sensitive actions
- Short, testable adapters around Windows APIs
- No dependency on a bundled graphical client
- Graceful behavior when optional speech, OCR, or server dependencies are absent
- Regression tests for stale PIDs, device changes, protected paths, and
  unavailable applications
