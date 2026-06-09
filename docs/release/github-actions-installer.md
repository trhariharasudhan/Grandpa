# GitHub Actions Windows Installer

Grandpa can build Windows desktop installer artifacts in GitHub Actions when
local Windows policy blocks Cargo/Tauri build scripts. This keeps Smart App
Control and Code Integrity enabled locally while using GitHub's clean
`windows-latest` runner to produce unsigned installer bundles.

## Workflow

Workflow file:

```text
.github/workflows/windows-installer.yml
```

Runner:

```text
windows-latest
```

The workflow performs:

1. Checkout repository.
2. Setup Node.js 22.
3. Setup Rust stable MSVC.
4. Cache npm, Cargo registry, Cargo git, and Tauri target output.
5. Run `npm ci` in `frontend/`.
6. Run `npm run build` in `frontend/`.
7. Run `npx tauri build` in `frontend/`.
8. Upload `frontend/src-tauri/target/release/bundle/**/*` as an artifact.
9. Upload failure logs if the Tauri build fails.

The CI build disables Tauri updater artifact generation with a temporary
command-line config override. This avoids requiring signing secrets for an
unsigned installer build.

## Run Manually

1. Open the GitHub repository.
2. Go to **Actions**.
3. Select **Windows Installer**.
4. Click **Run workflow**.
5. Choose the branch, usually `main`.
6. Wait for the `Build Windows installer` job.

Artifacts appear at the bottom of the workflow run under:

```text
grandpa-windows-installer-<commit-sha>
```

Expected installer bundle source path inside the runner:

```text
frontend/src-tauri/target/release/bundle/
```

Common outputs, depending on Tauri bundler configuration:

```text
frontend/src-tauri/target/release/bundle/msi/*.msi
frontend/src-tauri/target/release/bundle/nsis/*.exe
```

## Build From a Tag

Tag pushes matching `v*` also run the workflow.

```powershell
git tag v1.0.1
git push origin v1.0.1
```

When the workflow runs from a `v*` tag, it uploads matching `.msi` and `.exe`
bundle files to the GitHub Release using the default `GITHUB_TOKEN`. No custom
secrets are required for unsigned builds.

## Troubleshooting

If `npm ci` fails:

- Confirm `frontend/package-lock.json` is committed.
- Re-run `npm install` locally only when dependencies intentionally changed.

If `cargo metadata` fails:

- Confirm Rust stable MSVC is installed by the workflow setup step.
- Check the uploaded `grandpa-windows-installer-logs-*` artifact.

If the Tauri build fails because signing keys are missing:

- The Windows installer workflow intentionally disables updater artifacts for
  unsigned CI builds.
- Code signing and updater signing should be added later as a separate release
  hardening phase.

If no MSI or EXE appears:

- Check whether Tauri emitted a different bundle target under
  `frontend/src-tauri/target/release/bundle/`.
- Open the uploaded artifact and inspect subfolders such as `msi/`, `nsis/`,
  and `updater/`.

## Local Validation

The workflow is meant to bypass local Smart App Control build-script blocking.
Local validation should still include:

```powershell
cd D:\Grandpa\frontend
npm run build
```

Local `npx tauri build` may remain blocked by Windows policy. That is an
environment restriction, not a Grandpa source-code failure.
