"""Status that floats over the bottom of the active content area."""

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from pagedrop.ui.theme import SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_7, tabular_font

FLOAT_MARGIN = SPACE_4
FLOAT_GAP = SPACE_2
# Room a scrolling view leaves at its end so its last row clears the corner control.
FLOAT_CLEARANCE = FLOAT_MARGIN + SPACE_7

# What the layout watches on the widgets it places and on the area it floats over.
_ITEM_EVENTS = (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.LayoutRequest)
_ANCHOR_EVENTS = (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show)


class FloatingZoomHost(QFrame):
    """Frame around the zoom control that hands page and file drops to the grid.

    The control sits over the grid, so a drop landing on it must still reach the
    grid, with the pointer mapped into the grid's own coordinates.
    """

    def __init__(
        self, drop_target: Callable[[], QWidget | None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ThumbnailZoomStatusHost")
        self.setAcceptDrops(True)
        self._drop_target = drop_target
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def _forward(self, event, make_event, handler: str) -> None:
        target = self._drop_target()
        if target is None:
            event.ignore()
            return
        viewport = getattr(target, "viewport", None)
        space = viewport() if callable(viewport) else target
        pos = space.mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
        forwarded = make_event(QPointF(pos))
        getattr(target, handler)(forwarded)
        if forwarded.isAccepted():
            event.setDropAction(forwarded.dropAction())
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._forward(
            event,
            lambda pos: QDragEnterEvent(
                pos.toPoint(),
                event.possibleActions(),
                event.mimeData(),
                event.buttons(),
                event.modifiers(),
            ),
            "dragEnterEvent",
        )

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._forward(
            event,
            lambda pos: QDragMoveEvent(
                pos.toPoint(),
                event.possibleActions(),
                event.mimeData(),
                event.buttons(),
                event.modifiers(),
            ),
            "dragMoveEvent",
        )

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        target = self._drop_target()
        if target is not None:
            target.dragLeaveEvent(QDragLeaveEvent())

    def dropEvent(self, event: QDropEvent) -> None:
        self._forward(
            event,
            lambda pos: QDropEvent(
                pos,
                event.possibleActions(),
                event.mimeData(),
                event.buttons(),
                event.modifiers(),
            ),
            "dropEvent",
        )


class FloatingStatus(QObject):
    """Message pill, stacked prompts and a corner control over the active content.

    Everything is a child of *host* (the tab area) and is placed over *anchor*,
    the active page's content, so side panes stay clear. The pill takes no mouse
    input; stacked prompts keep theirs.
    """

    def __init__(
        self,
        host: QWidget,
        *,
        stack: Sequence[QWidget],
        corner: QWidget,
    ) -> None:
        super().__init__(host)
        # Weak: the host owns this object, and anything it holds strongly that
        # leads back to the host would be a reference cycle.
        self._anchor_ref: weakref.ref[QWidget] | None = None
        self._laying_out = False

        self._pill = QFrame(host)
        self._pill.setObjectName("FloatingStatusPill")
        self._pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        pill_layout = QHBoxLayout(self._pill)
        pill_layout.setContentsMargins(SPACE_3, SPACE_2, SPACE_3, SPACE_2)
        self._label = QLabel()
        self._label.setObjectName("FloatingStatusMessage")
        self._label.setFont(tabular_font())
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill_layout.addWidget(self._label)
        self._pill.hide()

        # Bottom to top.
        self._stack = (self._pill, *stack)
        self._corner = corner
        for widget in (*stack, corner):
            widget.setParent(host)
            widget.hide()
        for widget in (*self._stack, corner):
            widget.installEventFilter(self)
        host.installEventFilter(self)

    # --- message --------------------------------------------------------

    def show_message(self, text: str) -> None:
        self._label.setText(text)
        self._label.setAccessibleName(text)
        self._label.setAccessibleDescription("Status message")
        self._pill.show()
        self.relayout()

    def clear_message(self) -> None:
        if self._pill.isHidden():
            return
        self._pill.hide()
        self._label.clear()
        self.relayout()

    def message(self) -> str:
        return "" if self._pill.isHidden() else self._label.text()

    @property
    def pill(self) -> QWidget:
        return self._pill

    # --- placement ------------------------------------------------------

    @property
    def _host(self) -> QWidget:
        return self.parent()

    @property
    def _anchor(self) -> QWidget | None:
        return self._anchor_ref() if self._anchor_ref is not None else None

    def set_anchor(self, anchor: QWidget | None) -> None:
        if anchor is self._anchor:
            self.relayout()
            return
        old = self._anchor
        self._anchor_ref = weakref.ref(anchor) if anchor is not None else None
        if old is not None:
            try:
                old.removeEventFilter(self)
            except RuntimeError:
                # The old area was already deleted.
                pass
        if anchor is not None:
            anchor.installEventFilter(self)
        self.relayout()

    def _area(self) -> QRect | None:
        anchor = self._anchor
        if anchor is None or sip.isdeleted(anchor) or not self._host.isAncestorOf(anchor):
            return None
        return QRect(anchor.mapTo(self._host, QPoint(0, 0)), anchor.size())

    def _size_for(self, widget: QWidget, max_width: int) -> tuple[int, int]:
        hint = widget.sizeHint()
        width = min(hint.width(), widget.maximumWidth(), max_width)
        if widget is self._pill:
            # A wrapping label hints a narrow width; start from the text on one line.
            self._label.ensurePolished()
            text = self._label.fontMetrics().horizontalAdvance(self._label.text())
            chrome = hint.width() - self._label.sizeHint().width()
            width = min(text + chrome + 1, max_width)
        height = hint.height()
        layout = widget.layout()
        if layout is not None and layout.hasHeightForWidth():
            height = layout.totalHeightForWidth(width)
            if widget is not self._pill:
                height = max(height, hint.height())
        return width, height

    def relayout(self) -> None:
        if self._laying_out:
            return
        area = self._area()
        if area is None:
            return
        self._laying_out = True
        try:
            max_width = max(1, area.width() - 2 * FLOAT_MARGIN)
            floor = area.bottom() + 1 - FLOAT_MARGIN

            corner_rect: QRect | None = None
            if not self._corner.isHidden():
                width, height = self._size_for(self._corner, max_width)
                corner_rect = QRect(
                    area.right() + 1 - FLOAT_MARGIN - width,
                    floor - height,
                    width,
                    height,
                )
                self._corner.setGeometry(corner_rect)
                self._corner.raise_()

            sized = [
                (widget, *self._size_for(widget, max_width))
                for widget in self._stack
                if not widget.isHidden()
            ]
            if not sized:
                return
            column_width = max(width for _widget, width, _height in sized)
            left = area.center().x() - column_width // 2
            # Beside the corner control there is no room: stack above it instead.
            if corner_rect is not None and left + column_width + FLOAT_GAP > corner_rect.left():
                floor = corner_rect.top() - FLOAT_GAP
            y = floor
            for widget, width, height in sized:
                y -= height
                widget.setGeometry(area.center().x() - width // 2, y, width, height)
                widget.raise_()
                y -= SPACE_1
        finally:
            self._laying_out = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if watched is self._anchor or watched is self._host:
            if kind in _ANCHOR_EVENTS:
                self.relayout()
        elif kind in _ITEM_EVENTS:
            self.relayout()
        return False
