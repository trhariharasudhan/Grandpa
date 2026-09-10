"""Composition of the file surface: what to build, and what to hand it.

``FileExecutor`` has taken an injected ``MutationBoundary`` since the mutation
boundary slice, but injection was opt-in and only one caller opted in. Every
other production entry -- both CLI modules, the HTTP chat route and the voice
assistant -- reached ``FileAutomation`` through its default construction, which
supplies no runner, so their spoken and typed file mutations went to ``shutil``
and ``pathlib`` directly: no risk tier, no approval gate, no emergency stop, no
audit record, no verification. This module is what those callers construct
through instead.

**Why it is a layer of its own.** Naming ``run_local_action`` is exactly what a
capability package must not do -- ``files/`` and ``policy/`` are both required
to stay off the execution module, and asserting that is what keeps the file
layer out of the direct-executor baseline. Somebody has to know the concrete
runner, though, and the entry surfaces are the wrong place for it too: there
are four of them and they would each have to repeat the same wiring, which is
four chances to get it wrong and four places to fix when it changes. So the
knowledge lives here, once, in a module whose only job is to know it.

**What this is not.** It decides nothing. It classifies no risk, requests no
approval, validates no token, computes no digest, claims no decision, checks no
emergency stop, implements no dry run and touches no file. Every one of those
stays behind the callable, in ``pc_control``; the file-domain rules -- alias
resolution, blocked paths, the recursive-delete guard, the overwrite
confirmation -- stay in ``FileExecutor``. If this module ever grows a rule, it
has stopped being composition and become the second policy implementation the
architecture exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

from grandpa import pc_control
from grandpa.files.automation import FileAutomation
from grandpa.files.executor import FileExecutor, OpenCallback
from grandpa.policy.boundary import MutationBoundary

#: The provenance stamped on actions this file surface sends to the boundary
#: when the caller does not say otherwise. One of ``pc_control.ACTION_ORIGINS``,
#: and the least-privileged of them -- a programmatic caller *is* a direct
#: caller, which is what the CLI and the HTTP route are.
DEFAULT_FILE_ORIGIN = "direct"


def build_file_automation(
    *,
    roots: tuple[Path, ...] = (),
    opener: OpenCallback | None = None,
    origin: str = DEFAULT_FILE_ORIGIN,
    dry_run: bool = False,
    mutation_runner: MutationBoundary | None = None,
) -> FileAutomation:
    """Build a ``FileAutomation`` whose mutations go through the boundary.

    Every argument is forwarded to the constructors that already accept it;
    nothing here is interpreted. ``roots`` and ``opener`` keep their existing
    "empty means the default" meaning, resolved by ``FileExecutor`` as before,
    so this is the same object the default path built plus a runner.

    *mutation_runner* exists because one caller already supplies its own. The
    voice operator threads a per-turn ``action_runner`` -- the real actuator in
    production, a recorder under test -- and that seam predates this module and
    is what its tests bind to. Defaulting to ``run_local_action`` rather than
    requiring it means the ordinary caller says nothing and still gets the
    hardened path, while the one caller with a runner of its own keeps it.

    The executor is built here rather than reconfigured afterwards. Its runner,
    origin and dry-run are set once in ``__init__`` and never reassigned, so a
    request's provenance cannot leak into another request's.

    The actuator is looked up on the module at call time rather than bound at
    import. Binding it here would freeze whichever function object existed
    when this module was first imported, and a test that substitutes the
    actuator would then be driving the real machine through a stale
    reference without ever being told.
    """
    executor = FileExecutor(
        roots=roots,
        opener=opener,
        mutation_runner=mutation_runner or pc_control.run_local_action,
        origin=origin,
        dry_run=dry_run,
    )
    return FileAutomation(executor=executor)


__all__ = ["DEFAULT_FILE_ORIGIN", "build_file_automation"]
