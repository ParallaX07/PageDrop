"""Phase 19 UI tests — Create PDF window."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.convert_window import ConvertWindow
from pagedrop.ui.main_window import MainWindow


def _write_test_image(path: Path, width: int, height: int) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=height)
        page.draw_rect(
            fitz.Rect(0, 0, width, height),
            color=(0.4, 0.4, 0.4),
            fill=(0.4, 0.4, 0.4),
        )
        pix = page.get_pixmap()
        pix.save(str(path))
    finally:
        doc.close()


def _convert_window(qtbot) -> ConvertWindow:
    window = ConvertWindow()
    qtbot.addWidget(window)
    return window


def test_add_images_populates_grid(qtbot, tmp_path):
    png = tmp_path / "alpha.png"
    jpeg = tmp_path / "bravo.jpg"
    _write_test_image(png, 100, 100)
    _write_test_image(jpeg, 120, 120)

    window = _convert_window(qtbot)
    window._add_paths([str(png), str(jpeg)])

    assert window._model.file_count() == 2
    assert len(window._file_grid._cards) == 2
    names = [Path(path).name for path in window._file_grid.ordered_paths]
    assert names == [png.name, jpeg.name]


def test_reject_pdf_on_add(qtbot, one_page_pdf):
    window = _convert_window(qtbot)
    window._add_paths([str(one_page_pdf)])

    assert window._model.file_count() == 0
    assert len(window._file_grid._cards) == 0


def test_output_mode_toggle_updates_action_label(qtbot):
    window = _convert_window(qtbot)

    assert window._create_action.text() == "Save PDF…"

    window._separate_mode_action.setChecked(True)
    assert window._create_action.text() == "Choose folder…"

    window._single_mode_action.setChecked(True)
    assert window._create_action.text() == "Save PDF…"


def test_convert_disabled_when_empty(qtbot, tmp_path):
    png = tmp_path / "solo.png"
    _write_test_image(png, 100, 100)

    window = _convert_window(qtbot)
    assert not window._create_action.isEnabled()

    window._add_paths([str(png)])
    assert window._create_action.isEnabled()


def test_separate_mode_uses_folder_dialog(qtbot, tmp_path, monkeypatch):
    png = tmp_path / "alpha.png"
    _write_test_image(png, 100, 100)
    out_dir = tmp_path / "output"

    save_called = {"value": False}

    def _reject_save(*args, **kwargs):
        save_called["value"] = True
        return ("", "")

    folder_called = {"value": False}

    def _pick_folder(*args, **kwargs):
        folder_called["value"] = True
        return str(out_dir)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _reject_save)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", _pick_folder)

    window = _convert_window(qtbot)
    window._add_paths([str(png)])
    window._separate_mode_action.setChecked(True)
    window._create_pdfs()

    qtbot.waitUntil(lambda: not window._converting, timeout=10000)

    assert folder_called["value"]
    assert not save_called["value"]
    assert (out_dir / "alpha.pdf").is_file()


def test_menubar_create_pdf_beside_merge(main_window, qtbot):
    menubar = main_window.menuBar()
    labels = [action.text().replace("&", "") for action in menubar.actions()]

    merge_index = labels.index("Merge PDFs")
    assert labels[merge_index + 1] == "Create PDF"

    create_action = menubar.actions()[merge_index + 1]
    create_action.trigger()

    qtbot.waitUntil(
        lambda: main_window._convert_window is not None
        and main_window._convert_window.isVisible(),
        timeout=5000,
    )
    assert main_window._convert_window.windowTitle() == "Create PDF"


def test_toolbar_zoom_before_primary_action(qtbot):
    """Convert matches Merge: after the spacer, zoom then Save PDF (+ radios)."""
    from PyQt6.QtWidgets import QToolBar

    window = _convert_window(qtbot)
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    create_btn = toolbar.widgetForAction(window._create_action)
    assert create_btn is not None

    children = list(toolbar.children())
    zoom_i = children.index(window._zoom_controls)
    create_i = children.index(create_btn)
    radio_i = children.index(window._single_mode_action)
    assert zoom_i < create_i < radio_i
