"""Safe modular Downloads Manager for Grandpa."""

from grandpa.downloads.automation import DownloadsAutomation, handle_downloads_command
from grandpa.downloads.models import DownloadAction, DownloadItem, DownloadResult
from grandpa.downloads.parser import DownloadsParser
from grandpa.downloads.safety import DownloadsSafetyPolicy
from grandpa.downloads.scanner import DownloadsScanner

__all__ = [
    "DownloadAction",
    "DownloadItem",
    "DownloadResult",
    "DownloadsAutomation",
    "DownloadsParser",
    "DownloadsSafetyPolicy",
    "DownloadsScanner",
    "handle_downloads_command",
]
