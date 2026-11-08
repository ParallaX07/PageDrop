"""One list row with text on the left and a value on the right."""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QRect, QSize, Qt
from PyQt6.QtGui import QFontMetrics, QPainter
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from pagedrop.ui.accessibility import prefers_high_contrast
from pagedrop.ui.theme import SPACE_2, current_theme, index_qcolor, tabular_font, token_qcolor

VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
MARKER_ROLE = Qt.ItemDataRole.UserRole + 2  # index colour token name, or None

MARKER_SIZE = 10
_VALUE_PIXEL_SIZE = 12  # caption


class ListRowDelegate(QStyledItemDelegate):
    """Left text, optional index-colour square, and a right-aligned tabular value.

    Colours are read from the theme on every paint, so a theme change needs no
    rebuild. By default the value keeps its width and the text is elided; with
    ``elide_value`` the text keeps its width and the value is middle-elided.
    """

    def __init__(self, parent=None, *, elide_value: bool = False) -> None:
        super().__init__(parent)
        self._elide_value = elide_value

    def _value_font(self, base):
        font = tabular_font(base)
        font.setPixelSize(_VALUE_PIXEL_SIZE)
        return font

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = "Ag"
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        return style.sizeFromContents(
            QStyle.ContentsType.CT_ItemViewItem, opt, QSize(0, 0), opt.widget
        )

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        theme = current_theme()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        primary = token_qcolor(theme.on_ink if selected else theme.text)
        muted = token_qcolor(
            theme.on_ink if selected else theme.text if prefers_high_contrast() else theme.text_muted
        )
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)

        painter.save()
        try:
            marker = index.data(MARKER_ROLE)
            if marker:
                square = QRect(
                    rect.left(),
                    rect.center().y() - MARKER_SIZE // 2 + 1,
                    MARKER_SIZE,
                    MARKER_SIZE,
                )
                painter.fillRect(square, index_qcolor(str(marker)))
                rect.setLeft(square.right() + 1 + SPACE_2)

            value = str(index.data(VALUE_ROLE) or "")
            value_font = self._value_font(opt.font)
            value_metrics = QFontMetrics(value_font)
            text_metrics = QFontMetrics(opt.font)
            gap = SPACE_2 if value and text else 0
            if self._elide_value:
                text_width = min(text_metrics.horizontalAdvance(text) + 1, rect.width())
                value_width = max(0, rect.width() - text_width - gap)
            else:
                value_width = min(value_metrics.horizontalAdvance(value) + 1, rect.width())
                text_width = max(0, rect.width() - value_width - gap)

            text_rect = QRect(rect.left(), rect.top(), text_width, rect.height())
            painter.setFont(opt.font)
            painter.setPen(primary)
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                text_metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_width),
            )
            if value:
                value_rect = QRect(rect.right() - value_width + 1, rect.top(), value_width, rect.height())
                mode = Qt.TextElideMode.ElideMiddle if self._elide_value else Qt.TextElideMode.ElideRight
                painter.setFont(value_font)
                painter.setPen(muted)
                painter.drawText(
                    value_rect,
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                    value_metrics.elidedText(value, mode, value_width),
                )
        finally:
            painter.restore()
