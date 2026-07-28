# Grandpa Test Classification

Grandpa uses pytest markers to keep the full suite honest while separating
daily release blockers from tests that need live devices, credentials, or
platform-specific runtimes.

## Markers

- `core`: deterministic local tests expected to pass in normal development.
- `release`: curated release-blocking tests used by the final release gate.
- `integration`: cross-module tests.
- `optional`: tests that require opt-in dependencies, credentials, or live services.
- `environment`: tests tied to a browser, microphone, optional Rust extension,
  or another Windows environment backend.
- `slow`: intentionally long-running tests.

## Commands

Release-grade suite:

```powershell
uv run --python 3.11 python scripts\testing\test_suite_report.py --release-only
```

Writes `runtime/reports/test-suite-release-report.json` and `.md`.

Full suite report:

```powershell
uv run --python 3.11 python scripts\testing\test_suite_report.py --full
```

Writes `runtime/reports/test-suite-full-report.json` and `.md`.
The legacy `runtime/reports/test-suite-report.json` points to the most recent
test-suite report of either type.

Raw full pytest:

```powershell
uv run python -m pytest tests
```

Optional live tests remain opt-in through environment variables such as
`GRANDPA_RUN_LIVE_CONNECTOR_TESTS=1`, `GRANDPA_RUN_LIVE_SKILL_TESTS=1`,
`GRANDPA_RUN_EXTERNAL_RUNNER_TESTS=1`, and `GRANDPA_RUN_HF_DATASET_TESTS=1`.
