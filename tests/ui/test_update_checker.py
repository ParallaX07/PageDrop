"""Focused ownership and scheduling checks for the process-wide updater."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from pagedrop.ui import settings
from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.utils.update_checker import RateLimitedError


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
