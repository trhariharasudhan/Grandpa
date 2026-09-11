# Deferred: kept deliberately

Code and config that nothing uses today but that was kept on purpose during the
dead-code removal, with the reason. Anything here is a decision still to make,
not dead code to delete blindly.

| Item | State | Why it was kept |
|---|---|---|
| `src/grandpa/security/subprocess_sandbox.py` | Unused; nothing imports it | A runner with an allowlisted environment, a timeout and process-tree cleanup, written to back `shell_exec`. It was never wired up: `shell_exec` and `code_interpreter` still call `subprocess.run` directly. |
| `intelligence.top_p`, `intelligence.repetition_penalty` (`core/config.py`) | Declared, never sent to Ollama | Sampling knobs a user reasonably expects to work. Wiring them is pending a decision; note `repetition_penalty` defaults to 1.0 while the Ollama adapter sends `repeat_penalty` 1.08. |
| `grandpa_voice.character_voice` (`core/config.py`) | In use | Listed as dead in audit finding 26, but `voice_runtime/scripts/run_service.py` reads it. The audit scanned only `src/`. |
| `EventType.A2A_TASK_RECEIVED`, `EventType.A2A_TASK_COMPLETED` (`core/events.py`) | Unused since the a2a package was removed | Left in place to avoid changing the public `EventType` enum inside a deletion batch. |
