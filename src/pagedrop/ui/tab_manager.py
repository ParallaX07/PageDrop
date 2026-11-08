from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QFileInfo, QPoint, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QPainterPath,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QTabBar,
    QTabWidget,
    QToolButton,
    QWidget,
)

from pagedrop.core.drag_mime import (
    PAGE_TRANSFER_MIME,
    PageTransferPayloadError,
    decode_page_refs,
)
from pagedrop.core.pdf_loader import PdfLoadError
from pagedrop.ui import icons
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.theme import (
    INDEX_COLOUR_NAMES,
    RADIUS_SURFACE,
    SPACE_1,
    TAB_EDGE_HEIGHT,
    TAB_UNSAVED_DOT,
    accent_qcolor,
    current_theme,
    index_qcolor,
    tab_close_icon,
    token_qcolor,
)
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager


class _DragMarks(QWidget):
    """Transparent layer over the bar; paints the dragged tab's stripe and dot."""

    def __init__(self, bar: QTabBar) -> None:
        super().__init__(bar)
        self._bar = bar
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event) -> None:
        self._bar._paint_dragged_tab_marks(self)


class DetachableTabBar(QTabBar):
    """Tab bar that supports in-bar reorder (``setMovable``) and tear-off to a new window."""

    tab_detach_requested = pyqtSignal(int)
    move_to_new_window_requested = pyqtSignal(int)
    tab_rename_requested = pyqtSignal(int)

    DETACH_THRESHOLD_PX = 20
    TAB_GAP_PX = 2  # the style sheet's tab margin-right

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_tab_index = -1
        self._drag_start_global: QPoint | None = None
        self._detach_armed = False
        self._detach_hint_index = -1
        self._pre_hint_tooltip = ""
        self._drop_highlight_index = -1
        self._hover_index = -1
        # Qt draws a dragged tab in a private child from a pixmap of its own.
        self._moving_tab: QWidget | None = None
        self._marks = _DragMarks(self)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.currentChanged.connect(lambda _index: self.sync_close_buttons())
        self.tabMoved.connect(self._on_tab_moved)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_tab_context_menu)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_tab_index = self.tabAt(event.pos())
            self._drag_start_global = event.globalPosition().toPoint()
            self._detach_armed = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._set_hover_index(self.tabAt(event.pos()))
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
        if self._drag_tab_index >= 0:
            self._watch_moving_tab()

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        self._set_hover_index(-1)
        # Dragging over a neighbour swaps the pair; the pressed tab follows.
        if self._drag_tab_index == from_index:
            self._drag_tab_index = to_index
        elif self._drag_tab_index == to_index:
            self._drag_tab_index = from_index

    def _watch_moving_tab(self) -> None:
        """Find Qt's dragged-tab child and lay a marks layer over it."""
        if self._moving_tab is not None:
            return
        for child in self.children():
            if type(child) is QWidget and child.isVisible():
                self._moving_tab = child
                child.installEventFilter(self)
                child.destroyed.connect(self._forget_moving_tab)
                self._marks.setGeometry(self.rect())
                self._marks.raise_()
                self._marks.show()
                return

    def _forget_moving_tab(self) -> None:
        self._moving_tab = None

    def _dragging_index(self) -> int:
        """The dragged tab (the pressed tab is current), or -1 when none is moving."""
        if self._moving_tab is not None and self._moving_tab.isVisible():
            return self.currentIndex()
        return -1

    def eventFilter(self, watched, event) -> bool:
        if watched is self._moving_tab and event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            self._marks.update()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._marks.setGeometry(self.rect())

    def _paint_dragged_tab_marks(self, target: QWidget) -> None:
        """Draw the stripe and dot on the tab Qt is dragging (it paints a bare pixmap)."""
        moving = self._moving_tab
        index = self._dragging_index()
        slot = self.tabRect(index)
        if moving is None or index < 0 or not slot.isValid():
            return
        # The pixmap spans the tab plus the style's tab overlap on both sides.
        overlap = (moving.width() - slot.width()) // 2
        rect = QRect(moving.x() + overlap, moving.y(), slot.width(), slot.height())
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        self._paint_index_edge(painter, index, rect)
        self._paint_unsaved_dot(painter, index, rect)
        painter.end()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._detach_armed
            and self._drag_tab_index >= 0
        ):
            index = self._drag_tab_index
            self._reset_drag_state()
            # Let Qt end its drag so the dragged-tab pixmap does not outlive the tab.
            super().mouseReleaseEvent(event)
            self.tab_detach_requested.emit(index)
            event.accept()
            return
        self._reset_drag_state()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._set_hover_index(-1)
        super().leaveEvent(event)

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        self._hover_index = -1
        self.sync_close_buttons()

    def tabRemoved(self, index: int) -> None:
        super().tabRemoved(index)
        self._hover_index = -1
        self.sync_close_buttons()

    def _set_hover_index(self, index: int) -> None:
        if index != self._hover_index:
            self._hover_index = index
            self.sync_close_buttons()

    def close_button_shown(self, index: int) -> bool:
        """Close buttons appear on the active tab and the hovered tab only."""
        return index == self.currentIndex() or index == self._hover_index

    def sync_close_buttons(self) -> None:
        for index in range(self.count()):
            button = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if button is not None:
                button.setVisible(self.close_button_shown(index))

    def _tab_widget(self, index: int) -> QWidget | None:
        tab_manager = self.parent()
        if isinstance(tab_manager, QTabWidget):
            return tab_manager.widget(index)
        return None

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

        target_grid = target_widget.thumbnail_grid
        source_grid = ThumbnailGrid._grid_for_widget(event.source())
        if source_grid is None:
            target_grid.page_transfer_failed.emit(
                "Could not transfer pages: tabs can't accept drops from "
                "another PageDrop process. Drop on the page grid instead."
            )
            event.ignore()
            return

        source_tab = source_grid._parent_tab()
        if source_tab is target_widget:
            source_grid.page_transfer_failed.emit(
                "Drop on another tab to append pages"
            )
            event.ignore()
            return

        try:
            refs = decode_page_refs(mime.data(PAGE_TRANSFER_MIME))
        except PageTransferPayloadError:
            target_grid.page_transfer_failed.emit(
                "Could not transfer pages: the dropped data was not valid."
            )
            event.ignore()
            return
        if not refs:
            event.ignore()
            return

        move = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
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

    def _paint_index_edge(self, painter: QPainter, index: int, rect) -> None:
        """Index-colour top edge; style sheets cannot colour individual tabs."""
        manager = self.parent()
        name = (
            manager._tab_index_colour(index)
            if isinstance(manager, TabManager)
            else INDEX_COLOUR_NAMES[-1]
        )
        # The tab's right margin is part of tabRect; keep the edge on the tab.
        body = QRectF(rect.adjusted(0, 0, -self.TAB_GAP_PX, 0))
        # Round the top corners like the tab, then keep only the edge band.
        outline = QPainterPath()
        outline.addRoundedRect(
            body.adjusted(0, 0, 0, RADIUS_SURFACE), RADIUS_SURFACE, RADIUS_SURFACE
        )
        band = QPainterPath()
        band.addRect(QRectF(body.x(), body.y(), body.width(), TAB_EDGE_HEIGHT))
        painter.fillPath(outline.intersected(band), index_qcolor(name))

    def _paint_unsaved_dot(self, painter: QPainter, index: int, rect) -> None:
        widget = self._tab_widget(index)
        if not isinstance(widget, PdfTab) or not widget.is_dirty:
            return
        button = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        right = (
            button.geometry().left() - SPACE_1
            if button is not None
            else rect.right() - self.TAB_GAP_PX
        )
        centre_y = (rect.top() + TAB_EDGE_HEIGHT + rect.bottom()) / 2
        painter.setBrush(token_qcolor(current_theme().on_bar))
        painter.drawEllipse(
            QRectF(
                right - TAB_UNSAVED_DOT,
                centre_y - TAB_UNSAVED_DOT / 2,
                TAB_UNSAVED_DOT,
                TAB_UNSAVED_DOT,
            )
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        dragging = self._dragging_index()
        for index in range(self.count()):
            rect = self.tabRect(index)
            if rect.isValid() and index != dragging:
                self._paint_index_edge(painter, index, rect)
                self._paint_unsaved_dot(painter, index, rect)
        painter.end()
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
        recovery_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._temp_manager = temp_manager
        self._recovery_dir = recovery_dir
        self._next_index_colour = 0
        self.setObjectName("TabManager")
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)

        self._detachable_tab_bar = DetachableTabBar(self)
        self.setTabBar(self._detachable_tab_bar)
        # setTabBar replaces the bar and drops tabsClosable and movable — apply after.
        self.setTabsClosable(True)
        self.setMovable(True)
        self._detachable_tab_bar.tab_detach_requested.connect(
            self.tab_detach_requested.emit
        )
        self._detachable_tab_bar.move_to_new_window_requested.connect(
            self.move_to_new_window_requested.emit
        )
        self._detachable_tab_bar.tab_rename_requested.connect(
            self.tab_rename_requested.emit
        )
        self._tab_corner = QWidget(self)
        self._tab_corner.setObjectName("TabCorner")
        corner_layout = QHBoxLayout(self._tab_corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(4)
        self._open_tabs_button = QToolButton(self._tab_corner)
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
        corner_layout.addWidget(self._open_tabs_button)
        self.setCornerWidget(self._tab_corner, Qt.Corner.TopRightCorner)
        self._open_tabs_button.hide()

        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(self._on_current_changed)

        refresh_cb = self._refresh_close_icons
        icons.register_refresh(refresh_cb)

    def add_corner_widget(self, widget: QWidget) -> None:
        """Place a control in the tab strip's right-hand corner."""
        self._tab_corner.layout().addWidget(widget)

    @property
    def detachable_tab_bar(self) -> DetachableTabBar:
        return self._detachable_tab_bar

    @property
    def active_tab(self) -> PdfTab | None:
        widget = self.currentWidget()
        return widget if isinstance(widget, PdfTab) else None

    def add_tab(self, tab: PdfTab | None = None) -> PdfTab:
        if tab is None:
            tab = PdfTab(
                temp_manager=self._temp_manager,
                recovery_dir=self._recovery_dir,
            )
        if tab.index_colour is None:
            tab.index_colour = INDEX_COLOUR_NAMES[
                self._next_index_colour % len(INDEX_COLOUR_NAMES)
            ]
            self._next_index_colour += 1
        index = self.addTab(tab, tab.display_name)
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

    def _tab_index_colour(self, index: int) -> str:
        """Index colour token name for a tab; tool pages are always slate."""
        return getattr(self.widget(index), "index_colour", None) or "index_slate"

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
        compact_title = f"{title[:8]}…{title[-12:]}"
        display_title = title
        if len(title) > 20 and metrics.horizontalAdvance(compact_title) <= 185:
            display_title = compact_title
        self.setTabText(
            index,
            metrics.elidedText(display_title, Qt.TextElideMode.ElideMiddle, 185),
        )
        self.setTabToolTip(index, title)

    def _apply_tab_title(self, index: int, tab: PdfTab) -> None:
        # QSS-sized tabs ignore setElideMode and hard-clip long titles, so
        # elide manually. fixed width assumes the theme's 220px tab
        # content box minus ~22px close button and a margin for the wider
        # weight-600 selected font; recompute from the style if tab sizing
        # ever becomes configurable.
        # The unsaved dot is painted by the tab bar, so the text stays clean.
        title = tab.display_name
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
        self.tabBar().update()

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
            retain = btn.sizePolicy()
            retain.setRetainSizeWhenHidden(True)
            btn.setSizePolicy(retain)
            btn.setAccessibleName("Close tab")
            btn.clicked.connect(self._on_tab_close_button_clicked)
            bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)
        btn.setIcon(tab_close_icon())
        btn.setIconSize(QSize(14, 14))
        btn.setVisible(self._detachable_tab_bar.close_button_shown(index))

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
        self.tabBar().update()
