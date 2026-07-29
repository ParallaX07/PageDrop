"""Shared job chrome for Tools catalogue and tool shells (O6).

Owns begin_job / end_job / progress / toast / result-action handlers so catalogue
and shell surfaces stay distinct widgets but share one behavior path.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QWidget

from pagedrop.core.jobs import CancelToken, SerializedJobRunner
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.dialogs import prompt_cancel_running_job
from pagedrop.ui.result_actions import (
    ResultActionsBar,
    open_in_editor,
    preview_pdf,
    show_in_folder,
)
from pagedrop.utils.temp_manager import TempManager


def _progress_message(message: str) -> str:
    if message.endswith("…"):
        return message
    return f"{message.rstrip('.')}…"


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

            self._job_runner = ensure_organize_runner(TempManager())
        return self._job_runner

    def is_job_running(self) -> bool:
        return self._job_running

    def begin_job(self, message: str = "Working…") -> CancelToken:
        """Show BusyOverlay + progress status (must end with ``…``)."""
        message = _progress_message(message)
        self._job_running = True
        self._cancel_token = CancelToken()
        self._result_bar.clear()
        self._busy_overlay.show_message(message)
        self.statusBar().showMessage(message)
        self._set_job_controls_enabled(False)
        return self._cancel_token

    def set_job_progress(self, _fraction: float, message: str) -> None:
        if not self._job_running:
            return
        if message and message != "Done":
            message = _progress_message(message)
        if message == "Done":
            return
        self._busy_overlay.show_message(message or "Working…")
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
            self._toast.show_toast(toast or "Job failed", kind="error")
            QMessageBox.critical(self, self.WINDOW_TITLE, error)
            return
        if status:
            self.statusBar().showMessage(status)
        if toast:
            self._toast.show_toast(toast, kind=toast_kind)
        if result_path:
            # Same copy as status when provided (multi-output honesty, O12).
            self._result_bar.show_for(result_path, message=status)

    def cancel_active_job(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()

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
