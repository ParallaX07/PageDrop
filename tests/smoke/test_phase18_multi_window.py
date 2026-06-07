"""Phase 18 smoke tests — multi-window copy, move, tear-off, Save As verification."""

from __future__ import annotations

from pathlib import Path

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


def _model_refs(tab: PdfTab) -> list[tuple[str, int]]:
    model = tab.edit_model
    assert model is not None
    return [
        (model.page_at(i).source_path, model.page_at(i).source_index)
        for i in range(model.logical_count())
    ]


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


def _cross_window_drop(
    target_tab: PdfTab,
    source_tab: PdfTab,
    logical_indices: list[int],
    *,
    shift: bool = False,
    drop_index: int = 0,
) -> bool:
    source = source_tab.thumbnail_grid
    target = target_tab.thumbnail_grid
    assert source._model is not None
    refs = [source._model.page_at(i) for i in logical_indices]
    mime = _transfer_mime(refs, logical_indices)
    return target._handle_cross_window_drop(
        refs,
        drop_index,
        move=shift,
        source_grid=source,
        mime=mime,
    )


def _windows_added(manager, before: frozenset) -> list:
    return [window for window in manager.windows if window not in before]


def test_smoke_multi_window_copy_move_detach_save_as(
    qtbot,
    one_page_pdf,
    five_page_pdf,
    tmp_path,
    monkeypatch,
    qapp,
):
    from pagedrop.ui.window_manager import WindowManager

    manager = WindowManager.instance_or_none() or WindowManager.init(qapp)
    window_a = manager.open_new_window()
    window_b = manager.open_new_window()
    qtbot.addWidget(window_a)
    qtbot.addWidget(window_b)
    window_a.showMinimized()
    window_b.showMinimized()

    tab_a = _tab_at(window_a, 0)
    tab_b = _tab_at(window_b, 0)
    window_a._load_pdf(str(five_page_pdf), tab=tab_a)
    window_b._load_pdf(str(one_page_pdf), tab=tab_b)
    _wait_for_tab_loaded(qtbot, tab_a)
    _wait_for_tab_loaded(qtbot, tab_b)

    assert _cross_window_drop(tab_b, tab_a, [2], drop_index=1)
    assert _model_refs(tab_b) == [
        (str(one_page_pdf), 0),
        (str(five_page_pdf), 2),
    ]
    assert tab_a.edit_model is not None
    assert tab_a.edit_model.logical_count() == 5

    assert _cross_window_drop(tab_a, tab_b, [0], shift=True, drop_index=0)
    assert _model_refs(tab_a) == [
        (str(one_page_pdf), 0),
        (str(five_page_pdf), 0),
        (str(five_page_pdf), 1),
        (str(five_page_pdf), 2),
        (str(five_page_pdf), 3),
        (str(five_page_pdf), 4),
    ]
    assert _model_refs(tab_b) == [(str(five_page_pdf), 2)]

    windows_before = frozenset(manager.windows)
    window_b._detach_tab_to_new_window(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == len(windows_before) + 1,
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: window_b._tab_manager.count() == 1 and _tab_at(window_b, 0).is_blank,
        timeout=5000,
    )

    window_c = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(window_c)
    tab_c = _tab_at(window_c, 0)
    _wait_for_tab_loaded(qtbot, tab_c)
    assert _model_refs(tab_c) == [(str(five_page_pdf), 2)]

    output_a = tmp_path / "window_a.pdf"
    output_c = tmp_path / "window_c.pdf"
    save_paths = iter([str(output_a), str(output_c)])
    saved: list[str] = []

    def pick_save(*args, **kwargs):
        path = next(save_paths)
        saved.append(path)
        return (path, "PDF Files (*.pdf)")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", pick_save)

    assert window_a._save_as(tab_a) is True
    assert window_c._save_as(tab_c) is True

    assert output_a.exists()
    assert output_c.exists()
    assert len(PdfReader(str(output_a)).pages) == 6
    assert len(PdfReader(str(output_c)).pages) == 1
    assert {Path(path).name for path in saved} == {"window_a.pdf", "window_c.pdf"}
