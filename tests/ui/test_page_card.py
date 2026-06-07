"""Phase 4 unit tests — PageCard."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel

from pagedrop.ui.page_card import PageCard


def test_set_thumbnail(qtbot):
    card = PageCard(0)
    qtbot.addWidget(card)

    pixmap = QPixmap(80, 100)
    pixmap.fill(QColor("red"))
    card.set_thumbnail(pixmap)

    label = card.findChild(QLabel, "")
    thumbnail_label = card._thumbnail_label
    shown = thumbnail_label.pixmap()
    assert shown is not None
    assert not shown.isNull()


def test_set_selected_styles(qtbot):
    card = PageCard(0)
    qtbot.addWidget(card)

    card.set_selected(False)
    unselected_style = card.styleSheet()

    card.set_selected(True)
    selected_style = card.styleSheet()

    assert unselected_style != selected_style
    assert "3px" in selected_style
    assert "1px" in unselected_style
