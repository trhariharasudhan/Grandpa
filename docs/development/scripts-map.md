# Scripts Map

## Development

- `scripts/index_docs.py`
- `scripts/oauth_all.py`
- `scripts/production_audit.py`
- `scripts/quickstart.sh`
- `scripts/smoke_framework_comparison.sh`
- `scripts/validate_daily_use.py`
- `scripts/burnin_daily_use.py`

## Install

- `scripts/install/bg-orchestrator.sh`
- `scripts/install/build-extension.sh` builds the retained native Python
  extension, not a browser extension.
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

There is no UI or mobile packaging stage. Release validation covers the Python
package, CLI, local API, tests, and retained native workspace.
