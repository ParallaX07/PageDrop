"""Shared job chrome for tool shells (O6 / O15).

Owns begin_job / end_job / progress / toast / result-action handlers.
The Tools catalogue keeps toast only — BusyOverlay + ResultActionsBar live here
on ``ToolShellWindow`` (and similar hosts).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from pagedrop.core.jobs import CancelToken, JobCancelledError, SerializedJobRunner
from pagedrop.core.thread_policy import FITZ_LOCK
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.dialogs import prompt_cancel_running_job
from pagedrop.ui.result_actions import (
    ResultActionsBar,
    open_in_editor,
    preview_pdf,
    show_in_folder,
)


def _progress_message(message: str) -> str:
    if message.endswith("…"):
        return message
    return f"{message.rstrip('.')}…"


_LOCK_WAIT_MESSAGE = "Waiting for running job…"
_LOCK_FIRST_TRY_S = 0.05
_LOCK_TICK_MS = 50
# Timed (not non-blocking): per-page jobs free FITZ_LOCK for ~1 ms between
# pages, which only a thread already sleeping in acquire can catch.
_LOCK_TICK_ACQUIRE_S = 0.02


class _LockNotHeldError(JobCancelledError):
    """Cancelled while re-taking ``FITZ_LOCK``; the GUI thread does not hold it."""


def _acquire_pumped(
    flags: QEventLoop.ProcessEventsFlag, token: CancelToken | None = None
) -> None:
    """Take ``FITZ_LOCK`` on the GUI thread, pumping events while a job holds it.

    The uncontended path pumps nothing. Cancelling *token* during the wait
    raises ``_LockNotHeldError`` without holding the lock.
    """
    while not FITZ_LOCK.acquire(timeout=_LOCK_TICK_ACQUIRE_S):
        if token is not None and token.is_cancelled():
            raise _LockNotHeldError("Job cancelled")
        QApplication.processEvents(flags)


def gui_fitz_call(fn: Callable, *args, **kwargs):
    """Run a GUI-thread PDF probe under ``FITZ_LOCK`` without freezing the window.

    While a job holds the lock, painting, timers and window-system events keep
    running but user input is not processed, so nothing can re-enter the
    caller. Exceptions from *fn* propagate unchanged. Never open a modal inside
    *fn*; keep prompts and retry loops outside the call.
    """
    _acquire_pumped(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        return fn(*args, **kwargs)
    finally:
        FITZ_LOCK.release()


def fitz_lock_released(fn: Callable, token: CancelToken | None = None):
    """Wrap a modal callback so the GUI thread's ``FITZ_LOCK`` is free while it runs.

    The lock is re-taken afterwards with an event-pumping wait (all events, so
    the busy overlay's Cancel works). Cancelling *token* during that wait raises
    ``JobCancelledError`` without the lock held.
    """

    def wrapper(*args, **kwargs):
        FITZ_LOCK.release()
        try:
            return fn(*args, **kwargs)
        finally:
            _acquire_pumped(QEventLoop.ProcessEventsFlag.AllEvents, token)

    return wrapper


def run_with_fitz_lock(
    host,
    token: CancelToken,
    *,
    message: str,
    probe: Callable[[], object],
    done: Callable[[object, Exception | None], None],
) -> None:
    """Run GUI-thread PDF *probe* under ``FITZ_LOCK`` without freezing the window.

    Takes the lock with a short timed acquire; if a job holds it, shows
    "Waiting for running job…" and retries from a timer so the event loop keeps
    running. *probe* runs with the lock held (wrap modal dialogs it opens in
    ``fitz_lock_released``). The lock is released before ``done(result, error)``
    runs, so ``done`` may open dialogs. Cancelling *token* during the wait calls
    ``done(None, JobCancelledError)``.
    """

    def finish() -> None:
        result: object = None
        error: Exception | None = None
        held = True
        try:
            result = probe()
        except _LockNotHeldError as exc:
            held = False
            error = exc
        except Exception as exc:
            error = exc
        finally:
            if held:
                FITZ_LOCK.release()
        done(result, error)

    if FITZ_LOCK.acquire(timeout=_LOCK_FIRST_TRY_S):
        finish()
        return

    host.set_job_progress(0.0, _LOCK_WAIT_MESSAGE)
    timer = QTimer(host if isinstance(host, QObject) else None)
    timer.setInterval(_LOCK_TICK_MS)

    def current() -> bool:
        # Closing the host ends the job itself; a stale tick must not end it twice.
        running = getattr(host, "is_job_running", None)
        if callable(running) and not running():
            return False
        return getattr(host, "_cancel_token", token) is token

    def tick() -> None:
        if token.is_cancelled():
            timer.stop()
            timer.deleteLater()
            if current():
                done(None, JobCancelledError("Job cancelled"))
            return
        if not FITZ_LOCK.acquire(timeout=_LOCK_TICK_ACQUIRE_S):
            return
        timer.stop()
        timer.deleteLater()
        if not current():
            FITZ_LOCK.release()
            return
        host.set_job_progress(0.0, message)
        finish()

    timer.timeout.connect(tick)
    timer.start()


def explain_busy_running(
    *,
    status_bar,
    toast: ToastOverlay,
    label: str,
) -> None:
    """Status + toast when close/Escape is blocked without a cancel token (O12)."""
    message = f"{label} still running…"
    status_bar.showMessage(message)
    toast.show_toast(message, kind="info")


class JobChromeMixin:
    """BusyOverlay + toast + ResultActionsBar lifecycle for tool hosts.

    Hosts must set ``WINDOW_TITLE``, implement ``statusBar()``, and after building
    UI assign ``_result_bar``, ``_busy_overlay``, ``_toast``, then call
    ``_wire_result_actions()``. Override ``_set_job_controls_enabled`` for
    surface-specific disable/enable (search vs drop zone / Run).
    """

    WINDOW_TITLE: str
    _editor: QWidget | None
    _job_running: bool
    _cancel_token: CancelToken | None
    _job_runner: SerializedJobRunner | None
    _result_bar: ResultActionsBar
    _busy_overlay: BusyOverlay
    _toast: ToastOverlay

    def _init_job_chrome_state(self) -> None:
        self._job_running = False
        self._cancel_token = None
        self._job_runner = None
        self._worker_pending = False
        self._worker_callbacks: list[Callable[[], None]] = []

    def worker_pending(self) -> bool:
        """True from worker start until its final signal, even after the job UI ended."""
        return self._worker_pending

    def when_worker_finished(self, callback: Callable[[], None]) -> None:
        """Run *callback* once the worker has really finished (now if none is pending)."""
        if self._worker_pending:
            self._worker_callbacks.append(callback)
        else:
            callback()

    def _worker_started(self) -> None:
        self._worker_pending = True

    def _worker_finished(self) -> None:
        self._worker_pending = False
        callbacks, self._worker_callbacks = self._worker_callbacks, []
        for callback in callbacks:
            callback()

    def _make_job_chrome_widgets(self) -> None:
        """Create result bar, busy overlay, and toast on *self*."""
        assert isinstance(self, QWidget)
        self._result_bar = ResultActionsBar()
        self._busy_overlay = BusyOverlay(self)
        self._busy_overlay.set_cancellable(True)
        self._busy_overlay.cancelled.connect(self.cancel_active_job)
        self._toast = ToastOverlay(self)

    def _wire_result_actions(self) -> None:
        self._result_bar.preview_requested.connect(self._on_preview_result)
        self._result_bar.open_in_editor_requested.connect(self._on_open_result)
        self._result_bar.show_in_folder_requested.connect(self._on_show_folder)

    def _set_job_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable surface controls while a job runs. Override per host."""

    def show_toast(self, message: str, *, kind: str = "info") -> None:
        self._toast.show_toast(message, kind=kind)

    def job_runner(self) -> SerializedJobRunner:
        if self._job_runner is None:
            from pagedrop.ui.organize_tools import ensure_organize_runner

            self._job_runner = ensure_organize_runner()
        return self._job_runner

    def is_job_running(self) -> bool:
        return self._job_running

    def begin_job(self, message: str = "Working…") -> CancelToken:
        """Show BusyOverlay + progress status (must end with ``…``)."""
        message = _progress_message(message)
        self._job_running = True
        self._cancel_token = CancelToken()
        self._result_bar.clear()
        clear_error = getattr(self, "clear_job_error", None)
        if callable(clear_error):
            clear_error()
        set_precedence = getattr(self, "_set_result_precedence", None)
        if callable(set_precedence):
            set_precedence(False)
        self._busy_overlay.show_message(message)
        self._busy_overlay.set_cancel_ready()
        self._busy_overlay.set_progress(None)
        self.statusBar().showMessage(message)
        self._set_job_controls_enabled(False)
        return self._cancel_token

    def set_job_progress(
        self, fraction: float, message: str, *, total_known: bool = False
    ) -> None:
        if not self._job_running:
            return
        if message and message != "Done":
            message = _progress_message(message)
        if message == "Done":
            return
        self._busy_overlay.show_message(message or "Working…")
        self._busy_overlay.set_progress(fraction if total_known else None)
        self.statusBar().showMessage(message or "Working…")

    def end_job(
        self,
        *,
        status: str | None = None,
        toast: str | None = None,
        toast_kind: str = "info",
        result_path: str | None = None,
        error: str | None = None,
    ) -> None:
        self._job_running = False
        self._cancel_token = None
        self._result_bar.clear()
        self._busy_overlay.hide_overlay()
        self._set_job_controls_enabled(True)
        if error:
            self.statusBar().showMessage("Job failed")
            show_error = getattr(self, "show_job_error", None)
            if callable(show_error):
                show_error(error)
            self._toast.show_toast(toast or "Job failed", kind="error")
            QMessageBox.critical(self, self.WINDOW_TITLE, error)
            return
        if status:
            self.statusBar().showMessage(status)
        if toast:
            self._toast.show_toast(toast, kind=toast_kind)
        if result_path:
            self._result_bar.show_for(result_path, message=status)
        set_precedence = getattr(self, "_set_result_precedence", None)
        if callable(set_precedence):
            set_precedence(bool(result_path))

    def cancel_active_job(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()
            self._busy_overlay.set_cancelling()
            self.statusBar().showMessage("Cancelling…")

    def request_close(self) -> bool:
        """Return False to abort closing this tab while a job is running."""
        if not self._job_running:
            return True
        if not prompt_cancel_running_job(self, window_title=self.WINDOW_TITLE):
            return False
        self.cancel_active_job()
        self.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
        return True

    def _on_preview_result(self, path: str) -> None:
        preview_pdf(path, parent=self)

    def _on_open_result(self, path: str) -> None:
        editor = self._editor
        if editor is None:
            self._toast.show_toast("No editor window available", kind="error")
            return
        try:
            open_in_editor(path, editor)
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.WINDOW_TITLE,
                f"Could not open in editor:\n{exc}",
            )
            return
        self._toast.show_toast(f"Opened {Path(path).name}", kind="success")

    def _on_show_folder(self, path: str) -> None:
        if not show_in_folder(path):
            QMessageBox.warning(
                self,
                self.WINDOW_TITLE,
                "Could not open the folder for this file.",
            )
            return
        self._toast.show_toast("Opened folder", kind="info")

    def statusBar(self):  # noqa: N802
        raise NotImplementedError
