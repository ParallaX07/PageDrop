from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from pagedrop.ui.pdf_tab import PdfTab

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

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._windows: set[MainWindow] = set()
        self._primary: MainWindow | None = None

    @property
    def windows(self) -> frozenset[MainWindow]:
        return frozenset(self._windows)

    @property
    def primary(self) -> MainWindow | None:
        return self._primary

    def is_primary(self, window: MainWindow) -> bool:
        return window is self._primary

    def open_new_window(self, initial_tab: PdfTab | None = None) -> MainWindow:
        """Create, register, and show a new editor window."""
        return self.create_window(initial_tab, show=True)

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
        self._app.quit()
