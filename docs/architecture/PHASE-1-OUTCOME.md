# Phase 1 outcome — one action layer, one approval model

Status: complete. Merged to `main` as `a43c714c`, with the fail-open work
following on `fix/fail-open-defaults`.

This is the record of what Phase 1 built, what it deleted, every security hole
it found on the way, and what it deliberately left open. It is written for
whoever picks up Phase 2, and for anyone who wants to know whether a particular
door is closed.

---

## 1. What the action layer is

A single catalogue of every capability Grandpa has, and a single executor that
performs one.

* **`action_layer/catalogue.py`** — **167 actions**, each an `ActionSpec` with
  a name, a risk tier, a parameter schema and a dotted path to the one
  implementation behind it. Six further names are listed as `EXCLUSIONS` with a
  reason: they exist so a refusal can be explicit, not so they can be offered.
* **`action_layer/executor.py`** — `execute(ActionRequest, confirm_callback)`.
  Risk is derived from the catalogue entry, never accepted from the request.
  Whether something needs confirmation is one rule (HIGH, or on
  `APPROVAL_REQUIRED_ACTIONS`), not a per-entry opinion.
* **`Origin`** — `USER_CHAT`, `USER_VOICE`, `MODEL`, `AGENT`, `SKILL`. What
  asked matters, because the answer to "can this caller be asked?" differs.

The point is not the catalogue. The point is that there is **one** of it. Every
hole in section 3 has the same shape: two routes to one capability, agreeing by
hand until they stopped.

### The consent model

Two rules, and the distinction between them is the whole design:

1. **Synthetic input is never staged.** A keystroke lands on whatever has focus
   at the instant it is sent, so consent given 200 seconds ago is consent to
   something else. Keyboard and mouse actions are asked about inline, at the
   moment of action, or refused. A caller that cannot be asked — a spoken turn,
   an agent, a saved skill — gets a refusal, not a queue slot.
2. **Everything else may be deferred**, through one approval store with one
   expiry (`pc_control.PENDING_TTL_SECONDS`, 300s), bound to the origin that
   staged it, single-use. Deferred consent is opted into, not assumed.

Phase 1 retired **three competing expiry policies** on the way to that:
`local_action_approvals` (120s), `automation.ConfirmationManager` (120s) and
`kernel/compat.InMemoryConfirmationService` (120s, now a test-only stand-in
under `tests/`).

---

## 2. What it replaced

| Was | Now |
|---|---|
| Chat, voice, skills and agents each calling `pc_control.run_local_action` | All four go through `action_layer.executor` |
| `local_actions.py`, 2231 lines: parsers, tier decision, executor and audit in one file | `grandpa/local/` — `parsers` (1215), `execute` (401), `permissions` (326), `router` (298), `audit` (57), `types` (10), layered and acyclic. No shim; `grandpa.local_actions` does not exist |
| Four confirmation stores with four expiries | One store, one expiry, origin-bound |
| Risk decided in several places from several tables | Derived from the catalogue entry |

**Deleted rather than repaired**, because a capability that does not work is
worse than one that is absent — a person asked to approve it agrees to
something that never happens:

* the five browser stubs (`browser_click`, `browser_focus`, `browser_reload`,
  `browser_form_fill`, `browser_download`)
* `browser_media`, catalogued as a reader and implemented as an unconditional
  "unsupported"
* the `media|`, `form_fill|`, `download|` and `task|` phrase routes
* Chrome profile selection, which built a vision graph, fuzzy-matched a profile
  name and clicked at the matched coordinates with nothing asked first

---

## 3. Every security hole this phase found

None of these came from the original audit. They were found by doing the work,
and each is fixed, tested and mutation-proved.

### 3.1 Content choosing what may happen

