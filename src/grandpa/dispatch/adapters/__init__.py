"""Where the dispatcher contract meets code that already exists.

The dispatcher core -- ``context``, ``protocol``, ``registry`` -- imports no
capability and must stay that way; it is the vocabulary every surface shares.
Adapters are the deliberate exception: an adapter's whole job is to name one
existing implementation and present it in the shared shape, so it necessarily
depends on the thing it adapts.

Keeping that dependency here rather than in the core is what lets the core stay
importable from anywhere. The split is enforced by test, not convention:
``dispatch/*.py`` may import nothing but ``policy.models``, while
``dispatch/adapters/*.py`` may additionally import the specific capability each
adapter wraps.

Nothing in this package is wired into production routing.
"""
