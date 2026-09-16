"""Map a chat phrase to a catalogued file action.

``FileParser`` still reads the phrase, so exactly the same wording is caught as
before and nothing new is claimed from the handlers below. What moved is the
decision after it: the risk tier, whether to ask, and the audit record.

**One change a user can notice, and it is deliberate.** Chat reached the files
domain through ``file_assistant``, which passed a private, narrower set of
roots -- Downloads, Documents, Desktop and the workspace -- where the action
layer and voice both used ``grandpa.files.paths.safe_roots()``, which also
covers the home directory and the working directory. That is one domain with
two ideas of where it may look, and the narrow one applied to exactly one of
the three routes: ``voice/operator.py`` calls ``handle_file_automation`` with
no roots at all.

Going through the layer settles it on the domain's own definition, so all three
routes agree. What actually bounds a file operation is the protected-path
policy in ``grandpa.files.safety`` -- System32, Program Files, .ssh, the
browser profile directories, .grandpa -- and that applies either way.
``file_assistant``'s own features keep their narrow list; only file operations
move.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, Origin
from grandpa.files.models import FileAction

__all__ = ["ACTION_FOR", "build_file_request"]

ACTION_FOR: dict[str, str] = {
    "create_file": "file_create",
    "create_folder": "file_create",
    "rename": "file_rename",
    "move": "file_move",
    "copy": "file_copy",
    "delete": "file_delete",
    "read": "file_read",
    "search": "file_search",
    "open": "file_open",
    "open_containing_folder": "file_open_folder",
    "properties": "file_properties",
    "zip": "file_zip",
    "extract": "file_extract",
}
"""Every action the parser can produce, and the catalogue entry for it.

The whole vocabulary: a phrase the parser still recognises but the catalogue
could not name would be a phrase chat silently stopped answering.
"""


def _parameters(action: FileAction) -> dict[str, Any]:
    if action.action == "search":
        return {"query": action.query or action.source}

    parameters: dict[str, Any] = {"path": action.source}
    if action.action == "create_folder":
        parameters["kind"] = "folder"
    if action.action == "rename":
        parameters["new_name"] = action.destination
    elif action.destination:
        parameters["destination"] = action.destination
    return parameters


def build_file_request(text: str) -> tuple[ActionRequest | None, FileAction | None]:
    """The request for ``text``, or ``(None, None)`` when this is not for us."""
    from grandpa.files.parser import FileParser

    parsed = FileParser().parse(text)
    if parsed is None:
        return None, None

    name = ACTION_FOR.get(parsed.action)
    if name is None:
        # The parser grew an action the catalogue has not been told about.
        # Falling through leaves the phrase to the handlers below rather than
        # answering it with a guess.
        return None, None

    spec = get(name)
    return (
        ActionRequest(
            name,
            _parameters(parsed),
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        parsed,
    )
