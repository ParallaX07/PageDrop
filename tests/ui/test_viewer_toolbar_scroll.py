"""The viewer's toolbar scroll area sizes itself and survives app-wide restyles."""

from __future__ import annotations

import gc

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.accessibility import apply_app_stylesheet
from pagedrop.ui.pdf_viewer import PdfViewerWidget
from pagedrop.ui.settings import set_light_theme


def test_toolbar_height_grows_by_the_scroll_bar_only_when_narrow(qtbot):
    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    scroll = viewer._toolbar_scroll
    bar = viewer._toolbar
    bar_height = bar.sizeHint().height()
    bar_scroll_height = scroll.horizontalScrollBar().sizeHint().height()

    viewer.resize(3000, 600)
    viewer.show()
    qtbot.waitExposed(viewer)
    qtbot.waitUntil(lambda: scroll.height() == bar_height)
    assert scroll.horizontalScrollBar().maximum() == 0

    viewer.resize(bar.minimumSizeHint().width() // 2, 600)
    qtbot.waitUntil(lambda: scroll.horizontalScrollBar().maximum() > 0)
    qtbot.waitUntil(lambda: scroll.height() == bar_height + bar_scroll_height)

    viewer.resize(3000, 600)
    qtbot.waitUntil(lambda: scroll.height() == bar_height)


def test_restyling_after_a_viewer_is_deleted_does_not_crash(qtbot, isolated_settings):
    app = QApplication.instance()
    previous = app.styleSheet()
    viewer = PdfViewerWidget()
    viewer.resize(300, 300)
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer.deleteLater()
    del viewer
    gc.collect()

    try:
        apply_app_stylesheet()
        apply_app_stylesheet()
        set_light_theme(True)
        apply_app_stylesheet()
        set_light_theme(False)
        apply_app_stylesheet()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        apply_app_stylesheet()
    finally:
        app.setStyleSheet(previous)
