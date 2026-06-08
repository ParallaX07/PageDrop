"""Phase 20 smoke tests — cross-tab copy/cut, blank-tab init, Save As, Ctrl+Tab."""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFileDialog
from pypdf import PdfReader

from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    encode_page_indices,
    encode_page_refs,
)
from pagedrop.core.pdf_editor import PageRef
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import RENDER_TIMEOUT_MS


def _tab_at(window: MainWindow, index: int) -> PdfTab:
    widget = window._tab_manager.widget(index)
    assert isinstance(widget, PdfTab)
    return widget


def _wait_for_tab_loaded(qtbot, tab: PdfTab, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    qtbot.waitUntil(
        lambda: (
            tab.loader is not None
            and tab.thumbnail_grid._last_rendered_width_px
            == tab.thumbnail_grid._thumbnail_width_px
            and tab.thumbnail_grid._render_pool.activeThreadCount() == 0
            and len(tab.thumbnail_grid._cards) == tab.loader.page_count
        ),
        timeout=timeout,
    )


def _open_single(
    window: MainWindow,
    path,
    monkeypatch,
    *,
    target: str = "current",
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(path)], "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(window, "_ask_open_target", lambda _: target)
    window._open_pdf()


def _transfer_mime(refs: list[PageRef], logical_indices: list[int]):
    class _Mime:
        def hasFormat(self, fmt: str) -> bool:
            return fmt in (PAGE_TRANSFER_MIME, INTERNAL_PAGE_MIME)

        def data(self, fmt: str) -> bytes:
            if fmt == PAGE_TRANSFER_MIME:
                return encode_page_refs(refs)
            if fmt == INTERNAL_PAGE_MIME:
                return encode_page_indices(logical_indices)
            return b""

    return _Mime()


def _tab_bar_drop(
    window: MainWindow,
    source_tab: PdfTab,
    target_tab: PdfTab,
    logical_indices: list[int],
    *,
    shift: bool = False,
    monkeypatch,
) -> bool:
    source_grid = source_tab.thumbnail_grid
    assert source_grid._model is not None
    refs = [source_grid._model.page_at(i) for i in logical_indices]
    mime = _transfer_mime(refs, logical_indices)
    monkeypatch.setattr(
        ThumbnailGrid,
        "_grid_for_widget",
        staticmethod(lambda _widget: source_grid),
    )
    target_index = window._tab_manager.indexOf(target_tab)
    return target_tab.thumbnail_grid.handle_tab_bar_page_drop(
        refs,
        move=shift,
        source_grid=source_grid,
        mime=mime,
    )


def _trigger_shortcut(window: MainWindow, sequence: str) -> None:
    target = QKeySequence(sequence)
    for action in window.actions():
        if action.shortcut() == target:
            action.trigger()
            return
    raise AssertionError(f"No action registered for {sequence}")


def test_smoke_cross_tab_copy_cut_save_as_ctrl_tab(
    qtbot,
    one_page_pdf,
    five_page_pdf,
    tmp_path,
    monkeypatch,
):
    window = MainWindow()
    qtbot.addWidget(window)
    window.showMinimized()

    _open_single(window, five_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(window, 0))
    source = _tab_at(window, 0)

    _open_single(window, one_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(window, 1))
    target = _tab_at(window, 1)

    blank = window._tab_manager.add_blank_tab()
    window._tab_manager.setCurrentIndex(0)

    assert _tab_bar_drop(window, source, target, [1, 3], monkeypatch=monkeypatch)
    assert target.edit_model is not None
    assert target.edit_model.logical_count() == 3
    assert not source.is_dirty
    assert target.is_dirty
    assert window._tab_manager.currentIndex() == 0

    assert _tab_bar_drop(
        window, source, target, [0], shift=True, monkeypatch=monkeypatch
    )
    assert target.edit_model.logical_count() == 4
    assert source.edit_model is not None
    assert source.edit_model.logical_count() == 4
    assert source.is_dirty

    assert _tab_bar_drop(window, source, blank, [0, 1], monkeypatch=monkeypatch)
    assert blank.edit_model is not None
    assert blank.edit_model.logical_count() == 2
    blank_index = window._tab_manager.indexOf(blank)
    assert "*" in window._tab_manager.tabText(blank_index)

    output = tmp_path / "blank_init.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )
    assert window._save_as(blank) is True
    assert output.is_file()
    assert len(PdfReader(str(output)).pages) == 2
    assert not blank.is_dirty
    assert window._tab_manager.tabText(blank_index) == "blank_init.pdf"

    window._tab_manager.setCurrentIndex(0)
    _trigger_shortcut(window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: window._tab_manager.currentIndex() == 1,
        timeout=5000,
    )
    _trigger_shortcut(window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: window._tab_manager.currentIndex() == 0,
        timeout=5000,
    )
