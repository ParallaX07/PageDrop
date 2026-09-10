from __future__ import annotations

from PyQt6.QtCore import QFileInfo, QPoint, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
)
from PyQt6.QtWidgets import QMenu, QTabBar, QTabWidget, QToolButton, QWidget

from pagedrop.core.drag_mime import PAGE_TRANSFER_MIME, decode_page_refs
from pagedrop.core.pdf_loader import PdfLoadError
from pagedrop.ui import icons
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
        self._pre_hint_tooltip = ""
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

    def _page_is_pdf(self, index: int) -> bool:
        tab_manager = self.parent()
        if not isinstance(tab_manager, QTabWidget):
            return False
        return isinstance(tab_manager.widget(index), PdfTab)

    def _should_detach(self, global_pos: QPoint) -> bool:
        if self._drag_start_global is None:
            return False
        if self._drag_tab_index < 0 or not self._page_is_pdf(self._drag_tab_index):
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
            self._pre_hint_tooltip = self.tabToolTip(index)
            self.setTabToolTip(index, "Release to open in new window")
        else:
            self._clear_detach_hint()

    def _clear_detach_hint(self) -> None:
        if self._detach_hint_index >= 0:
            self.setTabToolTip(self._detach_hint_index, self._pre_hint_tooltip)
            self._pre_hint_tooltip = ""
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
        move_action = None
        if tab is not None and tab.can_rename_tab:
            rename_action = menu.addAction("Rename tab…")
            menu.addSeparator()
        if tab is not None:
            move_action = menu.addAction("Move to new window")
        if rename_action is None and move_action is None:
            return
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is rename_action:
            self.tab_rename_requested.emit(index)
        elif move_action is not None and chosen is move_action:
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
    """Browser-style tab bar; PdfTab workspaces plus optional tool pages."""

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
        self.setDocumentMode(True)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)

        self._detachable_tab_bar = DetachableTabBar(self)
        self.setTabBar(self._detachable_tab_bar)
        # setTabBar replaces the bar and drops tabsClosable — apply after.
        self.setTabsClosable(True)
        self._detachable_tab_bar.tab_detach_requested.connect(
            self.tab_detach_requested.emit
        )
        self._detachable_tab_bar.move_to_new_window_requested.connect(
            self.move_to_new_window_requested.emit
        )
        self._detachable_tab_bar.tab_rename_requested.connect(
            self.tab_rename_requested.emit
        )
        self._open_tabs_button = QToolButton(self)
        self._open_tabs_button.setObjectName("OpenTabsButton")
        self._open_tabs_button.setText("Open tabs")
        self._open_tabs_button.setToolTip("Show open tabs")
        self._open_tabs_button.setAccessibleName("Open tabs")
        self._open_tabs_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self._open_tabs_menu = QMenu(self._open_tabs_button)
        self._open_tabs_menu.aboutToShow.connect(self._populate_open_tabs_menu)
        self._open_tabs_button.setMenu(self._open_tabs_menu)
        self.setCornerWidget(self._open_tabs_button, Qt.Corner.TopRightCorner)
        self._open_tabs_button.hide()

        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(self._on_current_changed)

        refresh_cb = self._refresh_close_icons
        icons.register_refresh(refresh_cb)
        self.destroyed.connect(lambda *_: icons.unregister_refresh(refresh_cb))

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
        self._apply_tab_icon(index, tab)
        self._schedule_open_tabs_update()
        self.tab_added.emit(tab)
        return tab

    def add_blank_tab(self) -> PdfTab:
        return self.add_tab()

    def add_page(self, page: QWidget, title: str | None = None) -> QWidget:
        """Host a non-PDF tool page in the tab strip."""
        resolved = title or getattr(page, "tab_title", None) or getattr(
            page, "WINDOW_TITLE", "Tool"
        )
        index = self.addTab(page, str(resolved))
        self._style_close_button(index)
        self._apply_page_title(index, str(resolved))
        self._apply_tab_icon(index, page)
        self.setCurrentWidget(page)
        self._schedule_open_tabs_update()
        return page

    def find_page_id(self, page_id: str) -> QWidget | None:
        for index in range(self.count()):
            widget = self.widget(index)
            if widget is not None and getattr(widget, "tool_page_id", None) == page_id:
                return widget
        return None

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
        self._schedule_open_tabs_update()

    def update_tab_title(self, tab: PdfTab) -> None:
        try:
            index = self.indexOf(tab)
        except RuntimeError:
            return
        if index >= 0:
            self._apply_tab_title(index, tab)

    def _apply_page_title(self, index: int, title: str) -> None:
        metrics = self.tabBar().fontMetrics()
        self.setTabText(
            index,
            metrics.elidedText(title, Qt.TextElideMode.ElideMiddle, 185),
        )
        self.setTabToolTip(index, title)

    def _apply_tab_title(self, index: int, tab: PdfTab) -> None:
        # QSS-sized tabs ignore setElideMode and hard-clip long titles, so
        # elide manually. fixed width assumes the theme's 220px tab
        # content box minus ~22px close button and a margin for the wider
        # weight-600 selected font; recompute from the style if tab sizing
        # ever becomes configurable.
        title = tab.tab_title
        self._apply_page_title(index, title)
        if tab.edit_model is not None:
            count = tab.edit_model.logical_count()
            noun = "page" if count == 1 else "pages"
            self.setTabToolTip(index, f"{tab.identity_tooltip}\n{count} {noun}")
        accessible = tab.display_name
        if tab.is_dirty:
            accessible += ", unsaved changes"
        self.tabBar().setAccessibleTabName(index, accessible)
        self._schedule_open_tabs_update()

    def _connect_tab(self, tab: PdfTab, index: int) -> None:
        tab.pdf_loaded.connect(lambda: self.update_tab_title(tab))
        tab.pdf_closed.connect(lambda: self.update_tab_title(tab))
        tab.dirty_changed.connect(lambda _: self.update_tab_title(tab))
        tab.tab_title_changed.connect(lambda: self.update_tab_title(tab))
        self._apply_tab_title(index, tab)

    def _on_current_changed(self, index: int) -> None:
        if index < 0:
            return
        widget = self.widget(index)
        if isinstance(widget, PdfTab):
            self.active_tab_changed.emit(widget)

    def _style_close_button(self, index: int) -> None:
        # Qt's default CloseButton paints PE_IndicatorTabClose and ignores setIcon.
        bar = self.tabBar()
        btn = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if not isinstance(btn, QToolButton) or btn.objectName() != "TabCloseButton":
            btn = QToolButton(bar)
            btn.setObjectName("TabCloseButton")
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("Close tab")
            btn.setAccessibleName("Close tab")
            btn.clicked.connect(self._on_tab_close_button_clicked)
            bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)
        btn.setIcon(tab_close_icon())
        btn.setIconSize(QSize(14, 14))

    def _on_tab_close_button_clicked(self) -> None:
        btn = self.sender()
        if btn is None:
            return
        for index in range(self.count()):
            if self.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide) is btn:
                self.tabCloseRequested.emit(index)
                return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_open_tabs_update()

    def _schedule_open_tabs_update(self) -> None:
        QTimer.singleShot(0, self._update_open_tabs_button)

    def _update_open_tabs_button(self) -> None:
        bar = self.tabBar()
        crowded = self.count() > 1 and any(
            bar.tabRect(index).right() >= bar.width()
            for index in range(self.count())
        )
        self._open_tabs_button.setVisible(crowded)

    def _populate_open_tabs_menu(self) -> None:
        self._open_tabs_menu.clear()
        names: dict[str, int] = {}
        for index in range(self.count()):
            widget = self.widget(index)
            if isinstance(widget, PdfTab):
                filename = (
                    QFileInfo(widget.display_path).fileName()
                    if widget.display_path is not None
                    else widget.display_name
                )
                names[filename] = names.get(filename, 0) + 1
        for index in range(self.count()):
            widget = self.widget(index)
            if widget is None:
                continue
            if isinstance(widget, PdfTab):
                label = widget.display_name
                filename = (
                    QFileInfo(widget.display_path).fileName()
                    if widget.display_path is not None
                    else widget.display_name
                )
                if names[filename] > 1 and widget.display_path is not None:
                    folder = QFileInfo(widget.display_path).dir().dirName()
                    label = f"{label} — {folder}"
                if widget.is_dirty:
                    label += " *"
                action = self._open_tabs_menu.addAction(icons.icon("file-doc"), label)
                action.setToolTip(self.tabToolTip(index))
            else:
                label = getattr(widget, "tab_title", None) or self.tabText(index)
                action = self._open_tabs_menu.addAction(icons.icon("wrench"), str(label))
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.triggered.connect(
                lambda _checked=False, page=widget: self.setCurrentWidget(page)
            )

    def _apply_tab_icon(self, index: int, widget: QWidget) -> None:
        name = "file-doc" if isinstance(widget, PdfTab) else "wrench"
        self.setTabIcon(index, icons.icon(name))

    def _refresh_close_icons(self) -> None:
        """Re-tint tab close × after a light/dark swap."""
        for index in range(self.count()):
            self._style_close_button(index)
            widget = self.widget(index)
            if widget is not None:
                self._apply_tab_icon(index, widget)
