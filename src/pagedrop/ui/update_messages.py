"""Safe, actionable text shared by updater dialogs and Preferences."""

from datetime import datetime

from pagedrop.utils.update_checker import (
    RateLimitedError, ReleaseDataError, ReleaseNotFoundError,
    UpdateCancelledError, UpdateNetworkError, UpdateStorageError,
    UpdateTimeoutError, UpdateVerificationError,
)
from pagedrop.utils.update_windows import UpdateLaunchCancelledError, WindowsUpdateError


def throttle_message(deadline: datetime) -> str:
    local = deadline.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"The update service is limiting requests. Try again after {local}."


def update_error_message(error: object, *, operation: str = "check") -> str:
    if isinstance(error, UpdateLaunchCancelledError):
        return "Installation was canceled. Your documents remain open and the verified update is ready to try again."
    if isinstance(error, WindowsUpdateError):
        return "Windows could not start installation. Your documents remain open. Try again or use the releases page."
    if isinstance(error, UpdateCancelledError):
        return "Update download canceled. You can download it again when you are ready."
    if isinstance(error, RateLimitedError):
        return throttle_message(error.retry_after) if error.retry_after else "The update service is limiting requests. Try again in one minute."
    if isinstance(error, ReleaseNotFoundError):
        return "No published update information is available. You can check the releases page."
    if isinstance(error, UpdateVerificationError):
        return "The update download could not be verified. The unverified file was deleted. Try downloading again."
    if isinstance(error, ReleaseDataError):
        return "The update information could not be verified. Try again later or check the releases page."
    if isinstance(error, (UpdateStorageError, OSError)):
        return "PageDrop could not access its update files. Check available disk space and folder permissions, then try again."
    if isinstance(error, UpdateTimeoutError):
        return f"The update {operation} timed out. Check your internet connection and try again."
    if isinstance(error, UpdateNetworkError):
        return "PageDrop could not reach the update service. Check your internet connection and try again."
    return f"An unexpected problem stopped the update {operation}. Please try again or check the releases page."
