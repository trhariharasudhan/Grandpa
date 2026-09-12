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

## Debt: the ddgs whitespace patch

`src/grandpa/web_search/duckduckgo.py` replaces two methods of the third-party
`ddgs` package (`BaseSearchEngine.extract_tree` and `.extract_results`) at
runtime. This is deliberate debt, recorded here so it is removed rather than
forgotten.

- **Why.** In `ddgs` 9.11.4 (`ddgs/base.py`), result pages are parsed with
  `remove_blank_text=True`, which drops the whitespace-only text between tags,
  and `extract_results` then strips each text node and joins them with `""`.
  Search engines wrap query words in tags, so `the <b>Python</b>
  <b>Packaging</b>` arrives as `thePythonPackaging`. The spaces are gone before
  Grandpa sees the text, so no amount of downstream fixing can restore them.
- **Watch upstream.** <https://github.com/deedy5/ddgs> — issues and releases
  after 9.11.4. There is no Grandpa-filed issue yet; file one if this persists.
- **Remove it when** a `ddgs` release keeps the whitespace. The check is already
  written: `tests/test_web_search_duckduckgo.py::test_search_results_keep_the_spaces_around_highlighted_words`
  feeds a known result page through ddgs' own Bing engine and **skips with
  "ddgs keeps whitespace itself now; remove the duckduckgo.py shim"** once the
  unpatched output is correct. Delete `_keep_whitespace_between_tags` and its
  call, then that test's first assertion.
- **If ddgs changes those methods** (renames, different signature, another
  package patching them first), the shim does not apply itself. It logs a
  `WARNING` and emits a `RuntimeWarning` naming the problem, so the degradation
  is visible instead of silent; results may be glued again until the shim is
  updated.
