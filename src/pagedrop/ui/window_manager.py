from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.update_checker import UpdateCoordinator, UpdateState
from pagedrop.ui.update_presenter import UpdatePresenter

if TYPE_CHECKING:
    from pagedrop.ui.main_window import MainWindow


class WindowManager(QObject):
    """Registry of open editor windows and factory for new ``MainWindow`` instances.

    Geometry policy: only the *primary* editor (first registered window) persists
    size/position on close. Secondary closers must not overwrite next-launch
    restore. Quit runs when the last registered editor closes
    (``QuitOnLastWindowClosed`` is False).
    """

    last_window_closing = pyqtSignal()

    def __init__(self, app: QApplication, *, update_mutex=None, update_mutex_error: str = "") -> None:
        super().__init__()
        self._app = app
        self._windows: set[MainWindow] = set()
        self._primary: MainWindow | None = None
        self._preparing_installation = False
        self._prepared_shutdown = False
        self._update_mutex = update_mutex
        self._update_mutex_error = update_mutex_error
        self.update_coordinator = UpdateCoordinator(app)
        self.update_presenter = UpdatePresenter(self)

    @property
    def windows(self) -> frozenset[MainWindow]:
        return frozenset(self._windows)

    @property
    def primary(self) -> MainWindow | None:
        return self._primary

    def is_primary(self, window: MainWindow) -> bool:
        return window is self._primary

    def open_new_window(self, initial_tab: PdfTab | None = None) -> MainWindow | None:
        """Create, register, and show a new editor window."""
        if self._preparing_installation:
            return None
        return self.create_window(initial_tab, show=True)

    @property
    def preparing_installation(self) -> bool:
        return self._preparing_installation

    @property
    def prepared_shutdown(self) -> bool:
        """True only after U6 has handed the installer to Windows."""
        return self._prepared_shutdown

    def prepare_for_installation(self, parent: QWidget | None = None) -> bool:
        """Resolve process-wide work and dirty documents before U6 handoff."""
        if self._preparing_installation or not self.update_coordinator.begin_preparation():
            return False

        self._preparing_installation = True
        self._set_preparation_enabled(False)
        if self._has_running_jobs():
            self._preparation_failed(parent, "Finish or cancel running tasks before installing")
            return False

        discarded: set[PdfTab] = set()
        for window, tab in self._dirty_tabs():
            choice = window._prompt_unsaved_changes(tab)
            if choice == "cancel":
                self._preparation_failed(parent)
                return False
            if choice == "save":
                if not window._save_as(tab):
                    self._preparation_failed(parent)
                    return False
                # Installation preparation is the one lifecycle that needs a
                # completed save, rather than merely a dispatched editor job.
                window.wait_for_editor_job(tab)
                if tab.is_dirty:
                    self._preparation_failed(parent, "Could not save an open document")
                    return False
            else:
                # Discard authorizes the later prepared shutdown only. Keeping
                # the tab dirty makes a cancelled handoff fully reversible.
                discarded.add(tab)

        if self._has_running_jobs() or {tab for _, tab in self._dirty_tabs()} != discarded:
            self._preparation_failed(parent, "Open documents changed while preparing installation")
            return False
        return True

    def allow_prepared_shutdown(self) -> bool:
        """One-shot U6 hook, called only after Windows accepts installer launch."""
        if not self._preparing_installation:
            return False
        self._prepared_shutdown = True
        self._preparing_installation = False
        return True

    def cancel_installation_preparation(self) -> None:
        """Restore normal interaction after preparation or handoff failure."""
        self._prepared_shutdown = False
        self._preparing_installation = False
        self._set_preparation_enabled(True)
        if self.update_coordinator.state is UpdateState.HANDING_OFF:
            self.update_coordinator.handoff_failed()
        else:
            self.update_coordinator.preparation_failed()

    def handoff_update_installer(self, parent: QWidget | None = None) -> bool:
        """Launch only after U5 preparation, then perform the one-shot close."""
        if self._update_mutex_error or (self.update_coordinator.supported and self._update_mutex is None):
            self.cancel_installation_preparation()
            self.update_presenter.show_installation_error(
                "PageDrop could not safely prepare installation. Your documents remain open. Restart PageDrop and try again, or use the releases page."
            )
            return False
        if not self.update_coordinator.begin_handoff() or not self.update_coordinator.launch_ready_installer():
            self.cancel_installation_preparation()
            if self.update_coordinator.handoff_error:
                self.update_presenter.show_installation_error(self.update_coordinator.handoff_error)
            return False
        self.allow_prepared_shutdown()
        for window in tuple(self._windows):
            window.close()
        return True

    def _dirty_tabs(self):
        windows = [self._primary] if self._primary in self._windows else []
        windows.extend(window for window in self._windows if window is not self._primary)
        for window in windows:
            assert window is not None
            for index in range(window._tab_manager.count()):
                tab = window._tab_manager.widget(index)
                if isinstance(tab, PdfTab) and tab.is_dirty:
                    yield window, tab

    def _has_running_jobs(self) -> bool:
        for window in self._windows:
            for widget in (window, *window.findChildren(QWidget)):
                running = getattr(widget, "is_job_running", None)
                if callable(running) and running():
                    return True
        return False

    def _set_preparation_enabled(self, enabled: bool) -> None:
        for window in self._windows:
            window.setEnabled(enabled)

    def _preparation_failed(self, parent: QWidget | None, message: str | None = None) -> None:
        self._preparing_installation = False
        self._set_preparation_enabled(True)
        self.update_coordinator.preparation_failed()
        if message:
            self.update_presenter.show_installation_error(message + ". Your documents remain open.")

    def create_window(
        self,
        initial_tab: PdfTab | None = None,
        *,
        show: bool = False,
    ) -> MainWindow:
        from pagedrop.ui.main_window import MainWindow

        window = MainWindow(window_manager=self, initial_tab=initial_tab)
        self._register(window)
        if show:
            window.show()
        return window

    def window_for_widget(self, widget: QWidget) -> MainWindow | None:
        from pagedrop.ui.main_window import MainWindow

        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, MainWindow) and current in self._windows:
                return current
            current = current.parentWidget()
        return None

    def notify_window_closed(self, window: MainWindow) -> None:
        if window not in self._windows:
            return
        self._windows.discard(window)
        self.update_presenter.window_closed(window)
        if window is self._primary:
            self._primary = None
        if not self._windows:
            self._maybe_quit()

    def _register(self, window: MainWindow) -> None:
        self._windows.add(window)
        if self._primary is None:
            self._primary = window

    def _maybe_quit(self) -> None:
        self.last_window_closing.emit()
        self.update_coordinator.stopped.connect(self._app.quit)
        self.update_coordinator.stop()
