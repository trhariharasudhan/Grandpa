# Final Release Gate

Run the Python and CLI release-readiness gate:

```powershell
uv run python scripts\release\final_release_gate.py
```

or:

```powershell
scripts\release\final-release-gate.ps1
```

The gate checks dependency synchronization, doctor output, daily-use
validation, release-grade tests, generated artifacts, and release manifests.
Reports are written under `runtime/reports/`.

The gate does not package a graphical client or mobile application.
