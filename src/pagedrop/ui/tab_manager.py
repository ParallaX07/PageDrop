from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
)
from PyQt6.QtWidgets import QMenu, QTabBar, QTabWidget, QWidget

from pagedrop.core.drag_mime import PAGE_TRANSFER_MIME, decode_page_refs
from pagedrop.core.pdf_loader import PdfLoadError
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.theme import accent_qcolor, tab_close_icon
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager


class DetachableTabBar(QTabBar):
    """Tab bar that supports in-bar reorder (``setMovable``) and tear-off to a new window."""

    tab_detach_requested = pyqtSignal(int)
    move_to_new_window_requested = pyqtSignal(int)
    tab_rename_requested = pyqtSignal(int)

    DETACH_THRESHOLD_PX = 20

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_tab_index = -1
        self._drag_start_global: QPoint | None = None
        self._detach_armed = False
        self._detach_hint_index = -1
        self._drop_highlight_index = -1
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_tab_context_menu)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_tab_index = self.tabAt(event.pos())
            self._drag_start_global = event.globalPosition().toPoint()
            self._detach_armed = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_tab_index >= 0
            and self._drag_start_global is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            global_pos = event.globalPosition().toPoint()
            if self._should_detach(global_pos):
                if not self._detach_armed:
                    self._detach_armed = True
                    self._set_detach_hint(self._drag_tab_index, True)
                self.setCursor(Qt.CursorShape.DragCopyCursor)
                event.accept()
                return
            if self._detach_armed:
                self._clear_detach_hint()
                self._detach_armed = False
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._detach_armed
            and self._drag_tab_index >= 0
        ):
            index = self._drag_tab_index
            self._reset_drag_state()
            self.tab_detach_requested.emit(index)
            event.accept()
            return
        self._reset_drag_state()
        super().mouseReleaseEvent(event)

    def _should_detach(self, global_pos: QPoint) -> bool:
        if self._drag_start_global is None:
            return False
        if (global_pos - self._drag_start_global).manhattanLength() < self.DETACH_THRESHOLD_PX:
            return False
        window = self.window()
        if window is None:
            return False
        return not window.frameGeometry().contains(global_pos)

    def _set_detach_hint(self, index: int, enabled: bool) -> None:
        if enabled:
            self._detach_hint_index = index
            self.setTabToolTip(index, "Release to open in new window")
        else:
            self._clear_detach_hint()

    def _clear_detach_hint(self) -> None:
        if self._detach_hint_index >= 0:
            self.setTabToolTip(self._detach_hint_index, "")
            self._detach_hint_index = -1

    def _reset_drag_state(self) -> None:
        self._clear_detach_hint()
        self._drag_tab_index = -1
        self._drag_start_global = None
        self._detach_armed = False
        self.unsetCursor()

    def _show_tab_context_menu(self, pos: QPoint) -> None:
        index = self.tabAt(pos)
        if index < 0:
            return

        tab_manager = self.parent()
        tab: PdfTab | None = None
        if isinstance(tab_manager, QTabWidget):
            widget = tab_manager.widget(index)
            if isinstance(widget, PdfTab):
                tab = widget

        menu = QMenu(self)
        rename_action = None
        if tab is not None and tab.can_rename_tab:
            rename_action = menu.addAction("Rename Tab…")
            menu.addSeparator()
        move_action = menu.addAction("Move to New Window")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is rename_action:
            self.tab_rename_requested.emit(index)
        elif chosen is move_action:
            self.move_to_new_window_requested.emit(index)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(PAGE_TRANSFER_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not event.mimeData().hasFormat(PAGE_TRANSFER_MIME):
            event.ignore()
            return

        index = self.tabAt(event.position().toPoint())
        if index != self._drop_highlight_index:
            self._drop_highlight_index = index
            self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._clear_drop_highlight()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._clear_drop_highlight()
        mime = event.mimeData()
        if not mime.hasFormat(PAGE_TRANSFER_MIME):
            event.ignore()
            return

        index = self.tabAt(event.position().toPoint())
        if index < 0:
            event.ignore()
            return

        tab_manager = self.parent()
        if not isinstance(tab_manager, QTabWidget):
            event.ignore()
            return

        target_widget = tab_manager.widget(index)
        if not isinstance(target_widget, PdfTab):
            event.ignore()
            return

        source_grid = ThumbnailGrid._grid_for_widget(event.source())
        if source_grid is None:
            event.ignore()
            return

        source_tab = source_grid._parent_tab()
        if source_tab is target_widget:
            source_grid.page_transfer_failed.emit(
                "Drop on another tab to append pages"
            )
            event.ignore()
            return

        refs = decode_page_refs(mime.data(PAGE_TRANSFER_MIME))
        if not refs:
            event.ignore()
            return

        move = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        target_grid = target_widget.thumbnail_grid
        try:
            if target_grid.handle_tab_bar_page_drop(
                refs,
                move=move,
                source_grid=source_grid,
                mime=mime,
            ):
                event.acceptProposedAction()
            else:
                event.ignore()
        except PdfLoadError as exc:
            target_grid.pdf_drop_failed.emit(exc)
            event.ignore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_highlight_index < 0:
            return

        rect = self.tabRect(self._drop_highlight_index)
        if not rect.isValid():
            return

        accent = accent_qcolor()
        fill = QColor(accent)
        fill.setAlpha(48)
        painter = QPainter(self)
        painter.fillRect(rect, fill)
        painter.setPen(accent)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.end()

    def _clear_drop_highlight(self) -> None:
        if self._drop_highlight_index >= 0:
            self._drop_highlight_index = -1
            self.update()


class TabManager(QTabWidget):
    """Browser-style tab bar; each tab is an independent PdfTab workspace."""

    active_tab_changed = pyqtSignal(PdfTab)
    tab_added = pyqtSignal(PdfTab)
    tab_closed = pyqtSignal(int)
    all_tabs_closed = pyqtSignal()
    tab_detach_requested = pyqtSignal(int)
    move_to_new_window_requested = pyqtSignal(int)
    tab_rename_requested = pyqtSignal(int)

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

        self._detachable_tab_bar = DetachableTabBar(self)
        self.setTabBar(self._detachable_tab_bar)
        self._detachable_tab_bar.tab_detach_requested.connect(
            self.tab_detach_requested.emit
        )
        self._detachable_tab_bar.move_to_new_window_requested.connect(
            self.move_to_new_window_requested.emit
        )
        self._detachable_tab_bar.tab_rename_requested.connect(
            self.tab_rename_requested.emit
        )

        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(self._on_current_changed)

    @property
    def detachable_tab_bar(self) -> DetachableTabBar:
        return self._detachable_tab_bar

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
        try:
            index = self.indexOf(tab)
        except RuntimeError:
            return
        if index >= 0:
            self.setTabText(index, tab.tab_title)

    def _connect_tab(self, tab: PdfTab, index: int) -> None:
        tab.pdf_loaded.connect(lambda: self.update_tab_title(tab))
        tab.pdf_closed.connect(lambda: self.update_tab_title(tab))
        tab.dirty_changed.connect(lambda _: self.update_tab_title(tab))
        tab.tab_title_changed.connect(lambda: self.update_tab_title(tab))
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
