"""Phase 3 smoke tests — MainWindow with fixture PDF."""

from __future__ import annotations

from pagedrop.ui.main_window import MainWindow


def test_smoke_main_window_open_pdf(qtbot, five_page_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    window._load_pdf(str(five_page_pdf))

    qtbot.waitUntil(
        lambda: window.windowTitle()
        == f"PageDrop: {five_page_pdf.name} (5 pages)",
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: "Loaded" in window.statusBar().currentMessage(),
        timeout=15000,
    )

    message = window.statusBar().currentMessage()
    assert "5" in message

    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
