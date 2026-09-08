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
from pagedrop.ui.update_storage import UpdateStorage
from pagedrop.ui.update_messages import throttle_message, update_error_message
from pagedrop.utils.update_checker import (
    RateLimitedError,
    ReleaseDataError,
    ReleaseInfo,
    UpdateCancelledError,
    check_for_update,
    download_installer,
    parse_version,
)
from pagedrop.utils.update_windows import WindowsUpdateError, launch_installer

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


class _DownloadWorker(QRunnable):
    class Signals(QObject):
        progress = pyqtSignal(int, int)
        finished = pyqtSignal(object, object)

    def __init__(self, download, release: ReleaseInfo, destination: object) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._download, self._release, self._destination = download, release, destination
        self._cancel = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = self._download(self._release, self._destination, self._cancel, self.signals.progress.emit)
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
    download_progress = pyqtSignal(int, int)
    download_completed = pyqtSignal(object)
    download_failed_signal = pyqtSignal(str)
    download_cancelled = pyqtSignal()
    stopped = pyqtSignal()

    def __init__(
        self,
        app: QApplication,
        *,
        check: Callable[[str, threading.Event], ReleaseInfo | None] | None = None,
        download=None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        supported: bool | None = None,
        storage: UpdateStorage | None = None,
        launch=None,
    ) -> None:
        super().__init__(app)
        self._app = app
        self._check = check or (lambda version, cancel: check_for_update(version, cancel_event=cancel))
        self._download = download or (lambda release, destination, cancel, progress: download_installer(
            release, destination, cancel_event=cancel, progress=progress
        ))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._supported = sys.platform == "win32" if supported is None else supported
        self.storage = storage
        self._launch = launch or launch_installer
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._pool.setObjectName("PageDropUpdatePool")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_scheduled_check)
        self._state = UpdateState.IDLE
        self._release: ReleaseInfo | None = None
        self._worker: _CheckWorker | None = None
        self._download_worker: _DownloadWorker | None = None
        self._stopping = False
        self._next_due_monotonic: float | None = None
        self._server_retry_deadline: datetime | None = None
        self._last_error = ""
        self._handoff_error = ""
        self._clear_completed_pending_target()
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

    @property
    def last_error(self) -> str:
        """The current sanitized background failure, cleared by success."""
        return self._last_error

    @property
    def handoff_error(self) -> str:
        return self._handoff_error

    @property
    def check_block_reason(self) -> str:
        deadline = self._retry_deadline(self._now())
        if deadline and deadline > self._now():
            return throttle_message(deadline)
        return "PageDrop is closing. Open it again to check for updates."

    def set_automatic_enabled(self, enabled: bool) -> None:
        settings.set_automatic_update_checks_enabled(enabled)
        self.reschedule()

    def begin_download(self) -> bool:
        if self._state is not UpdateState.AVAILABLE:
            return False
        self._set_state(UpdateState.DOWNLOADING)
        return True

    def start_download(self) -> bool:
        """Begin an explicitly approved verified installer download."""
        deadline = self._retry_deadline(self._now())
        if deadline and deadline > self._now():
            self.download_failed_signal.emit(throttle_message(deadline))
            return False
        if self._release is None or not self.begin_download():
            return False
        try:
            if self.storage is None:
                self.storage = UpdateStorage()
            reusable = self.storage.reusable_installer(self._release)
        except Exception as exc:
            self.download_failed()
            self.download_failed_signal.emit(update_error_message(exc, operation="download"))
            return False
        if reusable is not None:
            self.download_finished()
            self.download_completed.emit(reusable)
            return True
        worker = _DownloadWorker(
            self._download, self._release, self.storage.destination(self._release)
        )
        self._download_worker = worker
        worker.signals.progress.connect(self.download_progress)
        worker.signals.finished.connect(self._download_finished)
        self._pool.start(worker)
        return True

    def cancel_download(self) -> bool:
        if self._download_worker is None:
            return False
        self._download_worker.cancel()
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

    def launch_ready_installer(self) -> bool:
        """Persist an attempted target then ask Windows to elevate the verified file."""
        if self._state is not UpdateState.HANDING_OFF or self._release is None or self.storage is None:
            return False
        try:
            installer = self.storage.reusable_installer(self._release)
        except Exception as exc:
            self._handoff_error = update_error_message(exc, operation="installation")
            self.handoff_failed()
            return False
        if installer is None:
            self._handoff_error = "The verified update installer is no longer available. Download it again."
            self._set_state(UpdateState.AVAILABLE)
            return False
        try:
            settings.set_pending_update_target_version(self._release.version)
            stored = settings._settings()
            stored.sync()
            if stored.status() != stored.Status.NoError:
                raise WindowsUpdateError("Could not record the pending update")
            self._launch(installer)
        except Exception as exc:
            settings.set_pending_update_target_version(None)
            settings._settings().sync()
            self._handoff_error = update_error_message(exc, operation="installation")
            self.handoff_failed()
            return False
        self._handoff_error = ""
        return True

    def request_check(self, *, manual: bool = False) -> bool:
        """Start one check, returning False when state/deadline disallows it."""
        if not self._supported or self._stopping or self._worker is not None or self._download_worker is not None:
            return False
        if self._state in {UpdateState.READY, UpdateState.PREPARING, UpdateState.HANDING_OFF}:
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
        if self._worker is None and self._download_worker is None:
            if self.storage is not None:
                self.storage.close()
            self.stopped.emit()
        elif self._worker is not None:
            self._worker.cancel()
        if self._download_worker is not None:
            self._download_worker.cancel()

    def _run_scheduled_check(self) -> None:
        if self._next_due_monotonic is not None and self._monotonic() < self._next_due_monotonic:
            self._timer.start(min(int((self._next_due_monotonic - self._monotonic()) * 1000), _MAX_TIMER_MS))
            return
        if not self.request_check():
            self.reschedule()

    def _check_finished(self, release: object, error: object) -> None:
        self._worker = None
        if self._stopping:
            self._finish_stop_if_idle()
            return
        now = self._now()
        if error is None:
            self._last_error = ""
            settings.set_last_successful_check_utc(now)
            settings.set_update_retry_after_utc(None)
            settings.set_server_retry_after_utc(None)
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
            if isinstance(error, RateLimitedError):
                self._record_throttle(error, now)
            server_retry = self._retry_deadline(now)
            if server_retry is not None:
                retry_at = max(retry_at, server_retry)
            settings.set_update_retry_after_utc(retry_at)
            self._set_state(UpdateState.AVAILABLE if self._release else UpdateState.IDLE)
            self._last_error = self.check_block_reason if isinstance(error, RateLimitedError) else update_error_message(error)
            self.check_failed.emit(self._last_error)
        settings._settings().sync()
        self.reschedule()

    def _download_finished(self, installer: object, error: object) -> None:
        self._download_worker = None
        if self._stopping:
            self._finish_stop_if_idle()
            return
        if error is None:
            self.download_finished()
            self.download_completed.emit(installer)
        else:
            self.download_failed()
            if isinstance(error, UpdateCancelledError):
                self.download_cancelled.emit()
                self.reschedule()
                return
            if isinstance(error, RateLimitedError):
                self._record_throttle(error, self._now())
            self.download_failed_signal.emit(
                self.check_block_reason if isinstance(error, RateLimitedError)
                else update_error_message(error, operation="download")
            )
        self.reschedule()

    def _finish_stop_if_idle(self) -> None:
        if self._worker is not None or self._download_worker is not None:
            return
        if self.storage is not None:
            self.storage.close()
        self.stopped.emit()

    def _now(self) -> datetime:
        value = self._clock()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _retry_deadline(self, now: datetime) -> datetime | None:
        stored = settings.server_retry_after_utc()
        if self._server_retry_deadline is not None:
            return max(self._server_retry_deadline, stored) if stored else self._server_retry_deadline
        return stored

    def _record_throttle(self, error: RateLimitedError, now: datetime) -> None:
        deadline = error.retry_after or now + timedelta(minutes=1)
        deadline = max(now + timedelta(seconds=1), deadline)
        previous = self._retry_deadline(now)
        self._server_retry_deadline = max(deadline, previous) if previous else deadline
        settings.set_server_retry_after_utc(self._server_retry_deadline)
        settings._settings().sync()

    def _due_at(self, now: datetime) -> datetime:
        success = settings.last_successful_check_utc()
        retry = settings.update_retry_after_utc()
        server = self._retry_deadline(now)
        if retry and retry > now + _IMPLAUSIBLE_FUTURE:
            retry = None
        if retry:
            due = retry
        else:
            due = now if success is None or success > now + _IMPLAUSIBLE_FUTURE else success + _SUCCESS_INTERVAL
        return max(due, server) if server else due

    def _is_due(self, now: datetime) -> bool:
        if self._next_due_monotonic is not None:
            return self._monotonic() >= self._next_due_monotonic
        return now >= self._due_at(now)

    def _set_state(self, state: UpdateState) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state.value)

    def _clear_completed_pending_target(self) -> None:
        target = settings.pending_update_target_version()
        if not target:
            return
        try:
            if parse_version(self._app.applicationVersion()) >= parse_version(target):
                settings.set_pending_update_target_version(None)
                settings._settings().sync()
        except ReleaseDataError:
            # Keep an invalid target: it must never be mistaken for a completed update.
            return
