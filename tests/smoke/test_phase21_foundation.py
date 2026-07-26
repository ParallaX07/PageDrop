"""Foundation smoke tests — app start + rapid open/close PDFs."""

from __future__ import annotations

from pagedrop.core.capabilities import CAPABILITY_IDS, probe_all
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS


def _active_tab(window: MainWindow) -> PdfTab:
    tab = window._active_tab()
    assert isinstance(tab, PdfTab)
    return tab


def _wait_for_tab_loaded(qtbot, tab: PdfTab, path, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    qtbot.waitUntil(
        lambda: (
            tab.loader is not None
            and tab.pdf_path == str(path)
            and tab.thumbnail_grid._last_rendered_width_px
            == tab.thumbnail_grid._thumbnail_width_px
            and tab.thumbnail_grid._render_pool.activeThreadCount() == 0
            and len(tab.thumbnail_grid._cards) == tab.loader.page_count
        ),
        timeout=timeout,
    )


def test_smoke_app_starts_with_capability_registry(qtbot, isolated_settings):
    """Main window boots; capability probe returns structured statuses."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    assert window.isVisible()

    statuses = probe_all()
    assert set(statuses) == set(CAPABILITY_IDS)

    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)


def test_smoke_rapid_open_close_pdfs(qtbot, one_page_pdf, five_page_pdf, isolated_settings):
    """Repeated open → wait → close must leave the app stable."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    paths = [one_page_pdf, five_page_pdf, one_page_pdf, five_page_pdf]
    for path in paths:
        window._load_pdf(str(path))
        tab = _active_tab(window)
        _wait_for_tab_loaded(qtbot, tab, path)
        assert not tab.is_blank

        closed = window._try_close_tab(window._tab_manager.currentIndex())
        assert closed
        qtbot.waitUntil(lambda: _active_tab(window).is_blank, timeout=5000)

    assert window.isVisible()
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
