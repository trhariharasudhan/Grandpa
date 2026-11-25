#!/usr/bin/env python3
"""Print the action catalogue: name, domain, risk, confirmation, implementation.

Read-only. It imports only grandpa.action_layer.catalogue, which by design
imports no implementation (tests/action_layer/test_import_isolation.py). It
still arms a throwaway GRANDPA_HOME before importing grandpa, because
grandpa.core.config resolves paths at import time and the repo's
require_sandboxed_probe hook expects every probe to be sandboxed.

Usage (from the repo root):
    GRANDPA_HOME=$(mktemp -d) uv run python .claude/skills/grandpa-action-layer/scripts/catalogue_report.py
    ... catalogue_report.py --risk HIGH
    ... catalogue_report.py --domain notes
    ... catalogue_report.py --confirm          # only actions that ask first
    ... catalogue_report.py --summary          # counts only
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

# Sandbox before any grandpa import.
os.environ.setdefault("GRANDPA_HOME", tempfile.mkdtemp(prefix="grandpa-catalogue-"))
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from grandpa.action_layer import catalogue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--risk", choices=["LOW", "MEDIUM", "HIGH", "BLOCKED"])
    parser.add_argument("--domain")
    parser.add_argument(
        "--confirm", action="store_true", help="only actions that require confirmation"
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    rows = []
    for spec in catalogue.CATALOGUE:
        domain = catalogue.domain_of(spec.name) or "-"
        if args.risk and spec.risk.value != args.risk:
            continue
        if args.domain and domain != args.domain:
            continue
        if args.confirm and not spec.requires_confirmation:
            continue
        rows.append(
            (
                spec.name,
                domain,
                spec.risk.value,
                spec.confirmation.value,
                spec.implementation,
            )
        )

    if args.summary or not rows:
        by_risk = Counter(r[2] for r in rows)
        by_conf = Counter(r[3] for r in rows)
        print(f"actions: {len(rows)} (catalogue total {len(catalogue.CATALOGUE)})")
        print("by risk:", dict(sorted(by_risk.items())))
        print("by confirmation:", dict(sorted(by_conf.items())))
        print("core domains:", ", ".join(catalogue.CORE_DOMAINS))
        print(
            "excluded (stubs/not catalogued):", ", ".join(sorted(catalogue.EXCLUSIONS))
        )
        return 0

    width = max(len(r[0]) for r in rows)
    for name, domain, risk, confirmation, impl in rows:
        print(f"{name:<{width}}  {domain:<10} {risk:<7} {confirmation:<6} {impl}")
    print(f"\n{len(rows)} action(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
