from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from pagedrop.ui.merge_window import MergeWindow
from pagedrop.ui.pdf_tab import PdfTab

if TYPE_CHECKING:
    from pagedrop.ui.main_window import MainWindow


class WindowManager(QObject):
    """Registry of open editor windows and factory for new ``MainWindow`` instances."""

    last_window_closing = pyqtSignal()

    _instance: WindowManager | None = None

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._windows: set[MainWindow] = set()

    @classmethod
    def init(cls, app: QApplication) -> WindowManager:
        cls._instance = cls(app)
        return cls._instance

    @classmethod
    def instance(cls) -> WindowManager:
        if cls._instance is None:
            raise RuntimeError("WindowManager.init() has not been called")
        return cls._instance

    @classmethod
    def instance_or_none(cls) -> WindowManager | None:
        return cls._instance

    @property
    def windows(self) -> frozenset[MainWindow]:
        return frozenset(self._windows)

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
        if not self._windows:
            self._maybe_quit()

    def _register(self, window: MainWindow) -> None:
        self._windows.add(window)

    def _maybe_quit(self) -> None:
        for widget in self._app.topLevelWidgets():
            if isinstance(widget, MergeWindow) and widget.isVisible():
                return
        self.last_window_closing.emit()
        self._app.quit()
