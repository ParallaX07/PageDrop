"""Phase 14 UI tests — inbound PDF drop onto the thumbnail grid."""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.utils.temp_manager import TempManager
from tests.conftest import wait_for_grid_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def _load_grid(qtbot, pdf_path) -> ThumbnailGrid:
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    grid.show()
    loader = PdfLoader(str(pdf_path))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    grid._reflow_grid(force=True)
    return grid


def _load_tab(qtbot, pdf_path) -> PdfTab:
    tab = PdfTab(TempManager())
    qtbot.addWidget(tab)
    tab.resize(900, 650)
    tab.show()
    tab.load_pdf(str(pdf_path))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)
    tab.thumbnail_grid._reflow_grid(force=True)
    return tab


def _model_refs(tab: PdfTab) -> list[tuple[str, int]]:
    model = tab.edit_model
    assert model is not None
    return [
        (model.page_at(i).source_path, model.page_at(i).source_index)
        for i in range(model.logical_count())
    ]


def test_drop_pdf_inserts_all_pages_at_index(qtbot, five_page_pdf, tmp_path):
    insert_pdf = tmp_path / "insert.pdf"
    generate_n_page(insert_pdf, 3)

    tab = _load_tab(qtbot, five_page_pdf)
    grid = tab.thumbnail_grid
    primary = str(five_page_pdf)

    assert grid.insert_pdf_pages([str(insert_pdf)], drop_index=2)

    assert tab.edit_model is not None
    assert tab.edit_model.logical_count() == 8
    assert _model_refs(tab) == [
        (primary, 0),
        (primary, 1),
        (str(insert_pdf), 0),
        (str(insert_pdf), 1),
        (str(insert_pdf), 2),
        (primary, 2),
        (primary, 3),
        (primary, 4),
    ]

    assert grid.insert_pdf_pages([primary], drop_index=0)
    assert tab.edit_model.logical_count() == 13
    assert _model_refs(tab)[:5] == [(primary, i) for i in range(5)]


def test_drop_rejects_non_pdf(qtbot, five_page_pdf, tmp_path):
    grid = _load_grid(qtbot, five_page_pdf)
    text_file = tmp_path / "notes.txt"
    text_file.write_text("not a pdf", encoding="utf-8")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(text_file))])
    assert grid.pdf_paths_from_mime(mime) == []
    assert not grid._accepts_inbound_pdf_drop(mime)

    pos = QPoint(10, 10)
    enter = QDragEnterEvent(
        pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    grid.dragEnterEvent(enter)
    assert not enter.isAccepted()

    drop = QDropEvent(
        QPointF(pos),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    grid.dropEvent(drop)
    assert not drop.isAccepted()
    assert grid._model is not None
    assert grid._model.logical_count() == 5


def test_drop_multiple_files_sorted(qtbot, five_page_pdf, tmp_path):
    z_pdf = tmp_path / "z_last.pdf"
    a_pdf = tmp_path / "a_first.pdf"
    generate_n_page(z_pdf, 1)
    generate_n_page(a_pdf, 2)

    tab = _load_tab(qtbot, five_page_pdf)
    primary = str(five_page_pdf)

    assert tab.thumbnail_grid.insert_pdf_pages(
        [str(z_pdf), str(a_pdf)],
        drop_index=0,
    )

    assert _model_refs(tab) == [
        (str(a_pdf), 0),
        (str(a_pdf), 1),
        (str(z_pdf), 0),
        (primary, 0),
        (primary, 1),
        (primary, 2),
        (primary, 3),
        (primary, 4),
    ]


def test_drop_marks_tab_dirty(qtbot, five_page_pdf, one_page_pdf):
    tab = _load_tab(qtbot, five_page_pdf)
    assert not tab.is_dirty

    assert tab.thumbnail_grid.insert_pdf_pages([str(one_page_pdf)], drop_index=5)
    assert tab.is_dirty
    assert tab.edit_model is not None
    assert tab.edit_model.is_dirty()


def test_blank_tab_accepts_inbound_pdf_drop(main_window, five_page_pdf, qtbot):
    from tests.conftest import wait_for_pdf_loaded

    tab = main_window._active_tab()
    assert tab is not None and tab.is_blank
    grid = tab.thumbnail_grid
    assert "drop" in grid._empty_hint.text().lower()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(five_page_pdf))])
    assert grid._accepts_inbound_pdf_drop(mime)

    pos = QPoint(10, 10)
    enter = QDragEnterEvent(
        pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    grid.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert main_window.statusBar().currentMessage() == "Release to place pages"

    drop = QDropEvent(
        QPointF(pos),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    grid.dropEvent(drop)
    assert drop.isAccepted()
    wait_for_pdf_loaded(qtbot, main_window)
    assert not tab.is_blank
    assert tab.edit_model is not None
    assert tab.edit_model.logical_count() == 5
