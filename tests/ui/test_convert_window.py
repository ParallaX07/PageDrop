"""Phase 19 UI tests — Create PDF window."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog, QLabel, QWidget

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


def test_create_pdf_has_workflow_header(qtbot):
    window = _convert_window(qtbot)
    header = window.findChild(QWidget, "ToolWorkflowHeader")
    assert header is not None
    assert header.findChild(QLabel, "ToolWorkflowTitle").text() == "Create PDF"


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

    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)

    assert folder_called["value"]
    assert not save_called["value"]
    assert (out_dir / "alpha.pdf").is_file()
    assert window._result_bar.isVisible()
    assert window._result_bar._path == str(out_dir / "alpha.pdf")
    assert window._toast.isVisible()
    assert window._toast._message.accessibleName()
    assert "Created 1 PDF file" in window.statusBar().currentMessage()
    assert "Showing first" not in window.statusBar().currentMessage()


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

    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)

    assert (out_dir / "alpha.pdf").is_file()
    assert (out_dir / "bravo.pdf").is_file()
    status = window.statusBar().currentMessage()
    assert window._toast._message.text() == "Completed"
    bar = window._result_bar._label.text()
    assert "Created 2 PDF files" in status
    assert "Showing first" in status
    assert status == bar.splitlines()[0]
    assert window._result_bar._path == str(out_dir / "alpha.pdf")
    assert window.editor is None


def test_separate_mode_shared_stems_get_distinct_outputs(
    qtbot, tmp_path, monkeypatch
):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    images = [src_dir / name for name in ("a.png", "a.jpg", "a_2.png")]
    for image in images:
        _write_test_image(image, 100, 100)
    out_dir = tmp_path / "output"
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(out_dir)
    )

    window = _convert_window(qtbot)
    window.show()
    qtbot.waitExposed(window, timeout=5000)
    window._add_paths([str(p) for p in images])
    window._separate_mode_action.setChecked(True)
    window._create_pdfs()

    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)

    assert sorted(p.name for p in out_dir.iterdir()) == [
        "a.pdf",
        "a_2.pdf",
        "a_2_2.pdf",
    ]
    assert "Created 3 PDF files" in window.statusBar().currentMessage()


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

    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)
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
    window.begin_job("Creating PDF…")
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._toast,
        "show_toast",
        lambda msg, kind="info": toasts.append((msg, kind)),
    )

    assert window.is_job_running()
    assert window.request_close() is False
    assert "still running" in window.statusBar().currentMessage()
    assert toasts and toasts[-1] == ("Create PDF still running…", "info")


def test_convert_failed_shows_shared_job_feedback(qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    window = _convert_window(qtbot)
    window.begin_job("Creating PDF…")
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

    window.end_job(error="convert boom", toast="Job failed", toast_kind="error")

    assert not window.is_job_running()
    qtbot.waitUntil(lambda: not window._busy_overlay.isVisible(), timeout=1000)
    assert window.statusBar().currentMessage() == "Job failed"
    assert toasts and toasts[-1] == ("Job failed", "error")
    assert dialogs and "convert boom" in str(dialogs[-1])


def test_create_pdf_asks_once_before_replacing_existing_output(
    qtbot, tmp_path, monkeypatch, overwrite_answer
):
    from tests.conftest import file_sha256

    png = tmp_path / "solo.png"
    _write_test_image(png, 100, 100)
    source_hash = file_sha256(png)
    output = tmp_path / "solo.pdf"
    output.write_bytes(b"old")
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF Files (*.pdf)"),
    )
    window = _convert_window(qtbot)
    window._add_paths([str(png)])

    overwrite_answer.answer = False
    window._create_pdfs()
    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)
    assert output.read_bytes() == b"old"
    assert len(overwrite_answer.calls) == 1

    overwrite_answer.answer = True
    window._create_pdfs()
    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)
    assert output.read_bytes() != b"old"
    assert len(overwrite_answer.calls) == 2
    assert file_sha256(png) == source_hash


def test_create_pdf_with_unreadable_image_keeps_existing_outputs(
    qtbot, tmp_path, monkeypatch, overwrite_answer
):
    from pagedrop.core import image_to_pdf
    from tests.conftest import file_sha256

    alpha = tmp_path / "alpha.png"
    bravo = tmp_path / "bravo.png"
    _write_test_image(alpha, 100, 100)
    _write_test_image(bravo, 120, 120)
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    (out_dir / "alpha.pdf").write_bytes(b"old")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(out_dir)
    )
    window = _convert_window(qtbot)
    window._add_paths([str(alpha), str(bravo)])
    window._separate_mode_action.setChecked(True)
    hashes = [file_sha256(alpha), file_sha256(bravo)]

    # Pass the up-front check, then fail while writing the second file.
    real_write = image_to_pdf.image_to_pdf_file

    def fail_second(path, out_path):
        if Path(path) == bravo.resolve():
            raise image_to_pdf.ImageConvertError("bravo is unreadable")
        real_write(path, out_path)

    monkeypatch.setattr("pagedrop.core.organize_jobs.image_to_pdf_file", fail_second)
    window._create_pdfs()
    qtbot.waitUntil(lambda: not window.is_job_running(), timeout=10000)

    assert overwrite_answer.calls == [[out_dir / "alpha.pdf"]]
    assert (out_dir / "alpha.pdf").read_bytes() == b"old"
    assert not (out_dir / "bravo.pdf").exists()
    assert window.statusBar().currentMessage() == "Job failed"
    assert not window._result_bar.isVisible()
    assert [file_sha256(alpha), file_sha256(bravo)] == hashes
