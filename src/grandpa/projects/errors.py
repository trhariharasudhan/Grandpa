"""Expected Project Manager errors."""


class ProjectError(Exception):
    """Base class for user-facing project errors."""


class ProjectNotFoundError(ProjectError):
    pass


class AmbiguousProjectError(ProjectError):
    pass


class InvalidProjectPathError(ProjectError):
    pass


class ProjectAlreadyRegisteredError(ProjectError):
    pass


class WorkflowNotConfiguredError(ProjectError):
    pass


class ProjectProcessError(ProjectError):
    pass


class ProjectCommandTimeoutError(ProjectProcessError):
    pass


class UnsafeProjectCommandError(ProjectError):
    pass


__all__ = [
    "AmbiguousProjectError",
    "InvalidProjectPathError",
    "ProjectAlreadyRegisteredError",
    "ProjectCommandTimeoutError",
    "ProjectError",
    "ProjectNotFoundError",
    "ProjectProcessError",
    "UnsafeProjectCommandError",
    "WorkflowNotConfiguredError",
]
