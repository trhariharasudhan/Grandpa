"""Safe local File Automation Engine for Grandpa."""

from grandpa.files.automation import FileAutomation, handle_file_automation
from grandpa.files.executor import FileExecutor
from grandpa.files.models import FileAction, FileOperationResult
from grandpa.files.parser import FileParser
from grandpa.files.safety import FileSafetyPolicy

__all__ = [
    "FileAction",
    "FileAutomation",
    "FileExecutor",
    "FileOperationResult",
    "FileParser",
    "FileSafetyPolicy",
    "handle_file_automation",
]
