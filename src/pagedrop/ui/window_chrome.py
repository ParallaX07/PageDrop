"""Frameless window chrome for the main window.

``WindowChromeMixin`` owns the custom title bar (menu bar, title text and the
minimize/maximize/close buttons), edge resizing, title-bar dragging, the native
Windows frame handling, the responsive menu/overflow layout and the collapse of
the menu and toolbar. It is mixed into ``MainWindow`` ahead of ``QMainWindow``
and relies on the window to provide ``_menu_bar``, ``_toolbar``,
``_update_thumbnail_zoom_host`` and the chrome state attributes set in its
constructor.
"""

from __future__ import annotations

import ctypes
import math
import sys

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QCursor, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QSizePolicy,
    QToolButton,
    QWIDGETSIZE_MAX,
    QWidget,
)

from pagedrop.ui import icons, native_frame
from pagedrop.ui.accessibility import prefers_high_contrast
from pagedrop.ui.settings import set_chrome_visible
from pagedrop.ui.theme import ICON_SIZE_SMALL, current_theme
from pagedrop.utils.diagnostics import log_failure

RESIZE_MARGIN = 6
MIN_WINDOW_WIDTH = 480
MIN_WINDOW_HEIGHT = 320
# The title and menu row is never shorter than this; the menus come first and
# the document title takes whatever room is left, up to the maximum.
TITLE_BAR_HEIGHT = 34
TITLE_MAX_WIDTH = 360


def resize_edges_at(pos, size, margin: int = RESIZE_MARGIN) -> Qt.Edge:
    """Return the window edges (corners are two flags) a point lies within."""
    edges = Qt.Edge(0)
    if pos.x() < margin:
        edges |= Qt.Edge.LeftEdge
    elif pos.x() >= size.width() - margin:
        edges |= Qt.Edge.RightEdge
    if pos.y() < margin:
        edges |= Qt.Edge.TopEdge
    elif pos.y() >= size.height() - margin:
        edges |= Qt.Edge.BottomEdge
    return edges


def cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape | None:
    """Return the resize cursor for an edge set, or None when it is empty."""
    left = bool(edges & Qt.Edge.LeftEdge)
    right = bool(edges & Qt.Edge.RightEdge)
    top = bool(edges & Qt.Edge.TopEdge)
    bottom = bool(edges & Qt.Edge.BottomEdge)
    if (left and top) or (right and bottom):
        return Qt.CursorShape.SizeFDiagCursor
    if (right and top) or (left and bottom):
        return Qt.CursorShape.SizeBDiagCursor
    if left or right:
        return Qt.CursorShape.SizeHorCursor
    if top or bottom:
        return Qt.CursorShape.SizeVerCursor
    return None


