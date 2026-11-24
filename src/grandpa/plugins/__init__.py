"""Grandpa plugins: ``plugins/<name>/plugin.toml`` plus one Python file (G2).

This package is also the only part of Grandpa a plugin may import. Plugins
reach everything else through the ``ctx`` their functions receive.
See :mod:`grandpa.plugins.host` for the rules and docs/getting-started/plugins.md.
"""

from __future__ import annotations

from grandpa.action_layer.model import ActionResult

__all__ = ["ActionResult"]
