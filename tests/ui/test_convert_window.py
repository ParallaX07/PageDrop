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
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(png)])
    window._separate_mode_action.setChecked(True)
    window._create_pdfs()

    qtbot.waitUntil(lambda: not window._converting, timeout=10000)

    assert folder_called["value"]
    assert not save_called["value"]
    assert (out_dir / "alpha.pdf").is_file()
    assert window._result_bar.isVisible()
    assert window._result_bar._path == str(out_dir / "alpha.pdf")
    assert window._toast.isVisible()
    assert window._toast._message.accessibleName()
    assert "Created 1 PDF file" in window._toast._message.text()
    assert "showing first" not in window._toast._message.text()


def test_separate_mode_multi_file_copy_mentions_showing_first(
    qtbot, tmp_path, monkeypatch
):
    """O12: N>1 separate outputs name count and that actions bind to the first."""
    alpha = tmp_path / "alpha.png"
    bravo = tmp_path / "bravo.png"
    _write_test_image(alpha, 100, 100)
    _write_test_image(bravo, 120, 120)
    out_dir = tmp_path / "output"

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(out_dir),
    )

    window = _convert_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(alpha), str(bravo)])
    window._separate_mode_action.setChecked(True)
    window._create_pdfs()

    qtbot.waitUntil(lambda: not window._converting, timeout=10000)

    assert (out_dir / "alpha.pdf").is_file()
    assert (out_dir / "bravo.pdf").is_file()
    status = window.statusBar().currentMessage()
    toast = window._toast._message.text()
    bar = window._result_bar._label.text()
    assert "Created 2 PDF files" in status
    assert "showing first" in status
    assert status == toast == bar
    assert window._result_bar._path == str(out_dir / "alpha.pdf")
    assert window.editor is None


def test_create_pdf_success_shows_toast_and_result_actions(qtbot, tmp_path, monkeypatch):
    png = tmp_path / "solo.png"
    _write_test_image(png, 100, 100)
    output = tmp_path / "solo.pdf"

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )

    window = _convert_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(png)])
    window._create_pdfs()

    qtbot.waitUntil(lambda: not window._converting, timeout=10000)
    assert output.is_file()
    assert "Created PDF from 1 image" in window.statusBar().currentMessage()
    assert window._result_bar.isVisible()
    assert window._result_bar._path == str(output)
    assert window._toast.isVisible()
    assert window._toast._message.accessibleName() == window._toast._message.text()
    assert window.editor is None
    assert window._result_bar._preview_btn.text() == "Preview"
    assert window._result_bar._open_btn.text() == "Open in editor"
    assert window._result_bar._folder_btn.text() == "Show in folder"


def test_menubar_create_pdf_beside_merge(main_window, qtbot):
    menubar = main_window.menuBar()
    labels = [action.text().replace("&", "") for action in menubar.actions()]

    merge_index = labels.index("Merge PDFs")
    assert labels[merge_index + 1] == "Create PDF"

    create_action = menubar.actions()[merge_index + 1]
    create_action.trigger()

    qtbot.waitUntil(
        lambda: main_window._convert_window is not None
        and main_window._tab_manager.indexOf(main_window._convert_window) >= 0,
        timeout=5000,
    )
    assert main_window._convert_window.windowTitle() == "Create PDF"
    assert main_window._tab_manager.currentWidget() is main_window._convert_window


def test_toolbar_zoom_before_primary_action(qtbot):
    """Convert matches Merge: after the spacer, zoom then Save PDF (+ mode)."""
    from PyQt6.QtWidgets import QToolBar

    window = _convert_window(qtbot)
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    create_btn = toolbar.widgetForAction(window._create_action)
    assert create_btn is not None

    children = list(toolbar.children())
    zoom_i = children.index(window._zoom_controls)
    create_i = children.index(create_btn)
    mode_i = children.index(window._output_mode_host)
    assert zoom_i < create_i < mode_i


def test_convert_toolbar_has_no_radio_buttons(qtbot):
    """R13: Create PDF mode uses checkable tool buttons, not QRadioButton."""
    from PyQt6.QtWidgets import QRadioButton, QToolBar, QToolButton

    window = _convert_window(qtbot)
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    assert toolbar.findChildren(QRadioButton) == []
    assert isinstance(window._single_mode_action, QToolButton)
    assert isinstance(window._separate_mode_action, QToolButton)
    assert window._single_mode_action.isCheckable()
    assert window._separate_mode_action.isCheckable()
    assert window._output_mode_host.objectName() == "OutputModeHost"
    assert window._single_mode_action.parent() is window._output_mode_host
    assert window._separate_mode_action.parent() is window._output_mode_host

    assert window._create_action.text() == "Save PDF…"
    window._separate_mode_action.setChecked(True)
    assert window._create_action.text() == "Choose folder…"
    window._single_mode_action.setChecked(True)
    assert window._create_action.text() == "Save PDF…"
    assert window._output_mode == "single"


def test_image_preview_arrow_keys_and_zoom(qtbot, tmp_path):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from pagedrop.ui.theme import ZOOM_WHEEL_STEP

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _write_test_image(a, 400, 300)
    _write_test_image(b, 400, 300)

    window = _convert_window(qtbot)
    window._add_paths([str(a), str(b)])
    window._open_preview(str(a))
    qtbot.waitUntil(lambda: window._is_preview_visible(), timeout=5000)

    preview = window._preview_widget
    assert preview.current_index == 0
    initial_width = preview.render_width_px

    qtbot.keyClick(preview, Qt.Key.Key_Right)
    assert preview.current_index == 1
    assert window._file_grid.selection_manager.selection == {1}

    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    preview._scroll.wheelEvent(event)
    assert preview.render_width_px >= initial_width + ZOOM_WHEEL_STEP
    assert preview._manual_zoom

    preview.reset_zoom_to_fit()
    assert not preview._manual_zoom


def test_toolbar_actions_have_status_tips(qtbot):
    window = _convert_window(qtbot)
    labeled = [
        a for a in window._toolbar.actions() if a.text() and not a.isSeparator()
    ]
    assert labeled
    for action in labeled:
        assert action.statusTip(), f"missing status tip on {action.text()!r}"
        assert action.toolTip() == action.statusTip()
    assert window._add_action.text() == "Add images…"


def test_request_close_while_converting_explains_busy(qtbot, monkeypatch):
    window = _convert_window(qtbot)
    window._converting = True
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )

    assert window.request_close() is False
    assert "still running" in window.statusBar().currentMessage()
    assert toasts and toasts[-1] == ("Create PDF still running…", "info")


def test_convert_failed_matches_end_job_feedback(qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    window = _convert_window(qtbot)
    window._converting = True
    window._busy_overlay.show_message("Creating PDF…")
    toasts: list[tuple[str, str]] = []
    dialogs: list[object] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *args, **kwargs: dialogs.append(args) or QMessageBox.StandardButton.Ok,
    )

    window._on_convert_failed("convert boom")

    assert not window._converting
    qtbot.waitUntil(lambda: not window._busy_overlay.isVisible(), timeout=1000)
    assert window.statusBar().currentMessage() == "Create PDF failed"
    assert toasts and toasts[-1] == ("Create PDF failed", "error")
    assert dialogs and "convert boom" in str(dialogs[-1])
