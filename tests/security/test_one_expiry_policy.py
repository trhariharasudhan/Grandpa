"""One expiry policy for actions waiting on a human.

There were four, each with its own clock and its own idea of who could answer:

  pc_control's approval store        300s, persisted, origin-bound
  local_action_approvals             120s, its own sqlite file
  automation's ConfirmationManager    120s, in memory, per process
  kernel/compat's confirmations       120s, in memory, "tests only" in its
                                      docstring while files/automation used it

Three are gone and the fourth is the one: the kernel approval store. A second
policy is not a style problem -- it is a second answer to "has this expired?",
and the looser one wins wherever it is reached.

This test reads the source rather than the behaviour, because a new store is
added by writing one, not by failing an existing test.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "grandpa"

# Where the one policy lives.
OWNER = SRC / "pc_control.py"

# Seconds-valued expiry settings that are not about a human answering a
# question: a cache's freshness and a schedule's next run are not consent.
ALLOWED = {
    SRC / "web_search" / "cache.py",
    SRC / "scheduler" / "scheduler.py",
    SRC / "memory" / "store.py",
}

_PATTERNS = (
    re.compile(r"\bttl_seconds\b"),
    re.compile(r"\bTTL_SECONDS\s*=\s*\d"),
)


def test_only_pc_control_defines_a_pending_expiry() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        if path == OWNER or path in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        # Comments and docstrings may name the policy; code may not define one.
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        hits = [pattern.pattern for pattern in _PATTERNS if pattern.search(code)]
        if hits:
            offenders[str(path.relative_to(SRC))] = hits

    assert offenders == {}, (
        "a second expiry policy for pending actions: "
        f"{offenders}. The kernel approval store owns this "
        "(pc_control.PENDING_TTL_SECONDS)."
    )


def test_the_one_policy_is_five_minutes() -> None:
    from grandpa import pc_control

    assert pc_control.PENDING_TTL_SECONDS == 300


def test_no_module_keeps_its_own_pending_confirmations() -> None:
    """The stores that used to: a class holding tokens in a dict."""
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "class ConfirmationManager" not in text, path
        assert "class InMemoryConfirmationService" not in text, path