class WindowChromeMixin:
    def _build_title_bar(self) -> None:
        title_bar = QWidget(self)
        title_bar.setObjectName("WindowTitleBar")
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        title_bar.setMinimumHeight(TITLE_BAR_HEIGHT)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        menubar = QMenuBar(title_bar)
        # The title bar's layout, not the menu items, decides this width.
        menubar.setSizePolicy(QSizePolicy.Policy.Ignored, menubar.sizePolicy().verticalPolicy())
        self._menu_bar = menubar
        self._title_bar = title_bar

        window_controls = QWidget(title_bar)
        window_controls.setObjectName("WindowControls")
        layout = QHBoxLayout(window_controls)
        # The label's margin lives here, not in its style sheet, so the width
        # the title is elided to is the width its text really has.
        layout.setContentsMargins(16, 0, 4, 0)
        layout.setSpacing(2)
        self._title_label = QLabel(self.windowTitle(), window_controls)
        self._title_label.setObjectName("WindowTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._title_label)
        # Stays reachable by mouse when the menus are hidden: the window
        # controls never collapse.
        toggle = QToolButton(window_controls)
        toggle.setObjectName("ChromeToggleButton")
        toggle.setIconSize(QSize(ICON_SIZE_SMALL, ICON_SIZE_SMALL))
        toggle.setAutoRaise(True)
        toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        toggle.clicked.connect(self._toggle_chrome_visible)
        layout.addWidget(toggle)
        self._chrome_toggle_btn = toggle
        for name, slot, label in (
            ("WindowMinimize", self.showMinimized, "Minimize window"),
            ("WindowMaximize", self._toggle_maximized, "Maximize window"),
            ("WindowClose", self.close, "Close window"),
        ):
            button = QToolButton(window_controls)
            button.setObjectName(name)
            button.setIconSize(QSize(ICON_SIZE_SMALL, ICON_SIZE_SMALL))
            # The hover tint is the icon's Active pixmap, which Qt only picks
            # for auto-raise tool buttons.
            button.setAutoRaise(True)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.clicked.connect(slot)
            layout.addWidget(button)
            if name == "WindowMaximize":
                self._maximize_button = button
        self._window_control_buttons = tuple(
            button
            for button in window_controls.findChildren(QToolButton)
            if button is not toggle
        )
        self._refresh_window_control_icons()
        title_layout.addWidget(menubar, 1)
        title_layout.addWidget(window_controls, 0, Qt.AlignmentFlag.AlignRight)
        self.setMenuWidget(title_bar)
        self._window_controls = window_controls
        self._title_drag_widgets = (title_bar, window_controls, self._title_label)
        QTimer.singleShot(0, self._update_responsive_shell)

    def _refresh_window_control_icons(self) -> None:
        """Tint the title-bar glyphs like the bar text; close turns red on hover."""
        theme = current_theme()
        tint = theme.text if prefers_high_contrast() else theme.on_bar
        glyphs = {
            "WindowMinimize": ("minus", None),
            "WindowMaximize": ("copy" if self.isMaximized() else "square", None),
            "WindowClose": ("x", theme.danger),
        }
        for button in self._window_control_buttons:
            name, active = glyphs[button.objectName()]
            button.setIcon(icons.icon(name, color=tint, active_color=active))
        self._sync_chrome_toggle(tint)

    def _sync_chrome_toggle(self, tint: str | None = None) -> None:
        """Point the collapse button at the action its next click performs."""
        toggle = self._chrome_toggle_btn
        if tint is None:
            theme = current_theme()
            tint = theme.text if prefers_high_contrast() else theme.on_bar
        visible = not self._menu_bar.isHidden()
        toggle.setIcon(icons.icon("caret-up-bold" if visible else "caret-down-bold", color=tint))
        tip = "Hide menu and toolbar" if visible else "Show menu and toolbar"
        toggle.setToolTip(tip)
        toggle.setAccessibleName(tip)

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _sync_custom_title(self) -> None:
        title_label = getattr(self, "_title_label", None)
        if title_label is not None:
            full_title = self.windowTitle()
            width = title_label.maximumWidth()
            title_label.setText(
                full_title
                if full_title == self.APP_TITLE
                else title_label.fontMetrics().elidedText(
                    full_title, Qt.TextElideMode.ElideRight, width if width < 10000 else 220
                )
            )
            title_label.setToolTip(full_title)

    def _update_responsive_shell(self) -> None:
        """Move destinations between the menu bar and More as one ownership set."""
        if not hasattr(self, "_menu_bar") or self._updating_responsive_shell:
            return
        self._updating_responsive_shell = True
        try:
            # Start with no title reservation: filename identity gives way before
            # any destination moves. Geometry, rather than text-width guesses,
            # accounts for the active font, display scale, and title controls.
            self._fit_window_controls(0)
            self._flush_menu_layout()
            direct = list(self._responsive_menu_actions)
            overflowed: list[QAction] = []
            self._relocate_application_actions(direct, overflowed)
            self._flush_menu_layout()

            while direct and not self._menu_actions_fit():
                overflowed.insert(0, direct.pop())
                self._relocate_application_actions(direct, overflowed)
                self._flush_menu_layout()

            # With the menu hidden the title has the whole strip to itself.
            room = (
                TITLE_MAX_WIDTH if self._menu_bar.isHidden() else self._menu_action_slack()
            )
            self._fit_window_controls(min(TITLE_MAX_WIDTH, max(0, room)))
            self._flush_menu_layout()
            self._sync_custom_title()
        finally:
            self._updating_responsive_shell = False
        self._update_thumbnail_zoom_host()

    def _fit_window_controls(self, title_width: int) -> None:
        self._title_label.setFixedWidth(title_width)
        controls = self._window_controls
        controls.setMinimumWidth(0)
        controls.setMaximumWidth(QWIDGETSIZE_MAX)
        controls.layout().invalidate()
        controls.setFixedWidth(controls.layout().sizeHint().width())

    def _relocate_application_actions(
        self, direct: list[QAction], overflowed: list[QAction]
    ) -> None:
        """Give every responsive destination exactly one current presentation."""
        for action in self._responsive_menu_actions:
            self._menu_bar.removeAction(action)
            self._application_overflow_menu.removeAction(action)
        more = self._application_overflow_menu.menuAction()
        more.setVisible(bool(overflowed))
        for action in direct:
            self._menu_bar.insertAction(more, action)
        for action in overflowed:
            self._application_overflow_menu.addAction(action)

    def _flush_menu_layout(self) -> None:
        self._title_bar.layout().invalidate()
        self._title_bar.layout().activate()
        self._menu_bar.updateGeometry()
        # Refresh only this layout; pumping the application here can dispatch
        # timers/deletions while Qt is still applying a stylesheet or resizing.
        QApplication.sendEvent(self._menu_bar, QEvent(QEvent.Type.LayoutRequest))

    def _menu_action_slack(self) -> int:
        """Return room between the final rendered menu action and title controls."""
        actions = [
            action for action in self._menu_bar.actions() if action.isVisible()
        ]
        right = max(
            (self._menu_bar.actionGeometry(action).right() + 1 for action in actions),
            default=0,
        )
        # The menu bar takes whatever the title bar leaves beside the controls.
        # Before first show (or while hidden) nothing has been laid out, so
        # budget from the window width instead.
        if self.isVisible() and not self._menu_bar.isHidden():
            menu_right = self._menu_bar.contentsRect().right() + 1
        else:
            menu_right = self.contentsRect().width() - self._window_controls.width()
        return menu_right - right

    def _menu_actions_fit(self) -> bool:
        return self._menu_action_slack() >= 0

    def _toggle_chrome_visible(self) -> None:
        action = getattr(self, "_chrome_visible_action", None)
        visible = True if action is None else action.isChecked()
        self._set_chrome_visible(not visible)

    def _on_chrome_visible_toggled(self, visible: bool) -> None:
        self._set_chrome_visible(visible)

    def _set_chrome_visible(self, visible: bool, *, persist: bool = True) -> None:
        # The title bar and its window controls stay; only the menus go.
        self._menu_bar.setVisible(visible)
        self._toolbar.setVisible(visible)
        QTimer.singleShot(0, self._update_responsive_shell)
        action = getattr(self, "_chrome_visible_action", None)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        self._sync_chrome_toggle()
        if persist:
            set_chrome_visible(visible)

    def _uses_native_frame(self) -> bool:
        """True where Windows supplies resize, snap and the caption for this window."""
        return (
            native_frame.IS_WINDOWS
            and bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)
            and not self._native_frame_failed
        )

    def _uses_qt_edge_resize(self) -> bool:
        """True where Qt must provide edge resizing for the frameless window."""
        return (
            bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)
            and (sys.platform != "win32" or self._native_frame_failed)
            and not self.isMaximized()
            and not self.isFullScreen()
            and QApplication.activeModalWidget() is None
        )

    def nativeEvent(self, eventType, message):  # noqa: ANN001, ANN201, N802
        if not self._uses_native_frame() or bytes(eventType) != b"windows_generic_MSG":
            return super().nativeEvent(eventType, message)
        try:
            handled, result = self._handle_native_message(
                native_frame.read_message(int(message))
            )
        except (OSError, ctypes.ArgumentError) as exc:
            # An exception escaping a Qt virtual is fatal; log once and let
            # Windows' default handling carry on.
            if not self._native_event_error_logged:
                self._native_event_error_logged = True
                log_failure("Handle native window message", exc)
            handled, result = False, 0
        if handled:
            return True, result
        return super().nativeEvent(eventType, message)

    def _handle_native_message(self, msg) -> tuple[bool, int]:  # noqa: ANN001
        kind = msg.message
        hwnd = int(msg.hwnd or 0)
        if kind == native_frame.WM_NCCALCSIZE:
            # Whole window is client area. Maximized, Windows places the window
            # past the screen edge by the frame thickness, so pull it back in.
            # wParam false passes a bare RECT instead of NCCALCSIZE_PARAMS and
            # needs the same adjustment, which calc_size_rect resolves.
            if msg.lParam and native_frame.is_zoomed(hwnd) and not self.isFullScreen():
                thickness_x, thickness_y = native_frame.resize_frame_thickness(hwnd)
                native_frame.inset_rect(
                    native_frame.calc_size_rect(msg.wParam, msg.lParam),
                    thickness_x,
                    thickness_y,
                )
            return True, 0
        if kind == native_frame.WM_NCHITTEST:
            return True, self._native_hit_test(hwnd, msg.lParam)
        button = self._maximize_button
        if (
            kind in (native_frame.WM_NCLBUTTONDOWN, native_frame.WM_NCLBUTTONDBLCLK)
            and msg.wParam == native_frame.HTMAXBUTTON
        ):
            # The window class has CS_DBLCLKS, so the second press of a fast
            # double-click arrives as a double-click message, not a press.
            button.setDown(True)
            return True, 0
        if kind == native_frame.WM_NCLBUTTONUP and msg.wParam == native_frame.HTMAXBUTTON:
            # Swallow the release even without a matching press so Windows does
            # not maximize on its own.
            pressed = button.isDown()
            button.setDown(False)
            if pressed:
                self._toggle_maximized()
            return True, 0
        # Hover tracking leaves these unhandled: Windows' default handling of
        # them is what shows the Snap Layouts flyout over the maximize button.
        if kind == native_frame.WM_NCMOUSEMOVE:
            self._set_native_maximize_hover(msg.wParam == native_frame.HTMAXBUTTON, hwnd)
        elif kind == native_frame.WM_NCMOUSELEAVE:
            self._set_native_maximize_hover(False, hwnd)
        return False, 0

    def _native_hit_test(self, hwnd: int, lparam: int) -> int:
        origin_x, origin_y = native_frame.client_origin(hwnd)
        screen_x, screen_y = native_frame.lparam_point(lparam)
        ratio = self.devicePixelRatioF()
        point = QPoint(
            math.floor((screen_x - origin_x) / ratio),
            math.floor((screen_y - origin_y) / ratio),
        )
        if not (self.isMaximized() or self.isFullScreen()):
            code = native_frame.hit_test_for_edges(resize_edges_at(point, self.size()))
            if code:
                return code
        button = self._maximize_button
        if button.isVisible() and QRect(button.mapTo(self, QPoint(0, 0)), button.size()).contains(point):
            return native_frame.HTMAXBUTTON
        if self._is_title_area_at(point):
            return native_frame.HTCAPTION
        return native_frame.HTCLIENT

    def _is_title_area_at(self, point: QPoint) -> bool:
        """True over blank title bar space, the title text or blank menu bar space."""
        child = self.childAt(point)
        if child is None:
            return False
        if child in self._title_drag_widgets:
            return True
        return child is self._menu_bar and self._menu_bar.actionAt(child.mapFrom(self, point)) is None

    def _set_native_maximize_hover(self, hover: bool, hwnd: int) -> None:
        button = self._maximize_button
        if not hover:
            button.setDown(False)
        if bool(button.property("nativeHover")) == hover:
            return
        if hover:
            native_frame.track_nonclient_leave(hwnd)
        button.setProperty("nativeHover", hover)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def _set_edge_cursor(self, shape: Qt.CursorShape | None) -> None:
        """Keep at most one override cursor pushed on behalf of edge resizing."""
        if shape is None:
            if self._edge_cursor_active:
                self._edge_cursor_active = False
                QApplication.restoreOverrideCursor()
        elif self._edge_cursor_active:
            QApplication.changeOverrideCursor(QCursor(shape))
        else:
            self._edge_cursor_active = True
            QApplication.setOverrideCursor(QCursor(shape))

    def _clear_edge_state(self) -> None:
        self._edge_resize = None
        self._set_edge_cursor(None)

    def _start_edge_resize(self, edges: Qt.Edge, global_pos: QPoint) -> None:
        handle = self.windowHandle()
        if handle is not None and handle.startSystemResize(edges):
            return
        self._edge_resize = (edges, global_pos, self.geometry())

    def _apply_edge_resize(self, global_pos: QPoint) -> None:
        edges, start, base = self._edge_resize
        delta = global_pos - start
        minimum = self.minimumSize()
        x, y, width, height = base.x(), base.y(), base.width(), base.height()
        if edges & Qt.Edge.LeftEdge:
            width = max(minimum.width(), base.width() - delta.x())
            x = base.x() + base.width() - width
        elif edges & Qt.Edge.RightEdge:
            width = max(minimum.width(), base.width() + delta.x())
        if edges & Qt.Edge.TopEdge:
            height = max(minimum.height(), base.height() - delta.y())
            y = base.y() + base.height() - height
        elif edges & Qt.Edge.BottomEdge:
            height = max(minimum.height(), base.height() + delta.y())
        self.setGeometry(x, y, width, height)

    def _handle_edge_resize_event(self, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Leave:
            if self._edge_resize is None:
                self._set_edge_cursor(None)
            return False
        if not isinstance(event, QMouseEvent):
            return False
        if self._edge_resize is not None:
            if kind == QEvent.Type.MouseMove:
                self._apply_edge_resize(event.globalPosition().toPoint())
                return True
            if kind == QEvent.Type.MouseButtonRelease:
                self._clear_edge_state()
                return True
            return False
        if not self._uses_qt_edge_resize():
            self._set_edge_cursor(None)
            return False
        edges = resize_edges_at(event.position().toPoint(), self.size())
        if kind == QEvent.Type.MouseMove and not event.buttons():
            self._set_edge_cursor(cursor_for_edges(edges))
        elif (
            kind == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and edges
        ):
            self._start_edge_resize(edges, event.globalPosition().toPoint())
            return True
        return False

    def _handle_title_area_event(self, obj, event) -> bool:
        """Drag the window from blank title bar space; True when the event is consumed."""
        is_title_area = obj in getattr(self, "_title_drag_widgets", ())
        if obj is getattr(self, "_menu_bar", None) and isinstance(event, QMouseEvent):
            dragging = (
                self._title_press_pos is not None or self._window_drag_offset is not None
            )
            is_title_area = (
                dragging or self._menu_bar.actionAt(event.position().toPoint()) is None
            )
        if not (is_title_area and isinstance(event, QMouseEvent)):
            return False
        kind = event.type()
        left = event.button() == Qt.MouseButton.LeftButton
        if kind == QEvent.Type.MouseButtonPress and left:
            # The move starts once the pointer travels, so a double-click
            # is never swallowed by a system move grab.
            self._title_press_pos = event.globalPosition().toPoint()
            self._window_drag_offset = None
            return True
        if kind == QEvent.Type.MouseButtonDblClick and left:
            self._title_press_pos = None
            self._window_drag_offset = None
            self._toggle_maximized()
            return True
        if kind == QEvent.Type.MouseMove:
            pos = event.globalPosition().toPoint()
            if self._window_drag_offset is not None:
                self.move(pos - self._window_drag_offset)
                return True
            press = self._title_press_pos
            if press is not None and event.buttons() & Qt.MouseButton.LeftButton:
                if (pos - press).manhattanLength() >= QApplication.startDragDistance():
                    self._title_press_pos = None
                    handle = self.windowHandle()
                    if handle is None or not handle.startSystemMove():
                        self._window_drag_offset = press - self.frameGeometry().topLeft()
                        self.move(pos - self._window_drag_offset)
                return True
        if kind == QEvent.Type.MouseButtonRelease:
            self._title_press_pos = None
            self._window_drag_offset = None
            return True
        return False
