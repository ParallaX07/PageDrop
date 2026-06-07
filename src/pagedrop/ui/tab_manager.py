from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QTabBar, QTabWidget, QWidget

from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.theme import tab_close_icon
from pagedrop.utils.temp_manager import TempManager


class TabManager(QTabWidget):
    """Browser-style tab bar; each tab is an independent PdfTab workspace."""

    active_tab_changed = pyqtSignal(PdfTab)
    tab_added = pyqtSignal(PdfTab)
    tab_closed = pyqtSignal(int)
    all_tabs_closed = pyqtSignal()

    def __init__(
        self,
        temp_manager: TempManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._temp_manager = temp_manager
        self.setObjectName("TabManager")
        self.setTabsClosable(True)
        self.setDocumentMode(True)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(self._on_current_changed)

    @property
    def active_tab(self) -> PdfTab | None:
        widget = self.currentWidget()
        return widget if isinstance(widget, PdfTab) else None

    def add_tab(self, tab: PdfTab | None = None) -> PdfTab:
        if tab is None:
            tab = PdfTab(temp_manager=self._temp_manager)
        index = self.addTab(tab, tab.tab_title)
        self._connect_tab(tab, index)
        self._style_close_button(index)
        self.tab_added.emit(tab)
        return tab

    def add_blank_tab(self) -> PdfTab:
        return self.add_tab()

    def switch_active_tab(self, index: int) -> None:
        if 0 <= index < self.count():
            self.setCurrentIndex(index)

    def close_tab(self, index: int) -> None:
        if index < 0 or index >= self.count():
            return

        tab = self.widget(index)
        if isinstance(tab, PdfTab):
            tab.close_loader()

        self.tab_closed.emit(index)
        self.removeTab(index)
        if tab is not None:
            tab.deleteLater()

        if self.count() == 0:
            self.all_tabs_closed.emit()
            self.add_blank_tab()

    def update_tab_title(self, tab: PdfTab) -> None:
        index = self.indexOf(tab)
        if index >= 0:
            self.setTabText(index, tab.tab_title)

    def _connect_tab(self, tab: PdfTab, index: int) -> None:
        tab.pdf_loaded.connect(lambda: self.update_tab_title(tab))
        tab.pdf_closed.connect(lambda: self.update_tab_title(tab))
        tab.dirty_changed.connect(lambda _: self.update_tab_title(tab))
        self.setTabText(index, tab.tab_title)

    def _on_current_changed(self, index: int) -> None:
        if index < 0:
            return
        widget = self.widget(index)
        if isinstance(widget, PdfTab):
            self.active_tab_changed.emit(widget)

    def _style_close_button(self, index: int) -> None:
        btn = self.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        if btn is None:
            return
        btn.setIcon(tab_close_icon())
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip("Close tab")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
