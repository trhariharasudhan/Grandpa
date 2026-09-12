"""The single action layer: one description of everything Grandpa can do.

Grandpa reaches the desktop through six separate stacks with four different
approval models (``docs/audit/FEATURE-INVENTORY.md`` sections 4.1 and 4.2).
This package is the replacement: a typed request/result contract
(:mod:`~grandpa.action_layer.model`), one honest catalogue of what is actually
implemented (:mod:`~grandpa.action_layer.catalogue`), a tool-schema export
(:mod:`~grandpa.action_layer.tool_schema`), the one place actions execute
(:mod:`~grandpa.action_layer.executor`), and a model-driven loop over the two
(:mod:`~grandpa.action_layer.loop`).

**Nothing in this package imports a legacy stack.** Not ``pc_control``, not
``local_actions``, not ``desktop_automation``, not ``grandpa.actions`` -- the
package this one was moved out of, whose ``__init__`` pulls in seven handler
modules. Implementations are named as dotted-path strings and imported only at
the moment the executor calls one.
``tests/action_layer/test_import_isolation.py`` enforces that in a clean
interpreter, so the rule cannot rot.

Importing this package is therefore cheap, and a consumer of the contract does
not inherit the old dispatch chain.
"""

from grandpa.action_layer.catalogue import CATALOGUE, EXCLUSIONS, ActionSpec
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin, RiskLevel
from grandpa.action_layer.tool_schema import as_tool_definition, as_tool_definitions

__all__ = [
    "CATALOGUE",
    "EXCLUSIONS",
    "ActionRequest",
    "ActionResult",
    "ActionSpec",
    "Origin",
    "RiskLevel",
    "as_tool_definition",
    "as_tool_definitions",
]
