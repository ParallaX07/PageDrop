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


def test_empty_states_show_keyboard_hints(qtbot):
    merge = MergeFileGrid()
    convert = ConvertFileGrid()
    qtbot.addWidget(merge)
    qtbot.addWidget(convert)

    assert merge._empty_kbd.isVisibleTo(merge)
    assert convert._empty_kbd.isVisibleTo(convert)
    assert "Drop PDFs" in merge._empty_kbd.text()
    assert "Add PDFs" in merge._empty_kbd.text()
    assert "Drop images" in convert._empty_kbd.text()
    assert "Add images" in convert._empty_kbd.text()
    assert "Space" not in merge._empty_kbd.text()
    assert "Enter" not in convert._empty_kbd.text()
    assert merge._empty_kbd.objectName() == "MergeEmptyKbd"
    assert convert._empty_kbd.objectName() == "ConvertEmptyKbd"
    # R10b: muted Phosphor glyph, not the app logo.
    assert merge._empty_glyph_name == "stack"
    assert convert._empty_glyph_name == "images"
    assert merge._empty_logo.accessibleName() != "PageDrop logo"
    assert not merge._empty_logo.pixmap().isNull()
    assert not convert._empty_logo.pixmap().isNull()


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


def test_merge_thumbnail_failure_emits_rendering_error(qtbot, corrupt_pdf):
    grid = MergeFileGrid()
    qtbot.addWidget(grid)
    errors: list[str] = []
    grid.rendering_error.connect(errors.append)

    path = str(corrupt_pdf)
    grid.set_files([path], {path: 1})

    assert len(errors) == 1
    assert corrupt_pdf.name in errors[0]
    assert "unreadable" in errors[0].lower() or "corrupt" in errors[0].lower()
    assert path in grid._failed_paths


def test_convert_thumbnail_failure_emits_rendering_error(qtbot, tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")

    grid = ConvertFileGrid()
    qtbot.addWidget(grid)
    errors: list[str] = []
    grid.rendering_error.connect(errors.append)

    path = str(bad)
    grid.set_files([path], {path: (0, 0)})

    assert len(errors) == 1
    assert bad.name in errors[0]
    assert path in grid._failed_paths


def test_merge_window_surfaces_thumbnail_failure(qtbot, corrupt_pdf):
    from pagedrop.ui.merge_window import MergeWindow

    window = MergeWindow()
    qtbot.addWidget(window)
    path = str(corrupt_pdf)
    window._file_grid.set_files([path], {path: 1})

    assert corrupt_pdf.name in window.statusBar().currentMessage()


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
