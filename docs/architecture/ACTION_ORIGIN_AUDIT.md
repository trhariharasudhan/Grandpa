# Grandpa — Agent- and Skill-Origin Action Paths

**Purpose:** the evidence base required before the policy model is changed.
Enumerates every path by which LLM-, agent-, or skill-originated input can
cause a side effect, and states whether approval is currently required on each.

**Status:** analysis. No policy behaviour was changed to produce it.
**Date:** 2026-08-26
**Scope note:** this is the prerequisite for AD-006 (one `PolicyEngine`). It is
**not** the consolidation itself, which is Phase 4.

Tag legend is in `CURRENT_ARCHITECTURE.md`.

---

## 1. Summary

**[FACT]** There are **three** enforcement mechanisms guarding
agent-originated side effects, and they are not equivalent:

| # | Mechanism | Where | Default | Fails |
|---|---|---|---|---|
| 1 | **PolicyEngine** — risk tier + approval + default-deny | `run_local_action` → `desktop/kernel/risk` | active | **closed** |
| 2 | **Tool confirmation** — `ToolSpec.requires_confirmation` | `tools/_stubs.py:209` `ToolExecutor` | active | **closed** |
| 3 | **Capability RBAC** — `required_capabilities` | `security/capabilities.py` | **disabled** | **open** |

**[FACT]** Only mechanism 1 is a genuine policy boundary with tiers, approval
staging, and an audit trail. Mechanism 2 is binary and covers **3 of 43** tools.
Mechanism 3 is off by default and fails open even when on.

**[FACT]** The consequence: an agent-originated action is strongly gated **if
and only if** it routes through `run_local_action`. Agent-reachable tools that
actuate without going through it are guarded by denylist pattern-matching or by
nothing.

---

## 2. AD-022 — the path, restated and preserved

**[FACT]** The following is a valid, wired action path:

```
LLM → Agent → ToolRegistry → SkillTool → _pc_action → run_local_action
```

Evidence, each independently verifiable:

| Link | Evidence |
|---|---|
| SkillTool is agent-invocable | `skills/tool_adapter.py:1` — *"wraps a skill as a tool that agents can invoke"* |
| Skills are registered as tools | `system/builder.py:150` — `skill_manager.get_skill_tools(...)` when `config.skills.enabled` |
| Skill params reach the payload | `skills/registry/defaults.py:20-28` — `_pc_action` builds `{"action_type": params.get("action_type", action_type), "target": params.get("target", ...), ...}` and calls `run_local_action(payload)` |

**[FACT]** `_pc_action` takes `action_type` from caller-supplied `params` **in
preference to** the value the skill was registered with. A caller that controls
`params` therefore controls which action is requested, regardless of what the
skill manifest declares.

**[FACT]** This does **not** produce an escalation, because the declared skill
risk is not what gets enforced — `run_local_action` re-derives risk from the
actual `action_type`. Verified by `tests/test_action_origin_invariant.py`
(60 tests): substituting `shell_run` yields `status=blocked`, and injected
`risk_level` / `approval_required` / `require_approval` / `status` / `ok` fields
do not downgrade it.

> **[DECISION] The invariant to preserve into Phase 4.**
> `run_local_action` is the single mandatory enforcement boundary for desktop
> actuation. Its authority derives from re-deriving risk from the action itself
> and ignoring caller-asserted risk. **Any PolicyEngine consolidation must keep
> that property: risk is computed, never accepted.**

**Do not** state or rely on "model output cannot become an action." It can, by
design, through skills. The true property is that nothing actuates without
classification and, where required, approval.

---

## 3. Path A — desktop actuation via `run_local_action`

**Approval: ENFORCED.** This is the strong path.

### 3.1 Skills registered as agent-invocable tools that call `run_local_action`

**[FACT]** Four built-in skills wrap `_pc_action`:

| Skill | Action | Skill-declared risk | Skill `approval_required` | PolicyEngine tier | Approval enforced? |
|---|---|---|---|---|---|
| `desktop.summary` | `desktop_summary` | LOW | False | LOW | read-only |
| `desktop.monitors` | `list_monitors` | LOW | False | LOW | read-only |
| `desktop.diagnostics` | `pc_diagnostics` | LOW | False | LOW | read-only |
| **`desktop.keyboard_type`** | **`keyboard_type`** | **MEDIUM** | **True** | **MEDIUM + `APPROVAL_REQUIRED_ACTIONS`** | **YES — both layers** |

**[FACT]** `desktop.keyboard_type` (`defaults.py:1249-1257`) is gated twice:
`approval_required=True` on the manifest, and `keyboard_type ∈
APPROVAL_REQUIRED_ACTIONS` at the policy layer. The second is the one that
matters, because the first is bypassable by param substitution.

