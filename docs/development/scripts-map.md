# Scripts Map

## Development

- `scripts/index_docs.py`: local documentation indexing.
- `scripts/oauth_all.py`: optional Gmail and Calendar OAuth setup.
- `scripts/production_audit.py`: focused local production audit.
- `scripts/validate_daily_use.py`: non-destructive daily-use validation.
- `scripts/burnin_daily_use.py`: local stability burn-in.
- `scripts/dev/`: targeted maintenance and desktop diagnostics.

## Testing

- `scripts/testing/test_suite_report.py`: local test result reporting.

## Release

- `scripts/release/final_release_gate.py`: Python release gate.
- `scripts/release/final-release-gate.ps1`: Windows release wrapper.

Grandpa uses the documented `uv` setup on Windows. Retired Unix installers,
remote deployment assets, and research tooling are not part of the supported
product.
