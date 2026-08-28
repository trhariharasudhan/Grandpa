"""Typed Windows desktop services: applications, windows, files, power, input.

Intentionally exports nothing. Callers import the concrete module they need
(``grandpa.desktop.control.windows``, ``grandpa.desktop.kernel.risk``, and so
on) and nothing in the tree imports ``grandpa.desktop`` itself, so re-exporting
here would only add import weight -- and ``pc_control`` <-> ``desktop`` is
already the heaviest import cycle in the package.

This file exists because ``desktop`` was the only real Python package under
``src/grandpa`` without one, which made it an implicit namespace package.
Runtime was unaffected (hatchling ships the directory either way), but griffe
cannot traverse a namespace package the way mkdocstrings needs, so the docs
build failed with:

    ERROR - mkdocstrings: grandpa.desktop.applications could not be found
    ERROR - Could not collect 'grandpa.desktop.applications'
    Aborted with a BuildError!

That failure predates this branch -- it is byte-identical on main at a031346a.
"""