**[FACT]** One further direct call: `defaults.py:351-354`, a
`clipboard_history` skill — LOW risk, read-only. Note it can surface passwords
copied from a password manager; that is a known LOW-tier exposure, not an
approval bypass.

### 3.2 Non-skill agent callers of `run_local_action`

**[FACT]** Two, both **safe by construction**:

| Caller | Payload | Assessment |
|---|---|---|
| `agents/context.py:90` | hardcoded `{"action_type": "desktop_summary", "target": "desktop", "dry_run": True}` | literal; no model input reaches it |
| `agents/goal_mode.py:381` | identical hardcoded literal | same |

### 3.3 Enforcement properties verified

| Property | Status | Evidence |
|---|---|---|
| BLOCKED set refused from skill path | ✅ | 6 actions × 2 variants, incl. `dry_run=False` |
| Unknown/invented `action_type` → BLOCKED | ✅ | default-deny, 7 cases |
| HIGH risk requires approval | ✅ | 5 actions |
| `APPROVAL_REQUIRED_ACTIONS` requires approval | ✅ | incl. `keyboard_hotkey("win+r")` |
| Caller cannot downgrade own risk | ✅ | 6 injected-field variants |

---

## 4. Path B — tools that actuate *without* `run_local_action`

**Approval: MOSTLY NOT ENFORCED.** This is the gap.

**[FACT]** Of 43 registered tools, **3** set `requires_confirmation=True`:

| Tool | Confirm | Capability | What it does |
|---|:--:|---|---|
| `shell_exec` | **YES** | `code:execute` | shell command, sanitised env, timeout |
| `git_commit` | **YES** | `file:write` | writes a commit |
| `agent_kill` | **YES** | `system:admin` | terminates an agent |

**[FACT]** `ToolExecutor` fails **closed** on confirmation
(`tools/_stubs.py:209-219`): a tool requiring confirmation with no
`confirm_callback` is refused, not executed. So these three are genuinely
gated — including in non-interactive contexts, where they simply refuse.

**[FACT]** The remaining 40 do not require confirmation. Those with side
effects:

| Tool | Capability | Side effect | Guard |
|---|---|---|---|
| `code_interpreter` | **none** | executes Python in a subprocess | denylist + isolated subprocess + 30s timeout |
| `repl` | **none** | executes Python in a daemon thread | denylist + restricted builtins + timeout |
| `apply_patch` | `file:write` | writes files | capability only (disabled by default) |
| `file_write` | `file:write` | writes files | capability only |
| `agent_spawn` | `system:admin` | starts an agent | capability only |
| `agent_send` | `system:admin` | messages an agent | capability only |
| `db_query` | `code:execute` | runs SQL | capability only |
| `kg_add_entity`, `kg_add_relation` | `memory:write` | writes knowledge graph | capability only |
| `memory_store`, `memory_manage`, `memory_index`, `user_profile_manage` | none | writes memory | none |
| `browser_click`, `browser_type` | **none** | drives a real browser | none |
| `browser_navigate`, `browser_axtree` | `network:fetch` | fetches URLs | SSRF check |
| `http_request` | `network:fetch` | outbound HTTP | SSRF check |
| `skill_manage` | none | installs/edits skills | none |
| `text_to_speech` | none | audio output | none |

### 4.1 The two code-execution tools

**[FACT]** `code_interpreter` and `repl` execute attacker-influenced Python
with **no confirmation and no declared capability**. They are not unguarded,
but their guard is a **denylist**, which is a materially weaker model than the
allowlist-plus-tiers used on the desktop path.

`code_interpreter._BLOCKED_PATTERNS`: `os.system`, `os.popen`, `subprocess.`,
`shutil.rmtree`, `os.remove`, `os.unlink`, `os.rmdir`, `__import__`, `eval(`,
`exec(`, `compile(`, `open(`. Runs in an isolated subprocess with a 30 s
timeout.

`repl._BLOCKED_PATTERNS`: `os.system`, `os.popen`, `subprocess`,
`shutil.rmtree`, `__import__`, `open(`, `ctypes`, `socket`, `http.client`,
`urllib`, plus `_REMOVED_BUILTINS` stripping `open`/`exec`/`eval`/`compile`.
Runs in a **daemon thread** with a timeout.

**[RECOMMENDATION]** Do not treat these as equivalent to `shell_exec` being
confirmation-gated. `shell_exec` is BLOCKED-by-policy on the desktop path *and*
confirmation-gated on the tool path; `code_interpreter` and `repl` reach a
Python interpreter with neither. Whether that is acceptable is a decision for
the Phase 4 policy table, not something to settle here.

**[OPEN QUESTION] Q-11.** Should `code_interpreter` and `repl` require
confirmation, carry `code:execute`, or be gated by the PolicyEngine like
`shell_run` is? They are the largest asymmetry this audit found.

**[RECOMMENDATION]** `repl` executing in a daemon thread is also worth noting
independently: leaked daemon threads were the cause of the historical
`exit 127` interpreter-shutdown crash.

