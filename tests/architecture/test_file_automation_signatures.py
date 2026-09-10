"""The public shape of the file-automation entry points.

These three signatures are what callers outside ``files/`` bind to:
``file_assistant``, the CLI paths, the HTTP route and both voice surfaces all
reach the file layer through them. Changing one is a breaking change to every
one of those callers, which is why the shape is asserted rather than assumed.

The assertions arrived as ``test_public_file_automation_signatures_remain_compatible``
and were duplicated verbatim in two of the kernel migration suites. They were
written to protect the public surface *while* the kernel migration was in
flight, but nothing in them is about the kernel: the adapter was constructed
inside ``__init__`` and never appeared in a signature. So the invariant
outlived the migration that motivated it, and it is kept here -- once, in the
package for guards on shape rather than behaviour -- instead of being retired
alongside the kernel tests that happened to house it.

Unchanged from the originals. Both copies asserted exactly these three
parameter lists.
"""

from __future__ import annotations

import inspect

from grandpa.files.automation import FileAutomation, handle_file_automation


def test_public_file_automation_signatures_remain_compatible():
    assert list(inspect.signature(FileAutomation).parameters) == [
        "roots",
        "parser",
        "executor",
        "opener",
    ]
    assert list(inspect.signature(FileAutomation.handle).parameters) == [
        "self",
        "text",
        "confirm",
    ]
    assert list(inspect.signature(handle_file_automation).parameters) == [
        "text",
        "roots",
        "confirm",
        "opener",
    ]
