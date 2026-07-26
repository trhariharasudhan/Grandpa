"""Expected Screen Vision errors."""


class ScreenError(Exception):
    """Base class for user-facing screen errors."""


class ScreenCaptureError(ScreenError):
    pass


class MonitorNotFoundError(ScreenError):
    pass


class ActiveWindowUnavailableError(ScreenError):
    pass


class OcrUnavailableError(ScreenError):
    pass


class OcrProcessingError(ScreenError):
    pass


class SensitiveScreenDetectedError(ScreenError):
    pass


class InvalidScreenshotPathError(ScreenError):
    pass


class ScreenDependencyError(ScreenError):
    pass


class ScreenConfigurationError(ScreenError):
    pass


__all__ = [
    "ActiveWindowUnavailableError",
    "InvalidScreenshotPathError",
    "MonitorNotFoundError",
    "OcrProcessingError",
    "OcrUnavailableError",
    "ScreenCaptureError",
    "ScreenConfigurationError",
    "ScreenDependencyError",
    "ScreenError",
    "SensitiveScreenDetectedError",
]