---

## 5. Path C — capability RBAC

**Approval: NOT ENFORCED BY DEFAULT.**

**[FACT]** `CapabilitiesConfig.enabled = False` (`core/config.py:586`).

**[FACT]** `capabilities.py:_check_python` returns `not self._default_deny`
when no policy exists for the agent, and `setup_security()` constructs
`CapabilityPolicy(default_deny=False)`. So even when enabled, a
partially-specified policy **grants** anything it does not mention.

**[FACT]** Consequence: every `required_capabilities` value in the table above
is currently **declarative only**. `apply_patch` declaring `file:write` does not
gate it.

This is GAP-06 / AD-013 and is already scheduled for Phase 1.3 (fail closed).
It is restated here because it is the reason "capability only" in §4 means "not
actually guarded".

---

## 6. Inert configuration — resolved

**[FACT]** The stabilization branch (`ff99715f`) removed the security config
keys that were never read, rather than leaving them to imply protection.
`core/config.py:REMOVED_CONFIG_KEYS` now holds **10** entries, each with its
reason, and loading a config that still sets one emits a warning:

`security.enforce_tool_confirmation`, `security.merkle_audit`,
`security.signing_key_path`, `security.ssrf_protection`,
`security.vault_key_path`, `security.rate_limit_enabled`,
`security.rate_limit_rpm`, `security.rate_limit_burst`,
`security.local_engine_bypass`, `security.local_tool_bypass`.

The two that matter most to this audit:

| Removed key | Recorded reason |
|---|---|
| `security.enforce_tool_confirmation` | never read; decided per-tool by `ToolSpec.requires_confirmation` and the executor's `confirm_callback` |
| `security.ssrf_protection` | never read; SSRF checks are unconditional in the `http_request`, browser and `web_search` tools and cannot be disabled |

**[FACT]** This closes part of GAP-19. Tool confirmation is genuinely per-tool
and genuinely enforced; there is no global switch that silently does nothing.

---

## 7. Findings, ranked

| # | Finding | Severity |
|---|---|---|
| 1 | `code_interpreter` and `repl` execute Python with no confirmation and no enforced capability; guarded only by denylists | **High** |
| 2 | Capability RBAC is disabled by default and fails open, so every `required_capabilities` declaration is inert | **High** (already scheduled, Phase 1.3) |
| 3 | `_pc_action` lets caller params override the skill's declared `action_type`, so manifest-declared risk is not a boundary | **Medium** — contained, because `run_local_action` re-derives risk |
| 4 | 40 of 43 tools require no confirmation, including `apply_patch`, `file_write`, `agent_spawn`, `browser_click`, `browser_type` | **Medium** |
| 5 | Two enforcement models with different strengths (tiers+approval vs binary confirm) and no shared vocabulary | **Medium** — this is what AD-006 consolidates |
| 6 | Actions carry no `origin`, so audit cannot distinguish user- from model-initiated | **Medium** — Phase 4, pinned by `TestOriginIsNotYetCarried` |
| 7 | `repl` executes in a daemon thread | **Low** |

---

## 8. What this means for Phase 4

**[RECOMMENDATION]** The PolicyEngine consolidation should treat this audit as
its acceptance criteria:

1. **Preserve** the property that makes Path A strong: risk is computed from the
   action, never accepted from the caller. Verified by
   `tests/test_action_origin_invariant.py`, which must keep passing.
2. **Extend** coverage to Path B. Tools that actuate should classify through the
   same engine rather than each carrying an ad-hoc guard.
3. **Add `origin`** as a required field with no default, so a missing origin is
   a type error rather than a silent default to `user`.
4. **Fail capability RBAC closed** before, not after, relying on
   `required_capabilities` for anything.
5. **Resolve Q-11** — the `code_interpreter` / `repl` asymmetry — explicitly,
   with the table in front of you.

**[FACT]** None of the above is implemented. This document records the current
state so the consolidation can be measured against it.

---

## Appendix — how to reproduce

```bash
# tools, their confirmation flag and declared capabilities
python - <<'PY'
import importlib, pkgutil
from grandpa.core.registry import ToolRegistry
import grandpa.tools as tp
for m in pkgutil.iter_modules(tp.__path__):
    try: importlib.import_module(f"grandpa.tools.{m.name}")
    except Exception: pass
for name in sorted(ToolRegistry.keys()):
    s = ToolRegistry.get(name)().spec
    print(name, s.requires_confirmation, s.required_capabilities)
PY

# skills that reach run_local_action
grep -n "_pc_action(\|run_local_action" src/grandpa/skills/registry/defaults.py

# every caller of the structured funnel
grep -rn "run_local_action(" src/ --include=*.py | grep -v "def "

# the invariant tests
python -m pytest tests/test_action_origin_invariant.py -q
```
