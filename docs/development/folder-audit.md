# Support Folder Audit

This audit covers non-runtime support folders requested for Phase 3.

| Folder | Purpose | Used by | Risk | Cleanup Recommendation |
| --- | --- | --- | --- | --- |
| `examples/` | Runnable examples and demos for browser assistant, code companion, daily digest, deep research, document QA, messaging, routing, scheduled ops, security scanning, and social bot flows. | Users, documentation, manual testing, possible future smoke checks. | Medium | Keep. Add a top-level `examples/README.md` later if discoverability becomes a problem. Do not move example code without checking docs and tutorial links. |
| `deploy/` | Docker, GPU Docker, systemd, launchd, and PostHog deployment assets. | Deployment docs, self-hosting users, release validation. | Medium | Keep. Consider adding `deploy/README.md` later. Avoid moving because deployment docs and automation may reference paths. |
| `tools/` | Supporting reference tools outside the main Python package. Currently contains the Pearl reference oracle. | Developers validating Pearl/reference behavior. | Low | Keep. The folder is small and already scoped. |
| `configs/` | Default and example Grandpa configuration, persona prompts, and workflow examples. | Local setup, docs, runtime configuration examples. | Medium | Keep. Review whether tracked `configs/grandpa/config.backup.toml` is intentional before any future cleanup. |
| `plugins/` | Built-in and user plugin manifest locations. | Plugin loader and local plugin discovery conventions. | Medium | Keep untouched unless plugin loading paths are audited. |

## Additional Observations

- `configs/grandpa/config.backup.toml` is tracked despite looking like a backup
  file. It does not match the Phase-3 stale-file extension scan, but it should
  be reviewed before future cleanup.
- `examples/twitter_bot/test_*.py` are examples, not part of the configured
  pytest `testpaths`, but their names may still confuse readers.