* **A saved skill could rename the action it performed.** `_pc_action` built
  its payload with `params.get("action_type", action_type)`, and a runtime
  skill's params come from a *stored* workflow step. `POST /v1/user-skills/
  create` accepted a `desktop.summary` step declaring `risk_level: LOW` whose
  params named `system_lock`, and the screen locked the next time that skill's
  trigger phrase was said. (`fd690a65`)
* **Saving a skill was not an approval**, though a saved skill is deferred
  execution: it runs later, on a trigger phrase, with nobody reading its steps.
  (`fd690a65`)
* **A stored step could raise its own privileges**, turning `db_query`'s
  `read_only` off and reaching DROP. (`639a0470`)
* **A manifest did not say who wrote it**, and `skill_manage` — a model-facing
  tool — writes manifests. (`639a0470`, `22eec862`)

### 3.2 Two routes to one capability

* **Voice Operator Mode** called `pc_control` directly. The tiers on both sides
  agreed the day they were compared, which is a coincidence maintained by hand.
  (`74a1c1a1`)
* **agent_plan** read the desktop through two more direct doors. (`e585e0e2`)
* **The intent router** — the only route that executes with `dry_run=False` —
  stamped `LOW` on every match without asking the registry, and one row already
  named a MEDIUM skill. Nothing acting was reachable, so nothing had gone
  wrong; it was safe because of what the table contained, not because of a
  check. (`8b960ad6`)

### 3.3 Defaults that said yes

* **`allowed_dirs=[]` meant "allow everything"** in `file_read` and
  `file_write`, and nothing ever passed a list — so the guard was inert in
  every configuration Grandpa runs in, and `file_write` could write
  `~/.grandpa/skills/`, authoring a manifest without going near the gated tool
  that is supposed to write them. (`639a0470`)
* **Six config defaults ignored `GRANDPA_HOME`**, being evaluated at
  class-definition time. The test suite wrote an audit database into a real
  home directory on every run. (`79e576d8`)
* **`RUNTIME_DIR` and two stores were relative paths**, so state followed the
  working directory. A `user_skills.db` was left inside the repository and
  later loaded by a test that believed its store was isolated. (`79e576d8`)

### 3.4 The test suite itself

* **Six machine changes in one session** — Notepad twice, brightness, a real
  Ctrl+C, the volume, the screen lock — each "fixed" by adding that category to
  a recorder, which is a list of what has already gone wrong. Replaced with
  default-deny driven by the catalogue: 91 implementations and primitives are
  replaced before every test, and a test that needs a real one says so with a
  reason.
* **Tests could still write anywhere.** The actuation guard covers *catalogued
  implementations*; `FileWriteTool` is a tool. A mutation run removed its path
  guard — which is what a mutation run is for — and the test asserting the
  refusal named real absolute paths, so `x` landed on a real
  `~/.ssh/authorized_keys` and a real `~/.grandpa/config.toml`. Writes are now
  confined at the filesystem level. (`79e576d8`)
* **The suite was creating `MagicMock/...` directory trees in the repository**
  — 319 sqlite files across two checkouts — because a mocked config left
  `audit_log_path` as a `MagicMock` and the security setup made a directory out
  of its repr. `.gitignore` had been taught to hide the symptom. (`79e576d8`)

### 3.5 Tools reachable unprompted from a saved manifest

Fourteen could change something with no confirmation. They are tiered now
rather than all gated or all trusted, because a prompt on every memory write is
an unusable gate, and an unusable gate gets disabled:

* **Prompted:** `apply_patch`, `code_interpreter`, `repl`, `shell_exec`,
  `git_commit`, `skill_manage`.
* **Bounded:** `file_write`, `db_query`, `text_to_speech`, `http_request`,
  `web_search`.
* **Ungated:** the memory, knowledge-graph and user-profile writers — on the
  argument that they write only inside Grandpa's own home. Two of them did not,
  until they were fixed. (`2df79819`)

---

## 4. What is still open

Stated plainly, because a phase that claims to have closed everything is not
believable.

* **`file_write` can still reach `~/.grandpa/skills/` in principle** — it is
  now refused by the file domain's protected-path list, which is a *list*. The
  underlying weakness is that `FileWriteTool` is ungated; the bound is what
  holds.
* **RBAC is disabled by default and fails open.** `CapabilitiesConfig.enabled`
  is `False`, so every `required_capabilities` declaration on every tool is
  inert. This is original finding 2's sibling and was not in Phase 1's brief.
* **`repl` executes Python in-process** behind a denylist and restricted
  builtins, not a sandbox, in a daemon thread. It is confirmation-gated now,
  which bounds *who* can invoke it, not what it can do once invoked.
* **`dry_run` is advisory.** `RuntimeSkill.execute` never checks it; each
  executor must honour it. Two of 44 skills do not, and both are reads — which
  is the only reason agent_plan's reliance on `dry_run` is sound. A test fails
  if a write joins that set.
* **Six desktop-control stacks remain** (original finding 18). Phase 1 removed
  four of the routes *into* them, not the stacks.
* **Actions carry no `origin` in the audit record**, so the trail cannot
  distinguish a user-typed action from a model-selected one. Pinned by
  `TestOriginIsNotYetCarried` so the gap is visible in the suite.
* **Writes that never pass through Python** — sqlite's C implementation, a
  subprocess writing on its own — are invisible to the test write guard. They
  reach the disk through `subprocess.Popen` and the catalogued implementations,
  which default-deny already covers.
* **Three developer report paths** (`burnin.py`, `production_audit.py`,
  `release_gate.py`) still write into the repository. That is what they are
  for; they are not user stores.

---

## 5. How to check any of this

```bash
python -m pytest -q
python scripts/run_e2e.py
python scripts/verify_confirmation_enforcement.py
```

The security properties live in `tests/security/`. Each file states the hole it
closes in its own docstring, and most were mutation-proved: the fix was
reverted, the test was watched to fail, and the fix was restored.
