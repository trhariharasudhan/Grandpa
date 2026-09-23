"""Where the model's file tools may read and write.

``file_read`` and ``file_write`` each took an ``allowed_dirs`` list and, when
it was empty, allowed everything::

    if not self._allowed_dirs:
        return True

Nothing ever passed a list. ``ToolRegistry.create("file_write")`` builds the
tool with no arguments, so the guard was inert in every configuration Grandpa
actually runs in, and a model could write any path on the disk -- including
``~/.grandpa/skills/``, where a manifest is deferred execution.

An empty list now means *nothing* is allowed, and "unconfigured" is a separate
state that means "use the file domain's policy". That policy is not invented
here: it is the one ``grandpa.files`` already applies to the user's own file
actions -- :func:`safe_roots` for where, :class:`FileSafetyPolicy` for the
carve-outs inside it. Two policies for one capability is the shape of every
hole this phase found, so these tools defer to the domain rather than keeping
a second opinion.
"""

from __future__ import annotations

from pathlib import Path


def default_scope() -> tuple[Path, ...]:
    """The roots the file domain already searches, reads and writes.

    Resolved on each call rather than at construction: the roots depend on
    ``GRANDPA_HOME``, ``tools.workspace`` and the working directory, and a tool
    built at import time would otherwise pin whatever those were then.
    """
    from grandpa.files.paths import safe_roots

    return safe_roots()


def is_within_scope(path: Path, allowed: tuple[Path, ...] | None) -> bool:
    """Whether ``path`` is somewhere these tools may touch.

    ``allowed`` of ``None`` means unconfigured, and falls back to the domain's
    roots. An empty tuple means an explicit "nowhere", and refuses everything --
    that is the inversion: the absence of a permission is not a permission.
    """
    roots = default_scope() if allowed is None else allowed
    if not roots:
        return False
    resolved = path.resolve()
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)


def is_protected(path: Path) -> bool:
    """Whether the file domain treats this path as off limits.

    Applies inside the roots as well as outside them: ``~/.ssh`` and
    ``~/.grandpa`` are under the home directory, and a browser profile is under
    AppData. ``.grandpa`` matters most here -- it is where skill manifests
    live, so this is what stops ``file_write`` authoring one directly.
    """
    from grandpa.files.safety import FileSafetyPolicy

    return FileSafetyPolicy().is_protected(path)


def refusal(path: Path, allowed: tuple[Path, ...] | None) -> str | None:
    """The reason ``path`` is refused, or None when it is allowed."""
    if is_protected(path):
        return (
            f"{path} is a protected location (a system directory, a credential "
            "store, or Grandpa's own configuration)."
        )
    if not is_within_scope(path, allowed):
        roots = default_scope() if allowed is None else allowed
        if not roots:
            return f"{path} is outside the allowed directories (none are allowed)."
        listed = ", ".join(str(root) for root in roots[:4])
        return f"{path} is outside the allowed directories ({listed}, ...)."
    return None


def normalise(allowed_dirs: list[str] | None) -> tuple[Path, ...] | None:
    """``None`` stays None (unconfigured); a list becomes resolved paths."""
    if allowed_dirs is None:
        return None
    return tuple(Path(item).expanduser().resolve() for item in allowed_dirs)


__all__ = [
    "default_scope",
    "is_protected",
    "is_within_scope",
    "normalise",
    "refusal",
]
