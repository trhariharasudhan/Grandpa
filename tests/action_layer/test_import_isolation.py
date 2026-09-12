"""The new layer must not drag the old one in.

This package was moved out of ``grandpa.actions`` precisely because importing
``grandpa.actions.model`` ran the legacy router's ``__init__`` and pulled in
seven handler modules. That is the kind of coupling that comes back silently:
one convenience import at the top of a new file and the layer is wearing the
old dispatch chain again.

So the check runs in a *clean* interpreter -- inside this one, pytest has
already imported half the codebase, and ``sys.modules`` would prove nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

# Importing any of these from the action layer would re-couple it to a stack
# the layer exists to replace.
FORBIDDEN = (
    "grandpa.pc_control",
    "grandpa.local_actions",
    "grandpa.desktop_automation",
    "grandpa.desktop_context",
    "grandpa.browser_control",
    "grandpa.actions",  # the legacy router this package was moved out of
    "grandpa.actions.router",
    "grandpa.actions.desktop_actions",
    "grandpa.actions.browser_actions",
    "grandpa.cli",
)

PUBLIC_MODULES = (
    "grandpa.action_layer",
    "grandpa.action_layer.model",
    "grandpa.action_layer.catalogue",
    "grandpa.action_layer.tool_schema",
    "grandpa.action_layer.executor",
    "grandpa.action_layer.loop",
)

_PROBE = """
import importlib, json, sys

importlib.import_module({module!r})
print(json.dumps(sorted(name for name in sys.modules if name.startswith("grandpa"))))
"""


def _grandpa_modules_after_importing(module: str) -> list[str]:
    probe = subprocess.run(
        [sys.executable, "-c", _PROBE.format(module=module)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert probe.returncode == 0, probe.stderr
    return json.loads(probe.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("module", PUBLIC_MODULES)
def test_importing_the_action_layer_pulls_in_no_legacy_stack(module: str) -> None:
    imported = _grandpa_modules_after_importing(module)

    leaked = sorted(set(imported) & set(FORBIDDEN))
    assert not leaked, (
        f"importing {module} pulled in {leaked}. The action layer names "
        "implementations as dotted-path strings and imports them only when the "
        "executor actually calls one."
    )


def test_the_probe_would_notice_a_leak() -> None:
    """A check that cannot fail is worth nothing, so prove this one can."""
    imported = _grandpa_modules_after_importing("grandpa.pc_control")

    assert "grandpa.pc_control" in imported


def test_the_legacy_package_still_imports_its_handlers() -> None:
    """Untouched, and left that way -- this test would notice if it were not."""
    imported = _grandpa_modules_after_importing("grandpa.actions")

    assert "grandpa.actions.router" in imported
    assert "grandpa.action_layer" not in imported, (
        "the legacy package must not depend on the new layer either"
    )
