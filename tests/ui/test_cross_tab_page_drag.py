"""Phase 20 UI tests — same-window cross-tab page drag via tab bar."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    encode_page_indices,
    encode_page_refs,
)
from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_loader import PdfEmptyError
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import RENDER_TIMEOUT_MS, file_sha256
from tests.ui.test_cross_window_page_drag import BAD_PAYLOADS


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


def _model_refs(tab: PdfTab) -> list[tuple[str, int]]:
    model = tab.edit_model
    assert model is not None
    return [
        (model.page_at(i).source_path, model.page_at(i).source_index)
        for i in range(model.logical_count())
    ]


def _tab_bar_drop(
    window: MainWindow,
    source_tab: PdfTab,
    target_index: int,
    logical_indices: list[int],
    *,
    shift: bool = False,
    monkeypatch=None,
) -> bool:
    source_grid = source_tab.thumbnail_grid
    assert source_grid._model is not None
    refs = [source_grid._model.page_at(i) for i in logical_indices]
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, encode_page_refs(refs))
    mime.setData(INTERNAL_PAGE_MIME, encode_page_indices(logical_indices))

    if monkeypatch is not None:
        monkeypatch.setattr(
            ThumbnailGrid,
            "_grid_for_widget",
            staticmethod(lambda _widget: source_grid),
        )

    tab_bar = window._tab_manager.detachable_tab_bar
    rect = tab_bar.tabRect(target_index)
    modifiers = (
        Qt.KeyboardModifier.ShiftModifier
        if shift
        else Qt.KeyboardModifier.NoModifier
    )
    drop = QDropEvent(
        QPointF(rect.center()),
        Qt.DropAction.MoveAction if shift else Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        modifiers,
    )
    tab_bar.dropEvent(drop)
    return drop.isAccepted()


def _two_loaded_tabs(
    main_window: MainWindow,
    one_page_pdf,
    five_page_pdf,
    monkeypatch,
    qtbot,
) -> tuple[PdfTab, PdfTab]:
    """Return (source=five-page tab, target=one-page tab)."""
    main_window.showMinimized()
    _open_single(main_window, five_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    _open_single(main_window, one_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))
    return _tab_at(main_window, 0), _tab_at(main_window, 1)


def test_drop_on_tab_bar_appends_to_end(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    before = _model_refs(target)

    assert _tab_bar_drop(main_window, source, 1, [1, 3], monkeypatch=monkeypatch)

    refs = _model_refs(target)
    assert len(refs) == 3
    assert refs == [
        (str(one_page_pdf), 0),
        (str(five_page_pdf), 1),
        (str(five_page_pdf), 3),
    ]
    assert before == [(str(one_page_pdf), 0)]
    assert source.edit_model is not None
    assert source.edit_model.logical_count() == 5


def test_drop_on_blank_tab_inits_model(
    main_window, five_page_pdf, monkeypatch, qtbot
):
    main_window.showMinimized()
    _open_single(main_window, five_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    source = _tab_at(main_window, 0)
    blank = main_window._tab_manager.add_blank_tab()
    blank_index = main_window._tab_manager.indexOf(blank)

    assert _tab_bar_drop(
        main_window, source, blank_index, [0, 2], monkeypatch=monkeypatch
    )

    assert not blank.is_blank
    assert blank.edit_model is not None
    assert blank.edit_model.logical_count() == 2
    qtbot.waitUntil(
        lambda: len(blank.thumbnail_grid._cards) == 2,
        timeout=RENDER_TIMEOUT_MS,
    )
    assert _model_refs(blank) == [
        (str(five_page_pdf), 0),
        (str(five_page_pdf), 2),
    ]


def test_shift_drop_moves_from_source_tab(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    main_window._tab_manager.setCurrentIndex(0)

    assert _tab_bar_drop(
        main_window, source, 1, [2], shift=True, monkeypatch=monkeypatch
    )

    assert _model_refs(target)[-1] == (str(five_page_pdf), 2)
    assert source.edit_model is not None
    assert source.edit_model.logical_count() == 4
    assert source.is_dirty
    assert target.is_dirty


def test_drop_does_not_switch_active_tab(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    main_window._tab_manager.setCurrentIndex(0)
    assert main_window._tab_manager.currentIndex() == 0

    assert _tab_bar_drop(main_window, source, 1, [0], monkeypatch=monkeypatch)

    assert main_window._tab_manager.currentIndex() == 0
    assert main_window._active_tab() is source
    assert target.edit_model is not None
    assert target.edit_model.logical_count() == 2


def test_drop_on_source_tab_rejected(
    main_window, five_page_pdf, monkeypatch, qtbot
):
    main_window.showMinimized()
    _open_single(main_window, five_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    source = _tab_at(main_window, 0)
    before = _model_refs(source)
    errors: list[str] = []
    source.thumbnail_grid.page_transfer_failed.connect(errors.append)

    assert not _tab_bar_drop(
        main_window, source, 0, [1], monkeypatch=monkeypatch
    )

    assert _model_refs(source) == before
    assert errors == ["Drop on another tab to append pages"]


def test_target_tab_title_shows_dirty_after_drop(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    target_index = main_window._tab_manager.indexOf(target)
    main_window._tab_manager.setCurrentIndex(0)
    assert "*" not in main_window._tab_manager.tabText(target_index)

    assert _tab_bar_drop(main_window, source, target_index, [0], monkeypatch=monkeypatch)

    assert target.is_dirty
    assert "*" in main_window._tab_manager.tabText(target_index)
    assert main_window._tab_manager.currentIndex() == 0


@pytest.fixture
def modal_calls(monkeypatch):
    calls: list[str] = []
    for name in ("critical", "warning"):
        monkeypatch.setattr(
            QMessageBox,
            name,
            staticmethod(lambda _parent, _title, text, _n=name: calls.append(text)),
        )
    return calls


def _raw_tab_bar_drop(
    window: MainWindow, target_index: int, payload: bytes, source_grid, monkeypatch,
    *, shift: bool = False,
) -> bool:
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, payload)
    monkeypatch.setattr(
        ThumbnailGrid, "_grid_for_widget", staticmethod(lambda _w: source_grid)
    )
    tab_bar = window._tab_manager.detachable_tab_bar
    drop = QDropEvent(
        QPointF(tab_bar.tabRect(target_index).center()),
        Qt.DropAction.MoveAction if shift else Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,
    )
    tab_bar.dropEvent(drop)
    return drop.isAccepted()


@pytest.mark.parametrize(
    "payload",
    [
        *BAD_PAYLOADS,
        pytest.param(
            encode_page_refs([PageRef("PLACEHOLDER", 99)]), id="index-past-end"
        ),
        pytest.param(
            encode_page_refs([PageRef("PLACEHOLDER", -1)]), id="negative-index"
        ),
    ],
)
def test_bad_tab_bar_payload_is_rejected_visibly_on_inactive_tab(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot, modal_calls, payload
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    main_window._tab_manager.setCurrentIndex(0)  # the drop target is inactive
    payload = payload.replace(b"PLACEHOLDER", str(five_page_pdf).encode())
    before = _model_refs(target)
    source_hash = file_sha256(five_page_pdf)
    errors: list[str] = []
    target.thumbnail_grid.page_transfer_failed.connect(errors.append)

    assert not _raw_tab_bar_drop(
        main_window, 1, payload, source.thumbnail_grid, monkeypatch
    )

    assert len(errors) == 1
    assert modal_calls == [errors[0]]
    assert main_window._status_by_page[target] == errors[0]
    assert main_window._status_by_page.get(source) != errors[0]
    assert _model_refs(target) == before
    assert file_sha256(five_page_pdf) == source_hash


def test_tab_bar_drop_from_another_process_is_reported(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot, modal_calls
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    assert source.edit_model is not None
    payload = encode_page_refs([source.edit_model.page_at(0)])
    before = _model_refs(target)

    assert not _raw_tab_bar_drop(main_window, 1, payload, None, monkeypatch)

    assert modal_calls == [
        "Could not transfer pages: tabs can't accept drops from another PageDrop "
        "process. Drop on the page grid instead."
    ]
    assert _model_refs(target) == before


def test_pdf_drop_failure_on_inactive_tab_is_reported(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot, modal_calls
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    main_window._tab_manager.setCurrentIndex(0)
    main_window._status_by_page[source] = "Marker"

    target.thumbnail_grid.pdf_drop_failed.emit(PdfEmptyError("PDF has no pages: x"))

    assert modal_calls == ["PDF has no pages: x"]
    assert main_window._status_by_page[target] == "Ready"
    assert main_window._status_by_page[source] == "Marker"


def test_shift_drop_from_another_process_toasts_copy_not_move(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    source, target = _two_loaded_tabs(
        main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
    )
    main_window._tab_manager.setCurrentIndex(1)
    assert source.edit_model is not None
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window,
        "_show_toast",
        lambda message, *, kind="info", on_undo=None: toasts.append((message, kind)),
    )
    payload = encode_page_refs([source.edit_model.page_at(0)])
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, payload)
    monkeypatch.setattr(
        ThumbnailGrid, "_grid_for_widget", staticmethod(lambda _w: None)
    )
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
    )

    target.thumbnail_grid.dropEvent(drop)

    assert drop.isAccepted()
    assert len(toasts) == 1
    message, kind = toasts[0]
    assert message == (
        "Copied 1 page, not moved: the source is in another PageDrop process"
    )
    assert kind == "info"
    assert source.edit_model.logical_count() == 5
    assert len(_model_refs(target)) == 2
