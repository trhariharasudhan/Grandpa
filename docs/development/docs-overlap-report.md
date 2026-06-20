# Documentation Overlap Report

This report audits selected documentation pairs for overlap and cleanup risk.
It does not modify the audited files.

## Installation Docs

Audited files:

- `docs/getting-started/install.md`
- `docs/getting-started/installation.md`

### Duplicate Sections

- Both files use the title "Installation".
- Both describe initial setup for running grandpa locally.
- Both mention the quickstart or install flow and backend setup expectations.

### Audience Differences

- `install.md` is focused on the one-line installer and what that installer
  does step by step.
- `installation.md` is a broader user-facing setup guide covering browser,
  desktop, CLI, and Python SDK entry points.

### Recommendation

Keep both for now, but make `installation.md` the canonical user-facing entry
point and link from it to `install.md` as the installer internals reference.
Avoid deleting either page until MkDocs navigation and inbound links are
checked.

### Consolidation Risk

Medium. `mkdocs.yml` uses `getting-started/installation.md` in navigation, and
platform-specific docs link to `install.md`. A direct merge could break links or
remove useful installer implementation detail.

## Channels Docs

Audited files:

- `docs/user-guide/channels.md`
- `docs/user-guide/channels-and-connectors.md`

### Duplicate Sections

- Both explain messaging channels.
- Both discuss external communication surfaces such as Slack, SMS/iMessage, or
  other integrations.
- Both are user-guide level docs rather than internal architecture docs.

### Audience Differences

- `channels.md` is a deeper channels-module guide. It describes channel
  implementation concepts such as `BaseChannel`, registry behavior, supported
  channel types, and operational setup.
- `channels-and-connectors.md` is a broader integration overview. It contrasts
  data connectors with messaging channels and gives product-level setup
  guidance.

### Recommendation

Keep both, but clarify the split: `channels-and-connectors.md` should be the
overview and decision guide, while `channels.md` should be the detailed channel
operation guide. Cross-link the two in a later docs pass.

### Consolidation Risk

Medium. The files overlap in topic but not fully in intent. A premature merge
could make the integration overview too long or hide channel-specific operational
details.
