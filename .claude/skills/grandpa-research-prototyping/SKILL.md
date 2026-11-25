---
name: grandpa-research-prototyping
description: Research and de-risk technical choices for Grandpa before building - compare libraries, local models, TTS/STT engines, UI toolkits or protocols against Grandpa's constraints (offline-first, Windows 11, Ryzen 5 7520U iGPU with 16 GB shared with Ollama, no admin rights, Apache-2.0 licence compatibility), gather evidence from primary sources and measurements, run throwaway spikes outside src/, and write the result as a survey document with a recommendation. Use for "which library/model should we use", "is X possible on my laptop", "compare A vs B", feasibility of future features (smart home, IoT, hardware), or before adding any new dependency.
---

# GRANDPA research and prototyping

The repo already has a house style for this: **a survey, not a build.**
`docs/development/desktop-ui-survey.md` and `orb-survey.md` measured the
options on the real machine, labelled judgement as judgement, and ended with a
recommendation and a smallest useful version. `piper_pilot_plan.md` cites the
official docs for every requirement. Do research the same way.

## Constraints every option is checked against

| Constraint | Why |
|---|---|
| Works offline, local data by default | product principle #1 |
| Windows 11 first; Linux only for CI and the headless node | target platform |
| Ryzen 5 7520U, integrated GPU, 16 GB RAM **shared with Ollama** | target machine; anything heavy competes with the model |
| No admin rights; unsigned `.exe` may be blocked by Smart App Control | `scripts/install.ps1`, E0 launcher |
| Python ≥ 3.10 (3.11 installed), uv-installable, ideally pure-Python or wheels for Windows | packaging |
| Licence compatible with Apache-2.0 distribution; GPL/LGPL needs care (the vendored LGPL ffmpeg note in AD-019) | legal |
| Optional extra, not a core dependency, unless it's tiny and essential | `pyproject.toml` policy |
| Tamil and Tanglish support where language is involved | owner's languages |

## Workflow

1. **Write the question** in one line, plus the decision it feeds
   (e.g. "Which wake-word engine for B-series hands-free mode?").
2. **List candidates:** at least two real options plus "extend what we have"
   and "do nothing". Check the repo first (`rg`, `pyproject.toml` extras,
   `docs/development/*-survey.md`), because it often already has one.
3. **Gather evidence from primary sources:** official docs, release notes,
   licence files, issue trackers. Record the URL and the date you read it.
   Mark anything unverified as **[UNVERIFIED]**. Never invent benchmark
   numbers.
4. **Measure what matters** when you can: latency, RAM, CPU/GPU %, accuracy on
   a fixed sample (Tamil included), install size, cold start. Several runs,
   report median and range, and name the machine. If you can't run on Windows
   or the target laptop, say so and give Captain the exact commands to run.
5. **Spike only outside the product:** use `scratch/` (gitignored) or a
   throwaway branch. A spike never lands in `src/` and never adds a dependency to
   `pyproject.toml`. If a spike needs to import `grandpa`, set `GRANDPA_HOME` to a
   temp dir first.
6. **Write the survey** using [references/survey-template.md](references/survey-template.md)
   as `docs/development/<topic>-survey.md`: options table, measurements,
   recommendation, smallest useful version, what you would not build.
7. **Hand off:** a recommendation goes to Captain. After he decides, the plan
   goes to `grandpa-product-planning` and the structure to
   `grandpa-architecture-design`.

## Safety and privacy in research

- Never send Captain's data (voice samples, screenshots, emails, memory) to a
  third-party service to "try it". Use synthetic or public samples.
- Don't install system-wide tools or drivers on Captain's machine without his
  yes. Prefer `uv run --with <pkg>` in a sandbox.
- Downloaded models and archives are untrusted: verify checksums when the
  project publishes them (`voice_runtime/scripts/fetch_ffmpeg.py` pins one).

## Future-phase research (no code exists yet)

Smart home, IoT, Raspberry Pi peripherals, hardware and robotics are
**planned only** (`capability-status.md` in `grandpa-master-orchestrator`).
Research for them follows this skill, with extra checks:

- Local control first (e.g. MQTT on the LAN, Home Assistant's local API)
  before any vendor cloud.
- The existing headless node (`server/headless.py`, `docker/headless.Dockerfile`,
  P2) and phone pairing (`devices/`) are the natural integration points.
  Read `grandpa-api-server` before proposing a new channel.
- Physical actuation (locks, power, motors) gets at least HIGH risk and
  confirmation, like any other action.
- Orphaned databases from an earlier attempt (`iot_smart_home.db` and others,
  AD-021) are history, not a design to revive.

When that work starts, propose dedicated skills (`grandpa-smart-home-iot`,
`grandpa-hardware-robotics`) instead of growing this one.
