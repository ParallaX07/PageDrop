"""Focused ownership and scheduling checks for the process-wide updater."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from datetime import UTC, datetime, timedelta

import pytest

from pagedrop.ui import settings
from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.ui.update_storage import UpdateStorage
from pagedrop.utils.update_checker import RateLimitedError
from pagedrop.utils.update_checker import ReleaseInfo
from pagedrop.utils.update_checker import UpdateStorageError


def _release(payload: bytes = b"installer") -> ReleaseInfo:
    return ReleaseInfo(
        "1.2.3", "v1.2.3", "PageDrop-1.2.3-Setup.exe", "https://example.test/installer",
        len(payload), "", hashlib.sha256(payload).hexdigest(),
    )


def test_manual_checks_share_one_worker(qtbot, qapp, isolated_settings):
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def check(version, cancel):
        calls.append(version)
        started.set()
        release.wait(1)
        return None

    coordinator = UpdateCoordinator(qapp, check=check, supported=True)

    assert coordinator.request_check(manual=True)
    assert started.wait(1)
    assert not coordinator.request_check(manual=True)
    release.set()
    qtbot.waitUntil(lambda: coordinator.state is UpdateState.IDLE)

    assert len(calls) == 1
    assert settings.last_check_attempt_utc() is not None
    assert settings.last_successful_check_utc() is not None


def test_server_retry_blocks_manual_requests(qtbot, qapp, isolated_settings):
    now = datetime(2026, 9, 8, tzinfo=UTC)

    def check(version, cancel):
        raise RateLimitedError(now + timedelta(hours=2))

    coordinator = UpdateCoordinator(qapp, check=check, clock=lambda: now, supported=True)
    assert coordinator.request_check(manual=True)
    qtbot.waitUntil(lambda: settings.update_retry_after_utc() is not None)

    assert not coordinator.request_check(manual=True)
    assert settings.update_retry_after_utc() == now + timedelta(hours=2)


def test_download_and_handoff_failures_preserve_the_offer(qapp, isolated_settings):
    coordinator = UpdateCoordinator(qapp, supported=True)
    coordinator._set_state(UpdateState.AVAILABLE)

    assert coordinator.begin_download()
    assert coordinator.download_failed()
    assert coordinator.begin_download()
    assert coordinator.download_finished()
    assert coordinator.begin_preparation()
    assert coordinator.preparation_failed()
    assert coordinator.begin_preparation()
    assert coordinator.begin_handoff()
    assert coordinator.handoff_failed()
    assert coordinator.state is UpdateState.READY


def test_stop_waits_for_owned_worker(qtbot, qapp, isolated_settings):
    cancelled = threading.Event()

    def check(version, cancel):
        while not cancel.wait(0.01):
            pass
        cancelled.set()
        return None

    coordinator = UpdateCoordinator(qapp, check=check, supported=True)
    assert coordinator.request_check(manual=True)
    with qtbot.waitSignal(coordinator.stopped, timeout=1_000):
        coordinator.stop()

    assert cancelled.is_set()


def test_storage_uses_isolated_sessions_and_revalidates_cache(tmp_path):
    first = UpdateStorage(tmp_path / "updates")
    second = UpdateStorage(tmp_path / "updates")
    release = _release()
    installer = first.destination(release)
    installer.write_bytes(b"installer")

    assert first.session_dir != second.session_dir
    assert first.reusable_installer(release) == installer
    installer.write_bytes(b"tampered!")
    assert first.reusable_installer(release) is None
    first.close()
    second.close()


def test_storage_cleanup_preserves_active_and_outside_files(tmp_path):
    root = tmp_path / "updates"
    active = UpdateStorage(root)
    release = _release()
    active_file = active.destination(release)
    active_file.write_bytes(b"installer")
    inactive = root / "abandoned"
    inactive.mkdir()
    partial = inactive / f"{release.installer_name}.part"
    expired = inactive / release.installer_name
    partial.write_bytes(b"partial")
    expired.write_bytes(b"installer")
    old = (datetime.now(UTC) - timedelta(days=8)).timestamp()
    expired.touch()
    os.utime(expired, (old, old))
    outside = tmp_path / release.installer_name
    outside.write_bytes(b"outside")

    cleaner = UpdateStorage(root)
    assert active_file.exists()
    assert not partial.exists()
    assert not expired.exists()
    assert outside.read_bytes() == b"outside"
    active.close()
    cleaner.close()


def test_automatic_scheduling_respects_disabled_daily_and_clock_rollback(qapp, isolated_settings):
    now = datetime(2026, 9, 8, tzinfo=UTC)
    ticks = [10.0]
    coordinator = UpdateCoordinator(
        qapp, clock=lambda: now, monotonic=lambda: ticks[0], supported=True
    )
    assert coordinator._next_due_monotonic == 15.0
    settings.set_last_successful_check_utc(now)
    coordinator.reschedule()
    assert coordinator._next_due_monotonic == 10.0 + 24 * 60 * 60
    settings.set_last_successful_check_utc(now + timedelta(days=3))
    coordinator.reschedule()
    assert coordinator._next_due_monotonic == 15.0
    coordinator.set_automatic_enabled(False)
    assert coordinator._next_due_monotonic is None


def test_unsupported_build_and_ready_state_reject_new_checks(qapp, isolated_settings):
    unsupported = UpdateCoordinator(qapp, supported=False)
    assert not unsupported.request_check(manual=True)
    coordinator = UpdateCoordinator(qapp, supported=True)
    coordinator._set_state(UpdateState.READY)
    assert not coordinator.request_check(manual=True)
    unsupported.stop()
    coordinator.stop()


def test_explicit_download_reaches_ready_and_reuses_verified_cache(qtbot, qapp, isolated_settings, tmp_path):
    release = _release()
    calls: list[str] = []

    def download(info, destination, cancel, progress):
        calls.append(info.version)
        progress(info.installer_size, info.installer_size)
        destination.write_bytes(b"installer")
        return destination

    coordinator = UpdateCoordinator(
        qapp,
        supported=True,
        storage=UpdateStorage(tmp_path / "updates"),
        download=download,
    )
    coordinator._release = release
    coordinator._set_state(UpdateState.AVAILABLE)

    with qtbot.waitSignal(coordinator.download_completed):
        assert coordinator.start_download()
    assert coordinator.state is UpdateState.READY
    assert calls == ["1.2.3"]
    coordinator.stop()


def test_first_failure_schedules_retry_but_manual_can_retry(qtbot, qapp, isolated_settings):
    from pagedrop.utils.update_checker import UpdateNetworkError
    now = datetime(2026, 9, 8, tzinfo=UTC)
    coordinator = UpdateCoordinator(qapp, clock=lambda: now, check=lambda *_: None, supported=True)
    coordinator._check_finished(None, UpdateNetworkError("secret URL"))
    assert coordinator._due_at(now) == now + timedelta(hours=1)
    assert not coordinator.request_check()
    assert "secret" not in coordinator.last_error
    with qtbot.waitSignal(coordinator.check_succeeded):
        assert coordinator.request_check(manual=True)
    assert coordinator.last_error == ""
    assert settings.update_retry_after_utc() is None
    coordinator.stop()


def test_throttle_without_deadline_survives_restart(qapp, isolated_settings):
    now = datetime(2026, 9, 8, tzinfo=UTC)
    coordinator = UpdateCoordinator(qapp, clock=lambda: now, supported=True)
    coordinator._check_finished(None, RateLimitedError(None))
    deadline = now + timedelta(minutes=1)
    assert settings.server_retry_after_utc() == deadline
    assert deadline.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z") in coordinator.last_error
    restarted = UpdateCoordinator(qapp, clock=lambda: now, supported=True)
    assert not restarted.request_check(manual=True)
    coordinator.stop()
    restarted.stop()


def test_support_requires_a_frozen_windows_build(qapp, isolated_settings, monkeypatch):
    import pagedrop.ui.update_checker as module

    def build(platform: str, frozen: bool) -> bool:
        with monkeypatch.context() as patch:  # Fake the platform only while constructing.
            patch.setattr(module.sys, "platform", platform)
            patch.setattr(module.sys, "frozen", frozen, raising=False)
            coordinator = UpdateCoordinator(qapp)
        coordinator.stop()
        return coordinator.supported

    assert not build("win32", False)
    assert build("win32", True)
    assert not build("linux", True)


def test_far_future_server_deadline_is_clamped_when_recorded(qapp, isolated_settings):
    now = datetime(2026, 9, 8, tzinfo=UTC)
    coordinator = UpdateCoordinator(qapp, clock=lambda: now, supported=True)
    coordinator._check_finished(None, RateLimitedError(datetime(2099, 1, 1, tzinfo=UTC)))
    limit = now + timedelta(hours=48)

    assert settings.server_retry_after_utc() == limit
    assert not coordinator.request_check(manual=True)
    assert limit.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z") in coordinator.check_block_reason
    coordinator.stop()


def test_stored_far_future_server_deadline_is_pinned_and_expires(qtbot, qapp, isolated_settings):
    now = [datetime(2026, 9, 8, tzinfo=UTC)]
    settings.set_server_retry_after_utc(datetime(2099, 1, 1, tzinfo=UTC))
    calls: list[str] = []

    def check(version, cancel):
        calls.append(version)
        return None

    coordinator = UpdateCoordinator(qapp, clock=lambda: now[0], check=check, supported=True)
    pinned = datetime(2026, 9, 8, tzinfo=UTC) + timedelta(hours=48)
    assert settings.server_retry_after_utc() == pinned
    assert not coordinator.request_check(manual=True)

    now[0] = pinned - timedelta(hours=1)  # A sliding limit would still block here.
    assert not coordinator.request_check(manual=True)
    assert settings.server_retry_after_utc() == pinned
    now[0] = pinned + timedelta(seconds=1)
    with qtbot.waitSignal(coordinator.check_succeeded):
        assert coordinator.request_check(manual=True)
    assert calls == [qapp.applicationVersion()]
    coordinator.stop()


def test_plausible_server_deadline_is_unchanged(qapp, isolated_settings):
    now = datetime(2026, 9, 8, tzinfo=UTC)
    deadline = now + timedelta(hours=47)
    coordinator = UpdateCoordinator(qapp, clock=lambda: now, supported=True)
    coordinator._check_finished(None, RateLimitedError(deadline))

    assert settings.server_retry_after_utc() == deadline
    assert coordinator._retry_deadline(now) == deadline
    coordinator.stop()


def _closed_session(root, name: str = "closed") -> Path:
    session = root / name
    session.mkdir(parents=True)
    return session


def test_new_session_adopts_a_closed_sessions_verified_installer(tmp_path):
    root = tmp_path / "updates"
    release = _release()
    closed = _closed_session(root)
    (closed / release.installer_name).write_bytes(b"installer")
    storage = UpdateStorage(root)

    adopted = storage.reusable_installer(release)

    assert adopted == storage.destination(release)
    assert adopted.read_bytes() == b"installer"
    assert not closed.exists()
    assert storage.reusable_installer(release) == adopted
    storage.close()


def test_tampered_installer_in_a_closed_session_is_deleted(tmp_path):
    root = tmp_path / "updates"
    release = _release()
    closed = _closed_session(root)
    (closed / release.installer_name).write_bytes(b"tampered!")
    storage = UpdateStorage(root)

    assert storage.reusable_installer(release) is None
    assert not storage.destination(release).exists()
    assert not closed.exists()
    storage.close()


def test_active_sessions_installer_is_not_taken(tmp_path):
    root = tmp_path / "updates"
    release = _release()
    owner = UpdateStorage(root)
    owner.destination(release).write_bytes(b"installer")
    other = UpdateStorage(root)

    assert other.reusable_installer(release) is None
    assert owner.destination(release).read_bytes() == b"installer"
    assert owner.session_dir.exists()
    owner.close()
    other.close()


def test_empty_inactive_session_folder_is_removed_but_unknown_files_keep_theirs(tmp_path):
    root = tmp_path / "updates"
    empty = _closed_session(root, "empty")
    keeper = _closed_session(root, "keeper")
    (keeper / "notes.txt").write_text("mine")
    storage = UpdateStorage(root)

    assert not empty.exists()
    assert (keeper / "notes.txt").read_text() == "mine"
    storage.reusable_installer(_release())
    assert (keeper / "notes.txt").exists()
    storage.close()


def test_symlinked_installer_in_a_closed_session_is_ignored(tmp_path):
    root = tmp_path / "updates"
    release = _release()
    closed = _closed_session(root)
    target = tmp_path / "elsewhere.exe"
    target.write_bytes(b"installer")
    try:
        (closed / release.installer_name).symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    storage = UpdateStorage(root)

    assert storage.reusable_installer(release) is None
    assert target.read_bytes() == b"installer"
    assert (closed / release.installer_name).is_symlink()
    storage.close()


def test_start_download_reuses_a_closed_sessions_installer(qtbot, qapp, isolated_settings, tmp_path):
    root = tmp_path / "updates"
    release = _release()
    closed = _closed_session(root)
    (closed / release.installer_name).write_bytes(b"installer")
    calls: list[str] = []
    coordinator = UpdateCoordinator(
        qapp, supported=True, storage=UpdateStorage(root),
        download=lambda *args: calls.append("download"),
    )
    coordinator._release = release
    coordinator._set_state(UpdateState.AVAILABLE)

    with qtbot.waitSignal(coordinator.download_completed) as done:
        assert coordinator.start_download()

    assert done.args == [coordinator.storage.destination(release)]
    assert coordinator.state is UpdateState.READY
    assert calls == []
    coordinator.stop()


def _lock_is_free(session) -> bool:
    from PyQt6.QtCore import QLockFile

    lock = QLockFile(str(session / ".active.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        return False
    lock.unlock()
    return True


def test_unreadable_installer_in_a_closed_session_is_skipped(tmp_path, monkeypatch):
    root = tmp_path / "updates"
    release = _release()
    closed = _closed_session(root)
    (closed / release.installer_name).write_bytes(b"installer")
    storage = UpdateStorage(root)

    def boom(*_args):
        raise OSError("disk error")

    with monkeypatch.context() as patch:
        patch.setattr(UpdateStorage, "_verified", staticmethod(boom))
        assert storage.reusable_installer(release) is None

    assert _lock_is_free(closed)
    # A later retry is not blocked and still adopts the installer once it reads fine.
    assert storage.reusable_installer(release) == storage.destination(release)
    storage.close()


def test_session_lock_is_released_when_a_step_raises(tmp_path, monkeypatch):
    root = tmp_path / "updates"
    release = _release()
    closed = _closed_session(root)
    (closed / release.installer_name).write_bytes(b"installer")
    storage = UpdateStorage(root)

    def boom(*_args):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(UpdateStorage, "_verified", staticmethod(boom))
    with pytest.raises(RuntimeError) as caught:  # The traceback keeps the frame alive here.
        storage.reusable_installer(release)

    assert _lock_is_free(closed)
    assert caught.value is not None
    storage.close()


def _flaky_lock(monkeypatch, *, failures: int):
    from PyQt6.QtCore import QLockFile

    from pagedrop.ui import update_storage

    calls = [0]

    class Flaky(QLockFile):
        def tryLock(self, timeout=0):  # noqa: N802
            calls[0] += 1
            if calls[0] <= failures:
                return False
            return super().tryLock(timeout)

    monkeypatch.setattr(update_storage, "QLockFile", Flaky)
    return calls


def test_new_session_retries_when_the_first_lock_attempt_fails(tmp_path, monkeypatch):
    root = tmp_path / "updates"
    calls = _flaky_lock(monkeypatch, failures=1)

    storage = UpdateStorage(root)

    assert calls[0] >= 2
    assert storage.session_dir.is_dir()
    assert [p for p in root.iterdir()] == [storage.session_dir]
    storage.close()


def test_new_session_gives_up_after_three_attempts_and_leaves_no_folder(tmp_path, monkeypatch):
    root = tmp_path / "updates"
    calls = _flaky_lock(monkeypatch, failures=99)

    with pytest.raises(UpdateStorageError):
        UpdateStorage(root)

    assert calls[0] == 3
    assert list(root.iterdir()) == []