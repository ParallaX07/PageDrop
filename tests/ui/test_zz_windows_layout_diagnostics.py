"""Temporary: report Windows shell metrics in the CI log."""

from __future__ import annotations

import sys

import pytest
from PyQt6.QtGui import QFontInfo, QFontMetrics
from PyQt6.QtWidgets import QApplication, QToolButton

from tests.ui.test_main_window import _open_loaded_window


@pytest.mark.skipif(sys.platform != "win32", reason="Windows metrics only")
def test_report_windows_shell_metrics(main_window, five_page_pdf, qtbot):
    app = QApplication.instance()
    lines = []

    def font_line(name, font):
        info = QFontInfo(font)
        metrics = QFontMetrics(font)
        lines.append(
            f"{name}: family={font.family()!r} families={font.families()} pt={font.pointSizeF()} "
            f"px={font.pixelSize()} resolved={info.family()!r} resolved_px={info.pixelSize()} "
            f"resolved_pt={info.pointSizeF()} 'File'w={metrics.horizontalAdvance('File')} "
            f"'Merge PDFs'w={metrics.horizontalAdvance('Merge PDFs')} height={metrics.height()}"
        )

    screen = app.primaryScreen()
    lines.append(
        f"platform={app.platformName()} style={app.style().name()} screen={screen.geometry()} "
        f"dpi={screen.logicalDotsPerInch()}/{screen.physicalDotsPerInch()} dpr={screen.devicePixelRatio()}"
    )
    lines.append(f"stylesheet_len={len(app.styleSheet())}")
    font_line("app", app.font())

    tab = _open_loaded_window(main_window, five_page_pdf, qtbot, width=960)
    menu_bar = main_window.menuBar()
    font_line("menubar", menu_bar.font())
    lines.append(f"window={main_window.size()} menubar={menu_bar.geometry()} hint={menu_bar.sizeHint()}")
    lines.append(f"controls={main_window._window_controls.geometry()} title={main_window._title_label.geometry()}")
    for action in menu_bar.actions():
        lines.append(f"  menu {action.text()!r} visible={action.isVisible()} geo={menu_bar.actionGeometry(action)}")
    ext = menu_bar.findChild(QToolButton)
    if ext is not None:
        lines.append(f"  menubar toolbutton {ext.objectName()!r} visible={ext.isVisible()} geo={ext.geometry()}")

    toolbar = main_window._toolbar
    lines.append(f"toolbar={toolbar.geometry()} hint={toolbar.sizeHint()} min={toolbar.minimumSizeHint()}")
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if widget is not None and widget.isVisible():
            lines.append(
                f"  tb {action.text()!r} {type(widget).__name__} geo={widget.geometry()} hint={widget.sizeHint()}"
            )
    toolbar_ext = toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    lines.append(f"  toolbar ext visible={toolbar_ext.isVisible() if toolbar_ext else None}")

    main_window.resize(480, 320)
    main_window._open_preview_at(0)
    qtbot.waitUntil(tab.is_preview_visible)
    viewer = tab.preview_widget
    viewer._set_navigation_panel_collapsed(False, persist=False)
    viewer._set_annot_rail_collapsed(False, persist=False)
    lines.append(f"viewer min={viewer.minimumSizeHint()}")
    layout = viewer.layout()
    for index in range(layout.count() if layout else 0):
        widget = layout.itemAt(index).widget()
        if widget is not None:
            lines.append(
                f"  viewer child {type(widget).__name__} {widget.objectName()!r} "
                f"min={widget.minimumSizeHint()} minsize={widget.minimumSize()}"
            )
    for child in viewer.findChildren(QToolButton):
        if child.isVisible() and child.minimumSizeHint().width() > 40:
            lines.append(f"  wide button {child.objectName()!r} {child.text()!r} min={child.minimumSizeHint()}")
    pytest.fail("\n".join(lines))
