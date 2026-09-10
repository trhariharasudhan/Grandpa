"""Where Grandpa's entry surfaces learn what to build and what to inject.

Composition only: this package wires existing pieces together and owns no
behaviour of its own. It is the one layer permitted to name a concrete
actuator, which is what lets the capability and policy packages stay off the
execution module.
"""

from grandpa.composition.files import DEFAULT_FILE_ORIGIN, build_file_automation

__all__ = ["DEFAULT_FILE_ORIGIN", "build_file_automation"]
