"""Toolbar keyboard navigation helpers.

Qt toolbars don't move focus with arrow keys by default. This installs a small
event filter so Left/Right/Up/Down step between focusable toolbar controls;
Space/Enter activation is already handled by QAbstractButton / QSlider.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QSlider,
    QToolBar,
    QToolButton,
    QWidget,
)

from pagedrop.ui.zoom_controls import ZoomControls

_ARROW_KEYS = {
    Qt.Key.Key_Left,
    Qt.Key.Key_Right,
    Qt.Key.Key_Up,
    Qt.Key.Key_Down,
}


def focusable_toolbar_widgets(toolbar: QToolBar) -> list[QWidget]:
    """Visible, enabled toolbar controls in left-to-right visual order."""
    widgets: list[QWidget] = []
    for action in toolbar.actions():
        if action.isSeparator():
            continue
        widget = toolbar.widgetForAction(action)
        if widget is None or not widget.isVisible() or not widget.isEnabled():
            continue
        if isinstance(widget, ZoomControls):
            for child in (widget._zoom_out, widget._slider, widget._zoom_in):
                if child.isVisible() and child.isEnabled():
                    widgets.append(child)
            continue
        if isinstance(widget, (QToolButton, QAbstractButton, QSlider)):
            widgets.append(widget)
    return widgets


class ToolbarArrowNavFilter(QObject):
    """Move focus between toolbar controls with arrow keys."""

    def __init__(self, toolbar: QToolBar) -> None:
        super().__init__(toolbar)
        self._toolbar = toolbar

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return False
        if event.key() not in _ARROW_KEYS:
            return False
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            return False

        focus = QApplication.focusWidget()
        if focus is None or not self._toolbar.isAncestorOf(focus):
            return False

        widgets = focusable_toolbar_widgets(self._toolbar)
        if len(widgets) < 2:
            return False

        try:
            index = widgets.index(focus)
        except ValueError:
            return False

        delta = 1 if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down) else -1
        next_index = max(0, min(len(widgets) - 1, index + delta))
        if next_index == index:
            return False

        widgets[next_index].setFocus(Qt.FocusReason.TabFocusReason)
        return True


def enable_toolbar_keyboard_navigation(toolbar: QToolBar) -> ToolbarArrowNavFilter:
    """StrongFocus on tool buttons + arrow-key focus movement within the toolbar."""
    nav_filter = ToolbarArrowNavFilter(toolbar)
    toolbar.installEventFilter(nav_filter)

    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if isinstance(widget, ZoomControls):
            for child in (widget._zoom_out, widget._slider, widget._zoom_in):
                child.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                child.installEventFilter(nav_filter)
        elif isinstance(widget, (QToolButton, QAbstractButton, QSlider)):
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.installEventFilter(nav_filter)

    # Keep a Python ref on the toolbar so the filter isn't GC'd.
    toolbar._pagedrop_arrow_nav = nav_filter  # type: ignore[attr-defined]
    return nav_filter


def set_content_tab_order(
    toolbar: QToolBar,
    content: QWidget,
    *,
    status_bar: QWidget | None = None,
) -> None:
    """Tab order: toolbar controls → content. Status bar stays out of the chain."""
    widgets = focusable_toolbar_widgets(toolbar)
    if widgets:
        for left, right in zip(widgets, widgets[1:]):
            QWidget.setTabOrder(left, right)
        QWidget.setTabOrder(widgets[-1], content)

    if status_bar is not None:
        status_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for child in status_bar.findChildren(QWidget):
            child.setFocusPolicy(Qt.FocusPolicy.NoFocus)
