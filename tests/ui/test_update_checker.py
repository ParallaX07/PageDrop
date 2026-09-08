"""Focused ownership and scheduling checks for the process-wide updater."""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import UTC, datetime, timedelta

from pagedrop.ui import settings
from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.ui.update_storage import UpdateStorage
from pagedrop.utils.update_checker import RateLimitedError
from pagedrop.utils.update_checker import ReleaseInfo


def _release(payload: bytes = b"installer") -> ReleaseInfo:
    return ReleaseInfo(
        "1.2.3", "v1.2.3", "PageDrop-1.2.3-Setup.exe", "https://example.test/installer",
        "https://example.test/checksum", len(payload), "", hashlib.sha256(payload).hexdigest(),
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
