"""Sanity check — Merge/Convert grids share BaseFileGrid shell; ThumbnailGrid does not."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent

from pagedrop.ui.base_file_grid import BaseFileGrid
from pagedrop.ui.convert_file_grid import ConvertFileGrid
from pagedrop.ui.merge_file_grid import MergeFileGrid
from pagedrop.ui.thumbnail_grid import ThumbnailGrid


def test_grid_inheritance():
    assert issubclass(MergeFileGrid, BaseFileGrid)
    assert issubclass(ConvertFileGrid, BaseFileGrid)
    assert not issubclass(ThumbnailGrid, BaseFileGrid)


def test_merge_reorder_by_drop(qtbot, one_page_pdf, five_page_pdf, tmp_path):
    third = tmp_path / "third.pdf"
    third.write_bytes(one_page_pdf.read_bytes())

    grid = MergeFileGrid()
    qtbot.addWidget(grid)
    paths = [str(one_page_pdf), str(five_page_pdf), str(third)]
    grid.set_files(paths, {paths[0]: 1, paths[1]: 5, paths[2]: 1})

    assert grid._reorder_by_drop([0], 3)
    assert grid.ordered_paths == [paths[1], paths[2], paths[0]]
    assert [card.path for card in grid._cards] == grid.ordered_paths
    assert [card.file_index for card in grid._cards] == [0, 1, 2]


def _press_key(widget, key: Qt.Key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(event)


def test_merge_grid_arrow_space_and_enter(qtbot, one_page_pdf, five_page_pdf, tmp_path):
    third = tmp_path / "third.pdf"
    third.write_bytes(one_page_pdf.read_bytes())

    grid = MergeFileGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    paths = [str(one_page_pdf), str(five_page_pdf), str(third)]
    grid.set_files(paths, {paths[0]: 1, paths[1]: 5, paths[2]: 1})
    grid.show()

    assert grid.focused_index == 0

    _press_key(grid, Qt.Key.Key_Right)
    assert grid.focused_index == 1

    _press_key(grid, Qt.Key.Key_Space)
    assert 1 in grid.selection_manager.selection

    previewed: list[str] = []
    grid.preview_requested.connect(previewed.append)
    _press_key(grid, Qt.Key.Key_Return)
    assert previewed == [paths[1]]
