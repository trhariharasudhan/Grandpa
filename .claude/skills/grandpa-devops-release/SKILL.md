---
name: grandpa-devops-release
description: Ship Grandpa changes safely - branch and Conventional Commit workflow with milestone tags, the commit guard and git hooks, GitHub Actions (lint, Linux test, Windows test, on-demand Windows e2e, Rust, headless Docker arm64, MkDocs docs, autotag dev versions, PyPI publish), version numbers, the release checklist and final release gate, the one-command Windows installer and launcher, and the headless Docker image. Use when preparing a PR, a failing CI job, bumping a version, cutting a release, changing a workflow, the installer, or the Docker image.
---

# GRANDPA DevOps and release

## Git workflow

1. Branch from `main`; never commit to `main` directly. One focused,
   behaviour-preserving change per PR (CONTRIBUTING).
2. **Conventional Commits**: `fix(voice): ...`, `feat(automation): ...`,
   `docs: ...`. Put the milestone tag in the PR title when there is one,
   e.g. `feat(screen): ... (C3)` (series in the `grandpa-master-orchestrator`
   skill, `references/roadmap.md`).
3. Before committing, run the focused tests for what you touched
   (`grandpa-testing-qa`, `scripts/which_tests.py`) and `uv run ruff check src tests`.
4. **Commit guard (optional, per worktree):** `uv run python scripts/install_git_hooks.py`
   (`--check`, `--uninstall`). `scripts/git-hooks/commit-msg` refuses a commit
   without a recorded passing run for the touched packages; the escape hatch is
   a `Tests-Skipped:` trailer with a real reason (≥ 20 chars).
   `post-commit` logs `--no-verify` bypasses to `runtime/verification/unverified.log`,
   which makes a test fail until handled. `pre-commit install` adds the
   `.pre-commit-config.yaml` hooks.
5. Commit or push only when Captain asks. Never force-push `main`, never
   rewrite someone else's branch, never commit `.env` or anything under
   `GRANDPA_HOME`.
6. PR description: what changed, why, tests run with exact counts, what could
   not be verified (Windows-only, hardware), screenshots for UI.

## CI (`.github/workflows/`)

| Workflow / job | Trigger | Runs |
|---|---|---|
| `ci.yml` lint | push/PR to main | `uv run ruff check src/ tests/` (ubuntu) |
| `ci.yml` test | push/PR | Linux subset, with `maturin develop` for the Rust binding |
| `ci.yml` test (windows) | push/PR | **full** `pytest -m "not live and not cloud"`; the authoritative signal |
| `ci.yml` e2e (windows, on demand) | `workflow_dispatch` only | `scripts/run_e2e.py --model <E2E_MODEL>`; needs a local model |
| `ci.yml` rust | push/PR | `cargo clippy -D warnings`, `cargo test --workspace` |
| `docker-headless.yml` | PR/push touching `docker/`, `server/`, `engine/`, `pyproject.toml` | builds the arm64 headless image and smoke-runs it (no push) |
| `docs.yml` | `docs/`, `mkdocs.yml`, `src/grandpa/` changes | `mkdocs build`, deploys Pages from main |
| `autotag.yml` | push to main | tags `v<major>.<minor>.<patch+1>.dev<commit count>`; then dispatches downstream workflows (currently fails: it dispatches a `desktop.yml` that does not exist) |
| `pypi-publish.yml` | release / tag / manual | sets `version` from the tag, `uv build`, `uv publish` (OIDC `id-token: write`) |
| `take-assign.yml` | issue comment "take" | self-assign |

Install for every Python job: `uv sync --extra dev --extra server --extra voice --extra screen`.

**A red job:** read the log, reproduce locally with the same command, find the
root cause (`grandpa-debugging-performance`). A failure is "not this PR's" only
if it is also red on `main`. Never skip, mark xfail, or delete a test to get
green; never re-run more than once hoping it passes.

## Versions

- `pyproject.toml` `version` is the **base** (currently `1.0.1`). Autotag
  derives dev tags from it, so a real release must bump it first.
- Tags exist up to `v1.0.3` while the base still says `1.0.1`. Treat that
  mismatch as known; fix it with a deliberate version bump, not by editing tags.
- `CHANGELOG.md` uses Keep a Changelog; add user-visible changes under
  `[Unreleased]` in the same PR.

## Release

Follow `docs/development/release-checklist.md` in order:

```powershell
uv lock
uv sync --extra dev --extra server --extra voice --extra screen
python -m compileall -q src scripts tests
uv run --no-sync ruff check src tests scripts
python -m pytest -q
git diff --check
uv build
```

Then the Windows smoke commands from that checklist on a clean profile, the
security review list (API on loopback, confirmation on destructive actions, no
cloud fallback, no OAuth files or `%USERPROFILE%\.grandpa` data in artifacts),
and the final gate: `scripts/release/final-release-gate.ps1` /
`final_release_gate.py` (`docs/release/final-release-gate.md`).
Release tests must never click, send email, change the calendar, or delete.
Publishing a release or tag is outward-facing: only with Captain's explicit yes.

## Installer and launcher (Windows)

- `scripts/install.ps1`: uv → Python 3.11 → `uv sync` with voice, screen,
  server, piper, tamil-voice and scheduler extras → Ollama check → launcher →
  `grandpa setup --yes` → desktop shortcut → `grandpa doctor`. Idempotent, no
  admin rights. Flags: `-DryRun`, `-SkipModels`, `-SkipVoice`. Test changes with
  `-DryRun` first.
- `grandpa.cmd` and `scripts/install_launcher.ps1` replace a `grandpa.exe`
  because Smart App Control / Device Guard block unsigned executables (E0).
- `scripts/oauth_all.py` is an inherited helper (Google, Strava, Spotify) that
  writes to `~/.grandpa/connectors` directly. Only Google is used by Grandpa;
  don't ship instructions that depend on it.

## Docker (headless home-server node)

`docker/headless.Dockerfile` builds the Pironman / Raspberry Pi node
(`grandpa server --headless`, P2). CI builds arm64 without pushing. Changes to
`server/` or `engine/` trigger it. Server specifics: `grandpa-api-server`.

## Dependencies

`uv add` / `uv add --optional <extra>`, commit `pyproject.toml` + `uv.lock`
together, explain any new core dependency in a comment, and run the Windows
job. For upgrades: one package per PR when it touches voice, OCR or Ollama
clients, with the related manual QA script.
