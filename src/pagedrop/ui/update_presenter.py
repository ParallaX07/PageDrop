"""One accessible, application-wide presentation for update choices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PyQt6.QtCore import QEvent, QObject, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from pagedrop.ui import settings
from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.utils.update_checker import REPOSITORY, ReleaseInfo

_RELEASE_PAGE = QUrl(f"https://github.com/{REPOSITORY}/releases")


class UpdateDialog(QDialog):
    """A small stateful dialog; its owner keeps exactly one instance alive."""

    def __init__(self, parent, coordinator: UpdateCoordinator) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self.setWindowTitle("PageDrop updates")
        self.setObjectName("UpdateDialog")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setObjectName("UpdateMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.notes = QPlainTextEdit()
        self.notes.setObjectName("UpdateReleaseNotes")
        self.notes.setReadOnly(True)
        self.notes.setAccessibleName("Release notes")
        self.notes.setMaximumHeight(160)
        layout.addWidget(self.notes)
        self.progress = QProgressBar()
        self.progress.setObjectName("UpdateDownloadProgress")
        self.progress.setAccessibleName("Update download progress")
        layout.addWidget(self.progress)
        self.buttons = QDialogButtonBox()
        layout.addWidget(self.buttons)

    def show_message(self, message: str, *, notes: str = "") -> None:
        self.message.setText(message)
        self.notes.setPlainText(notes)
        self.notes.setVisible(bool(notes))
        self.progress.hide()
        self._clear_buttons()

    def show_offer(self, release: ReleaseInfo) -> None:
        self.show_message(
            f"PageDrop {release.version} is available. You are running "
            f"{QApplication.instance().applicationVersion()}.",
            notes=release.notes,
        )
        self._button("Download update", self._start_download)
        self._button("Remind me tomorrow", self._remind)
        self._button("Skip this version", self._skip)

    def show_downloading(self, done: int = 0, total: int = 0, *, cancelling: bool = False) -> None:
        self.message.setText("Cancelling update download…" if cancelling else "Downloading update…")
        self.notes.hide()
        self.progress.setRange(0, max(total, 0))
        self.progress.setValue(done)
        self.progress.show()
        self._clear_buttons()
        if not cancelling:
            self._button("Cancel", self._cancel_download)

    def show_ready(self) -> None:
        self.show_message("The update has been verified and is ready to install.")
        self._button("Install and close PageDrop", self._install_later_phase)
        self._button("Later", self.reject)

    def _button(self, text: str, slot):
        button = self.buttons.addButton(text, QDialogButtonBox.ButtonRole.ActionRole)
        button.clicked.connect(slot)
        return button

    def _clear_buttons(self) -> None:
        for button in self.buttons.buttons():
            self.buttons.removeButton(button)
            button.deleteLater()

    def _remind(self) -> None:
        settings.set_update_remind_after_utc(datetime.now(UTC) + timedelta(days=1))
        self.reject()

    def _skip(self) -> None:
        if self._coordinator.release is not None:
            settings.set_skipped_update_version(self._coordinator.release.version)
        self.reject()

    def _cancel_download(self) -> None:
        if self._coordinator.cancel_download():
            self.show_downloading(cancelling=True)

    def _start_download(self) -> None:
        if self._coordinator.start_download():
            self.show_downloading()

    def _install_later_phase(self) -> None:
        if self._manager.prepare_for_installation(self):
            self.show_message("PageDrop is ready to close for installation.")


class UpdatePresenter(QObject):
    """Connect one coordinator to one movable dialog across editor windows."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self._manager = manager
        self._coordinator = manager.update_coordinator
        self._dialog: UpdateDialog | None = None
        self._manual = False
        self._manual_no_release = False
        self._pending_offer = False
        app = QApplication.instance()
        app.installEventFilter(self)
        self._coordinator.release_available.connect(self._on_release_available)
        self._coordinator.check_succeeded.connect(self._on_check_succeeded)
        self._coordinator.no_published_release.connect(self._on_no_published_release)
        self._coordinator.check_failed.connect(self._on_check_failed)
        self._coordinator.download_progress.connect(self._on_download_progress)
        self._coordinator.download_completed.connect(self._on_download_completed)
        self._coordinator.download_failed_signal.connect(self._on_download_failed)

    @property
    def dialog(self) -> UpdateDialog | None:
        return self._dialog

    def check_manually(self, parent) -> None:
        if not self._coordinator.supported:
            self._show_message(
                parent,
                "Updates are available only in the packaged Windows version.",
                release_page=True,
            )
            return
        if self._coordinator.state is UpdateState.READY:
            self._show_ready(parent)
            return
        self._manual = True
        if self._coordinator.request_check(manual=True):
            self._show_message(parent, "Checking for updates…")
        elif self._coordinator.state is UpdateState.CHECKING:
            self._show_message(parent, "Checking for updates…")
        else:
            self._show_message(parent, "Update checks are temporarily unavailable. Try again later.")

    def window_closed(self, window) -> None:
        if self._dialog is not None and self._dialog.parentWidget() is window:
            self._dialog.setParent(self._presenter_window())
            self._dialog.show()
        self._present_pending_offer()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.WindowActivate, QEvent.Type.Hide, QEvent.Type.Show}:
            QTimer.singleShot(0, self._present_pending_offer)
        return super().eventFilter(obj, event)

    def _on_release_available(self, release: ReleaseInfo) -> None:
        if self._manual:
            self._show_offer(self._presenter_window())
        else:
            self._pending_offer = True
            self._present_pending_offer()

    def _on_check_succeeded(self, release: object) -> None:
        if self._manual and release is None and not self._manual_no_release:
            self._show_message(self._presenter_window(), "PageDrop is up to date.")
        self._manual = False
        self._manual_no_release = False

    def _on_no_published_release(self) -> None:
        if self._manual:
            self._manual_no_release = True
            self._show_message(self._presenter_window(), "No published PageDrop release is available.")

    def _on_check_failed(self, message: str) -> None:
        if self._manual:
            self._show_message(self._presenter_window(), message)
        self._manual = False

    def _on_download_progress(self, done: int, total: int) -> None:
        if self._dialog is not None:
            self._dialog.show_downloading(done, total)

    def _on_download_completed(self, installer: object) -> None:
        self._show_ready(self._presenter_window())

    def _on_download_failed(self, message: str) -> None:
        self._show_message(self._presenter_window(), message)
        if self._coordinator.release is not None and self._dialog is not None:
            self._dialog._button("Try again", lambda: self._dialog.show_offer(self._coordinator.release))

    def _present_pending_offer(self) -> None:
        if not self._pending_offer or not self._can_interrupt():
            return
        release = self._coordinator.release
        if release is None or self._suppressed(release):
            return
        self._pending_offer = False
        self._show_offer(self._presenter_window())

    def _suppressed(self, release: ReleaseInfo) -> bool:
        remind = settings.update_remind_after_utc()
        return settings.skipped_update_version() == release.version or (remind is not None and remind > datetime.now(UTC))

    def _can_interrupt(self) -> bool:
        window = self._presenter_window()
        if window is None or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return False
        for editor in self._manager.windows:
            for widget in editor.findChildren(QWidget):
                running = getattr(widget, "is_job_running", None)
                if callable(running) and running():
                    return False
        tab = window._active_tab()
        if tab is None or tab.is_preview_visible():
            return False
        focus = QApplication.focusWidget()
        return focus is None or not (focus.inherits("QLineEdit") or focus.inherits("QTextEdit")) or not focus.hasFocus()

    def _presenter_window(self):
        active = QApplication.activeWindow()
        return active if active in self._manager.windows else self._manager.primary

    def _ensure_dialog(self, parent) -> UpdateDialog:
        if self._dialog is None:
            self._dialog = UpdateDialog(parent, self._coordinator)
            self._dialog.finished.connect(lambda _: setattr(self, "_dialog", None))
        elif self._dialog.parentWidget() is not parent and parent is not None:
            self._dialog.setParent(parent)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        return self._dialog

    def _show_message(self, parent, message: str, *, release_page: bool = False) -> None:
        dialog = self._ensure_dialog(parent)
        dialog.show_message(message)
        if release_page:
            dialog._button("Open releases page", lambda: QDesktopServices.openUrl(_RELEASE_PAGE))
            dialog._button("Close", dialog.reject)

    def _show_offer(self, parent) -> None:
        release = self._coordinator.release
        if release is not None:
            self._ensure_dialog(parent).show_offer(release)

    def _show_ready(self, parent) -> None:
        self._ensure_dialog(parent).show_ready()
