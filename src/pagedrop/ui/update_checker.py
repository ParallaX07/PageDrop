"""Application-wide scheduling and ownership for Windows update checks."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from pagedrop.ui import settings
from pagedrop.utils.update_checker import (
    RateLimitedError,
    ReleaseInfo,
    ReleaseNotFoundError,
    check_for_update,
)

_STARTUP_DELAY_MS = 5_000
_SUCCESS_INTERVAL = timedelta(hours=24)
_FAILURE_INTERVAL = timedelta(hours=1)
_IMPLAUSIBLE_FUTURE = timedelta(hours=48)
_MAX_TIMER_MS = 2_147_483_647


class UpdateState(StrEnum):
    IDLE = "idle"
    CHECKING = "checking"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    READY = "ready"
    PREPARING = "preparing"
    HANDING_OFF = "handing_off"


class _CheckWorker(QRunnable):
    class Signals(QObject):
        finished = pyqtSignal(object, object)

    def __init__(
        self,
        check: Callable[[str, threading.Event], ReleaseInfo | None],
        version: str,
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._check = check
        self._version = version
        self._cancel = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result: object = self._check(self._version, self._cancel)
        except BaseException as exc:  # Worker must always notify its owner.
            self.signals.finished.emit(None, exc)
        else:
            self.signals.finished.emit(result, None)


class UpdateCoordinator(QObject):
    """The sole updater owner for one application process.

    It deliberately presents no UI. Windows subscribe to these signals in U4;
    requests and worker lifetime stay here so multiple windows cannot race.
    """

    state_changed = pyqtSignal(str)
    release_available = pyqtSignal(object)
    check_succeeded = pyqtSignal(object)
    check_failed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(
        self,
        app: QApplication,
        *,
        check: Callable[[str, threading.Event], ReleaseInfo | None] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        supported: bool | None = None,
    ) -> None:
        super().__init__(app)
        self._app = app
        self._check = check or (lambda version, cancel: check_for_update(version, cancel_event=cancel))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._supported = sys.platform == "win32" if supported is None else supported
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._pool.setObjectName("PageDropUpdatePool")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_scheduled_check)
        self._state = UpdateState.IDLE
        self._release: ReleaseInfo | None = None
        self._worker: _CheckWorker | None = None
        self._stopping = False
        self._next_due_monotonic: float | None = None
        self._server_retry_deadline: datetime | None = None
        if self._supported:
            self.reschedule()

    @property
    def state(self) -> UpdateState:
        return self._state

    @property
    def release(self) -> ReleaseInfo | None:
        return self._release

    @property
    def supported(self) -> bool:
        return self._supported

    def set_automatic_enabled(self, enabled: bool) -> None:
        settings.set_automatic_update_checks_enabled(enabled)
        self.reschedule()

    def begin_download(self) -> bool:
        if self._state is not UpdateState.AVAILABLE:
            return False
        self._set_state(UpdateState.DOWNLOADING)
        return True

    def download_finished(self) -> bool:
        if self._state is not UpdateState.DOWNLOADING:
            return False
        self._set_state(UpdateState.READY)
        return True

    def download_failed(self) -> bool:
        if self._state is not UpdateState.DOWNLOADING:
            return False
        self._set_state(UpdateState.AVAILABLE)
        return True

    def begin_preparation(self) -> bool:
        if self._state is not UpdateState.READY:
            return False
        self._set_state(UpdateState.PREPARING)
        return True

    def preparation_failed(self) -> bool:
        if self._state is not UpdateState.PREPARING:
            return False
        self._set_state(UpdateState.READY)
        return True

    def begin_handoff(self) -> bool:
        if self._state is not UpdateState.PREPARING:
            return False
        self._set_state(UpdateState.HANDING_OFF)
        return True

    def handoff_failed(self) -> bool:
        if self._state is not UpdateState.HANDING_OFF:
            return False
        self._set_state(UpdateState.READY)
        return True

    def request_check(self, *, manual: bool = False) -> bool:
        """Start one check, returning False when state/deadline disallows it."""
        if not self._supported or self._stopping or self._worker is not None:
            return False
        if self._state is UpdateState.READY:
            return False  # A verified download stays available until U6 consumes it.
        now = self._now()
        retry_after = self._retry_deadline(now)
        if retry_after is not None and now < retry_after:
            return False
        if not manual and not settings.automatic_update_checks_enabled():
            return False
        if not manual and not self._is_due(now):
            return False
        settings.set_last_check_attempt_utc(now)
        settings._settings().sync()
        self._set_state(UpdateState.CHECKING)
        worker = _CheckWorker(self._check, self._app.applicationVersion())
        self._worker = worker
        worker.signals.finished.connect(self._check_finished)
        self._pool.start(worker)
        return True

    def reschedule(self) -> None:
        self._timer.stop()
        self._next_due_monotonic = None
        if self._stopping or not self._supported or not settings.automatic_update_checks_enabled():
            return
        now = self._now()
        due = self._due_at(now)
        delay = _STARTUP_DELAY_MS if due <= now else max(0, int((due - now).total_seconds() * 1000))
        self._next_due_monotonic = self._monotonic() + delay / 1000
        self._timer.start(min(delay, _MAX_TIMER_MS))

    def stop(self) -> None:
        """Cancel owned work; ``stopped`` fires only after the worker exits."""
        self._stopping = True
        self._timer.stop()
        if self._worker is None:
            self.stopped.emit()
        else:
            self._worker.cancel()

    def _run_scheduled_check(self) -> None:
        if self._next_due_monotonic is not None and self._monotonic() < self._next_due_monotonic:
            self._timer.start(min(int((self._next_due_monotonic - self._monotonic()) * 1000), _MAX_TIMER_MS))
            return
        self.request_check()

    def _check_finished(self, release: object, error: object) -> None:
        self._worker = None
        if self._stopping:
            self.stopped.emit()
            return
        now = self._now()
        if isinstance(error, ReleaseNotFoundError):
            release, error = None, None
        if error is None:
            settings.set_last_successful_check_utc(now)
            settings.set_update_retry_after_utc(None)
            self._server_retry_deadline = None
            if isinstance(release, ReleaseInfo):
                self._release = release
                self._set_state(UpdateState.AVAILABLE)
                self.release_available.emit(release)
            else:
                self._release = None
                self._set_state(UpdateState.IDLE)
            self.check_succeeded.emit(release)
        else:
            retry_at = now + _FAILURE_INTERVAL
            if isinstance(error, RateLimitedError) and error.retry_after is not None:
                retry_at = max(retry_at, error.retry_after.astimezone(UTC))
            stored_retry = settings.update_retry_after_utc()
            if stored_retry is not None:
                retry_at = max(retry_at, stored_retry)
            self._server_retry_deadline = retry_at
            settings.set_update_retry_after_utc(retry_at)
            self._set_state(UpdateState.AVAILABLE if self._release else UpdateState.IDLE)
            self.check_failed.emit(str(error))
        settings._settings().sync()
        self.reschedule()

    def _now(self) -> datetime:
        value = self._clock()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _retry_deadline(self, now: datetime) -> datetime | None:
        stored = settings.update_retry_after_utc()
        if self._server_retry_deadline is not None:
            return max(self._server_retry_deadline, stored) if stored else self._server_retry_deadline
        return stored

    def _due_at(self, now: datetime) -> datetime:
        success = settings.last_successful_check_utc()
        if success is None or success > now + _IMPLAUSIBLE_FUTURE:
            return now
        retry = self._retry_deadline(now)
        return max(success + _SUCCESS_INTERVAL, retry) if retry else success + _SUCCESS_INTERVAL

    def _is_due(self, now: datetime) -> bool:
        if self._next_due_monotonic is not None:
            return self._monotonic() >= self._next_due_monotonic
        return now >= self._due_at(now)

    def _set_state(self, state: UpdateState) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state.value)
