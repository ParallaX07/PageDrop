"""Phase 19 smoke tests — Create PDF workflow."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog

from pagedrop.core.image_to_pdf import images_to_individual_pdfs, images_to_single_pdf
from pagedrop.ui.convert_window import ConvertWindow


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


def _page_count(path: Path | str) -> int:
    doc = fitz.open(str(path))
    try:
        return doc.page_count
    finally:
        doc.close()


def test_smoke_combine_and_separate_modes(qtbot, tmp_path, monkeypatch):
    png = tmp_path / "first.png"
    jpeg = tmp_path / "second.jpg"
    third = tmp_path / "third.png"
    _write_test_image(png, 111, 100)
    _write_test_image(jpeg, 222, 100)
    _write_test_image(third, 333, 100)

    original_bytes = {
        str(png.resolve()): png.read_bytes(),
        str(jpeg.resolve()): jpeg.read_bytes(),
        str(third.resolve()): third.read_bytes(),
    }
    paths = [str(png), str(jpeg), str(third)]

    combined = tmp_path / "all_images.pdf"
    images_to_single_pdf(paths, str(combined))
    assert _page_count(combined) == 3

    separate_dir = tmp_path / "separate"
    written = images_to_individual_pdfs(paths, str(separate_dir))
    assert len(written) == 3
    for path in written:
        assert _page_count(path) == 1

    window = ConvertWindow()
    qtbot.addWidget(window)
    window.showMinimized()
    window._add_paths(paths)

    ui_combined = tmp_path / "ui_combined.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(ui_combined), "PDF Files (*.pdf)"),
    )
    window._create_pdfs()
    qtbot.waitUntil(lambda: not window._converting, timeout=10000)
    assert _page_count(ui_combined) == 3

    ui_separate_dir = tmp_path / "ui_separate"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(ui_separate_dir),
    )
    window._separate_mode_action.setChecked(True)
    window._create_pdfs()
    qtbot.waitUntil(lambda: not window._converting, timeout=10000)

    ui_written = sorted(ui_separate_dir.glob("*.pdf"))
    assert len(ui_written) == 3
    for path in ui_written:
        assert _page_count(path) == 1

    for path, data in original_bytes.items():
        assert Path(path).read_bytes() == data
