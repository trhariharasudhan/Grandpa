# Final Release Gate

Grandpa's final release gate answers one question: is the current checkout ready for daily use, packaging, commit, and push?

Run the full gate:

```powershell
.\scripts\release\final-release-gate.ps1
```

Run a faster daily gate that skips optional Android packaging:

```powershell
.\scripts\release\final-release-gate.ps1 -Quick
```

The gate writes:

- `runtime/reports/final-release-gate.json`
- `runtime/reports/final-release-gate.md`

## What It Checks

- Git status summary
- Tracked generated/runtime artifact hygiene
- `uv sync --extra server --link-mode=copy`
- `grandpa doctor`
- Daily-use validator
- Release-grade pytest suite (`scripts\testing\test_suite_report.py --release-only`)
- Latest dedicated full-suite pytest report, if available:
  `runtime/reports/test-suite-full-report.json`
- Frontend build
- Tauri frontend build
- Optional Android APK build when Flutter is available
- Release manifest sanity when release artifacts exist

## Warning Classes

The gate treats these as non-blocking unless the related artifact is required for a specific release:

- Docker daemon off
- Browser microphone permission not testable from CLI
- Vite chunk-size warning
- Flutter or Android environment issue
- Optional cloud/local engines unavailable while the default engine works

## Interpreting Results

- `READY`: no blocking failures. Review warnings and commit intentional changes before pushing.
- `BLOCKED`: at least one required check failed. Do not package or push a release until fixed.
- `skipped_optional`: optional checks were intentionally skipped or unavailable.

Use the frontend `/release-gate` dashboard or API endpoints to inspect the latest report.

To refresh the full-suite status shown by the gate:

```powershell
uv run --python 3.11 python scripts\testing\test_suite_report.py --full
```

The release-grade pytest check writes its own
`runtime/reports/test-suite-release-report.json`, so it does not overwrite the
full-suite status consumed by the gate.
