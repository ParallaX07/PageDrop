"""Phase U6 Windows primitives and handoff regressions."""

from __future__ import annotations

import hashlib

import pytest

import pagedrop.utils.update_windows as update_windows
from pagedrop.ui import settings
from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.ui.update_storage import UpdateStorage
from pagedrop.utils.update_checker import ReleaseInfo
from pagedrop.utils.update_windows import WindowsUpdateError, launch_installer


def _release() -> ReleaseInfo:
    payload = b"installer"
    return ReleaseInfo(
        "1.2.3", "v1.2.3", "PageDrop-1.2.3-Setup.exe", "https://example.test/installer",
        "https://example.test/installer.sha256", len(payload), "", hashlib.sha256(payload).hexdigest(),
    )


def test_non_windows_launch_is_capability_detected(tmp_path):
    with pytest.raises(WindowsUpdateError, match="Windows"):
        launch_installer(tmp_path / "PageDrop-1.2.3-Setup.exe")


class _Function:
    def __init__(self, result, callback=None):
        self.result = result
        self.callback = callback
        self.argtypes = self.restype = None

    def __call__(self, *args):
        if self.callback is not None:
            self.callback(*args)
        return self.result


def test_windows_launch_uses_only_fixed_arguments_and_closes_handle(tmp_path, monkeypatch):
    installer = tmp_path / "PageDrop-1.2.3-Setup.exe"
    installer.write_bytes(b"installer")
    calls = []

    class Shell32:
        def __init__(self):
            self.ShellExecuteExW = _Function(1, self.execute)

        def execute(self, pointer):
            info = pointer._obj
            calls.append((info.lpVerb, info.lpFile, info.lpParameters, info.fMask))
            info.hProcess = 99

    class Kernel32:
        def __init__(self):
            self.CloseHandle = _Function(1, lambda handle: calls.append(("close", handle)))

    shell32, kernel32 = Shell32(), Kernel32()
    monkeypatch.setattr(update_windows.sys, "platform", "win32")
    monkeypatch.setattr(
        update_windows.ctypes, "WinDLL", lambda name, **_: shell32 if name == "shell32" else kernel32,
        raising=False,
    )

    launch_installer(installer)

    assert calls[0] == (
        "runas", str(installer.resolve()), "/NORESTART /NOCLOSEAPPLICATIONS /NORESTARTAPPLICATIONS", 0x40,
    )
    assert calls[1] == ("close", 99)


def test_windows_uac_refusal_is_typed(tmp_path, monkeypatch):
    installer = tmp_path / "PageDrop-1.2.3-Setup.exe"
    installer.write_bytes(b"installer")

    class Shell32:
        ShellExecuteExW = _Function(0)

    monkeypatch.setattr(update_windows.sys, "platform", "win32")
    monkeypatch.setattr(update_windows.ctypes, "WinDLL", lambda *_args, **_kwargs: Shell32(), raising=False)
    monkeypatch.setattr(update_windows.ctypes, "get_last_error", lambda: 1223, raising=False)

    with pytest.raises(update_windows.UpdateLaunchCancelledError, match="UAC"):
        launch_installer(installer)


def test_windows_mutex_is_held_until_explicit_close(monkeypatch):
    calls = []

    class Kernel32:
        CreateMutexW = _Function(41, lambda *_: calls.append("create"))
        CloseHandle = _Function(1, lambda handle: calls.append(("close", handle)))

    monkeypatch.setattr(update_windows.sys, "platform", "win32")
    monkeypatch.setattr(update_windows.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32(), raising=False)
    mutex = update_windows.UpdateMutex.acquire()
    assert calls == ["create"]
    mutex.close()
    assert calls[1][0] == "close" and calls[1][1].value == 41


def test_handoff_revalidates_persists_and_clears_failed_attempt(qapp, tmp_path, isolated_settings):
    release = _release()
    storage = UpdateStorage(tmp_path / "updates")
    installer = storage.destination(release)
    installer.write_bytes(b"installer")
    launched = []
    coordinator = UpdateCoordinator(qapp, supported=True, storage=storage, launch=launched.append)
    coordinator._release = release
    coordinator._set_state(UpdateState.PREPARING)
    assert coordinator.begin_handoff()
    assert coordinator.launch_ready_installer()
    assert launched == [installer]
    assert settings.pending_update_target_version() == release.version

    coordinator._set_state(UpdateState.HANDING_OFF)
    coordinator._launch = lambda _: (_ for _ in ()).throw(WindowsUpdateError("UAC refused"))
    assert not coordinator.launch_ready_installer()
    assert coordinator.state is UpdateState.READY
    assert settings.pending_update_target_version() == ""
    storage.close()


def test_tampered_installer_keeps_ready_state(qapp, tmp_path, isolated_settings):
    release = _release()
    storage = UpdateStorage(tmp_path / "updates")
    installer = storage.destination(release)
    installer.write_bytes(b"tampered")
    coordinator = UpdateCoordinator(qapp, supported=True, storage=storage, launch=lambda _: None)
    coordinator._release = release
    coordinator._set_state(UpdateState.PREPARING)
    assert coordinator.begin_handoff()
    assert not coordinator.launch_ready_installer()
    assert coordinator.state is UpdateState.READY
    storage.close()


def test_older_restart_retains_pending_target(qapp, isolated_settings):
    qapp.setApplicationVersion("1.2.3")
    settings.set_pending_update_target_version("1.2.4")
    UpdateCoordinator(qapp, supported=False)
    assert settings.pending_update_target_version() == "1.2.4"

    qapp.setApplicationVersion("1.2.4")
    UpdateCoordinator(qapp, supported=False)
    assert settings.pending_update_target_version() == ""
