# Scripts Map

This map classifies tracked scripts by intended use.

## Development

- `scripts/dev/audit_grandpa_features.py`
- `scripts/index_docs.py`
- `scripts/oauth_all.py`
- `scripts/production_audit.py`
- `scripts/quickstart.sh`
- `scripts/smoke_framework_comparison.sh`
- `scripts/validate_daily_use.py`
- `scripts/burnin_daily_use.py`

## Desktop

- `scripts/dev/desktop/tauri-floating-debug-hold.ps1`
- `scripts/dev/desktop/tauri-floating-normal-window.ps1`
- `scripts/dev/desktop/tauri-floating-render-proof.ps1`
- `scripts/dev/desktop/tauri-floating-topmost.ps1`
- `scripts/dev/desktop/tauri-floating-visibility.ps1`
- `scripts/bump-desktop-version.sh`

## Install

- `scripts/install/bg-orchestrator.sh`
- `scripts/install/build-extension.sh`
- `scripts/install/grandpa-uninstall.sh`
- `scripts/install/grandpa-wrapper.sh`
- `scripts/install/install-rust.sh`
- `scripts/install/install.sh`
- `scripts/install/pull-model.sh`

## Release

- `scripts/release/final_release_gate.py`
- `scripts/release/final-release-gate.ps1`

## Testing

- `scripts/testing/test_suite_report.py`

## Domain-Specific

- `scripts/mining/pearl_model_converter.py`
- `scripts/pearl/model_converter.py`

## Missing or Thin Folders

- `scripts/dev/desktop/` exists and contains desktop diagnostics.
- `scripts/testing/` exists but currently contains only one tracked report
  helper.
- `scripts/release/` exists and contains the release gate helpers.
- `scripts/install/` exists and contains setup helpers.
- There is no separate `scripts/deploy/`; deployment assets live under
  `deploy/`.
- There is no separate `scripts/docs/`; documentation helpers currently live at
  `scripts/index_docs.py` and `docs/gen_ref_pages.py`.
