"""Small, optional Windows primitives used by the in-app updater."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

UPDATE_MUTEX_NAME = r"Global\PageDropInstallerMutex"
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_ERROR_CANCELLED = 1223
_INSTALLER_PARAMETERS = "/NORESTART /NOCLOSEAPPLICATIONS /NORESTARTAPPLICATIONS"


class WindowsUpdateError(RuntimeError):
    """A Windows update operation could not be completed safely."""


class UpdateLaunchCancelledError(WindowsUpdateError):
    """The user refused the UAC prompt."""


def _require_windows() -> None:
    if sys.platform != "win32":
        raise WindowsUpdateError("In-app installation is available only on Windows")


def _kernel32():
    _require_windows()
    return ctypes.WinDLL("kernel32", use_last_error=True)


class UpdateMutex:
    """A process-lifetime AppMutex handle; this does not prevent app instances."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    @classmethod
    def acquire(cls) -> "UpdateMutex":
        kernel32 = _kernel32()
        create = kernel32.CreateMutexW
        create.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        create.restype = ctypes.c_void_p
        handle = create(None, False, UPDATE_MUTEX_NAME)
        if not handle:
            raise WindowsUpdateError("Could not create the installer coordination mutex")
        return cls(handle)

    def close(self) -> None:
        if self._handle:
            kernel32 = _kernel32()
            close = kernel32.CloseHandle
            close.argtypes = (ctypes.c_void_p,)
            close.restype = ctypes.c_int
            close(ctypes.c_void_p(self._handle))
            self._handle = 0


def launch_installer(installer: Path) -> None:
    """Ask Windows to elevate a verified installer, then release its process handle."""
    _require_windows()
    path = installer.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".exe":
        raise WindowsUpdateError("Verified update installer is unavailable")

    class _ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint32), ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_uint32), ("hIconOrMonitor", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    execute = shell32.ShellExecuteExW
    execute.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    execute.restype = ctypes.c_int
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = os.fspath(path)
    info.lpParameters = _INSTALLER_PARAMETERS
    info.nShow = 1
    if not execute(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == _ERROR_CANCELLED:
            raise UpdateLaunchCancelledError("Update installation was cancelled at the UAC prompt")
        raise WindowsUpdateError("Windows could not start the update installer")
    if info.hProcess:
        close = _kernel32().CloseHandle
        close.argtypes = (ctypes.c_void_p,)
        close.restype = ctypes.c_int
        close(info.hProcess)
