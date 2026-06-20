# Duplicate Documentation Report

This report identifies documentation that overlaps in purpose or exists as a
compatibility duplicate after recent cleanup.

| Old Path | New Preferred Path | Risk | Notes |
| --- | --- | --- | --- |
| `MODEL_NAMES.md` | `docs/development/model-names.md` | Low | Root file is now a redirect stub. Keep temporarily for compatibility. |
| `REVIEW.md` | `docs/development/pr-review-guidelines.md` | Medium | Historical design docs still mention `REVIEW.md`; keep stub until references are intentionally updated. |
| `docs/getting-started/install.md` | `docs/getting-started/installation.md` as canonical entry point | Medium | `install.md` explains installer internals; `installation.md` is broader user setup. Keep both but clarify linking. |
| `docs/user-guide/channels.md` | `docs/user-guide/channels-and-connectors.md` as overview | Medium | `channels.md` is detailed channel usage; `channels-and-connectors.md` is broader integration overview. Keep both with cross-links. |
| `docs/GRANDPA_FEATURE_AUDIT.md` | Generated from `scripts/dev/audit_grandpa_features.py` | Low | Not a duplicate, but generated. Keep path stable because the generator writes it. |
| `docs/GRANDPA_FEATURE_TRACKER.json` | Generated from `scripts/dev/audit_grandpa_features.py` | Low | Not a duplicate, but generated. Keep path stable because the generator writes it. |

## README Density

Several folders contain useful local READMEs:

- `examples/*/README.md`
- `models/README.md`
- `scripts/README.md`
- `scripts/pearl/README.md`
- `tools/pearl-reference-oracle/README.md`

These are not duplicates. They provide local context and should remain near
their folders.
