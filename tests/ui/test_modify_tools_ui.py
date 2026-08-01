"""Phase 28 UI — modify tool shells, blank confirm, raster warning."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from pagedrop.core.modify_ops import RASTER_EFFECT_WARNING
from pagedrop.ui.modify_tools_shell import SHELL_MODIFY_IDS, open_modify_shell
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


def _write_pdf(path: Path, *, text: str = "hello", pages: int = 1) -> None:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page(width=200, height=200)
            if text:
                page.insert_text((40, 80), text if pages == 1 else f"{text}{i}", fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()


def test_modify_tiles_open_shells(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    by_id = {t.entry.id: t.entry for t in tools._tiles}
    for tool_id in SHELL_MODIFY_IDS:
        assert tool_id in by_id
        assert by_id[tool_id].action == "modify"
        assert not by_id[tool_id].coming_soon
        shell = open_modify_shell(tools, tool_id)
        assert shell is not None
        assert isinstance(shell, ToolShellWindow)
        assert shell.isVisible()
        qtbot.addWidget(shell)
        shell.close()
    tools.close()


def test_watermark_shell_has_diagonal_and_position_controls(qtbot, isolated_settings):
    from PyQt6.QtWidgets import (
        QCheckBox,
        QDoubleSpinBox,
        QFrame,
        QLabel,
        QPushButton,
        QToolBar,
        QToolButton,
        QWidget,
    )

    from pagedrop.ui.watermark_preview import WatermarkPreviewCanvas

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    host = shell._options_host

    assert host.findChild(WatermarkPreviewCanvas, "WatermarkPreviewCanvas") is not None
    assert host.findChild(QFrame, "WatermarkPreviewCard") is not None
    options_card = host.findChild(QFrame, "WatermarkOptionsCard")
    assert options_card is not None
    # R11: Run docks in options column footer (outside scroll card); shell strip hidden.
    assert host.isAncestorOf(shell._run_btn)
    assert not options_card.isAncestorOf(shell._run_btn)
    assert not shell._actions_host.isVisible()
    assert shell.findChild(QToolBar, "ToolShellToolbar") is None
    # R12: drag hint is a canvas tooltip, not a header QLabel.
    canvas = host.findChild(WatermarkPreviewCanvas, "WatermarkPreviewCanvas")
    assert canvas is not None
    assert "Drag watermark" in canvas.toolTip()
    assert not any(
        isinstance(lab, QLabel) and "Drag watermark" in lab.text()
        for lab in host.findChildren(QLabel)
    )
    options_col = host.findChild(QWidget, "WatermarkOptionsColumn")
    assert options_col is not None
    assert options_col.minimumWidth() == 400
    assert options_col.maximumWidth() == 460
    # R18: tool title + ? dock in the options column (not shell root).
    assert options_col.isAncestorOf(shell._header_host)
    assert shell._title_label.text() == "Watermark"
    assert shell._help_btn.isVisible()
    assert shell.layout().indexOf(shell._header_host) < 0
    assert shell.findChild(QLabel, "ToolShellDescription") is None
    spins = host.findChildren(QDoubleSpinBox)
    assert any(s.suffix().strip() == "%" for s in spins)
    assert any(s.suffix() == "°" for s in spins)
    pos_buttons = [
        b
        for b in host.findChildren(QToolButton)
        if b.isCheckable() and b.text() in {"TL", "T", "TR", "L", "C", "R", "BL", "B", "BR"}
    ]
    assert len(pos_buttons) == 9
    assert any(b.isChecked() and b.text() == "C" for b in pos_buttons)
    assert any(
        isinstance(c, QCheckBox) and "Flatten" in c.text()
        for c in host.findChildren(QCheckBox)
    )
    kind_btns = [
        b for b in host.findChildren(QToolButton) if b.text() in {"Text", "Image"}
    ]
    assert {b.text() for b in kind_btns} == {"Text", "Image"}
    assert any(b.isChecked() and b.text() == "Text" for b in kind_btns)
    zoom_btns = [
        b
        for b in host.findChildren(QPushButton)
        if b.objectName() == "WatermarkZoomButton"
    ]
    assert len(zoom_btns) == 2
    shell.resize(900, 640)
    shell.show()
    qtbot.wait(20)
    # R12: options stay in the locked band; preview gets the horizontal remainder.
    assert 400 <= options_col.width() <= 460
    preview = host.findChild(QFrame, "WatermarkPreviewCard")
    assert preview is not None
    assert preview.width() > options_col.width()
    # Idle status placeholder must not reserve a full-width strip.
    assert not shell.statusBar().isVisible()
    assert shell.statusBar().currentMessage() == ""
    tools.close()


def test_r12_crop_margins_use_2x2_grid(qtbot, isolated_settings):
    from PyQt6.QtWidgets import QDoubleSpinBox, QGridLayout, QWidget

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "crop")
    assert shell is not None
    qtbot.addWidget(shell)
    host = shell._options_host
    margins = host.findChild(QWidget, "CropMarginsGrid")
    assert margins is not None
    grid = margins.layout()
    assert isinstance(grid, QGridLayout)
    assert grid.rowCount() == 2
    assert grid.columnCount() == 2
    # Four margin spins live in the grid (not four stacked QFormLayout rows).
    spins = margins.findChildren(QDoubleSpinBox)
    assert len(spins) == 4
    assert all(s.suffix().strip() == "pt" for s in spins)
    tools.close()


def test_watermark_preview_after_pick_shows_change_file(qtbot, tmp_path, isolated_settings):
    from PyQt6.QtWidgets import QLabel, QPushButton

    from pagedrop.ui.watermark_preview import WatermarkPreviewCanvas

    pdf = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=280)
        doc.new_page(width=200, height=280)
        doc.save(str(pdf))
    finally:
        doc.close()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.resize(960, 700)
    shell.show()

    assert shell.drop_zone.isVisible()
    shell.drop_zone.set_paths([str(pdf)])

    qtbot.waitUntil(lambda: not shell.drop_zone.isVisible(), timeout=3000)
    chrome = shell._chrome_host
    assert chrome.isVisible()
    # R18: title/desc live in the options column — no root spacing rhythm for that stack.
    change = chrome.findChild(QPushButton)
    assert change is not None and change.text() == "Change file"
    assert any("src.pdf" in lab.text() for lab in chrome.findChildren(QLabel))

    canvas = shell._options_host.findChild(WatermarkPreviewCanvas)
    assert canvas is not None
    qtbot.waitUntil(lambda: not canvas._page_pix.isNull(), timeout=5000)
    assert canvas.page_count == 2

    # Sidebar text change updates overlay state.
    from PyQt6.QtWidgets import QLineEdit, QToolButton

    text_edit = next(
        e for e in shell._options_host.findChildren(QLineEdit) if e.text() == "CONFIDENTIAL"
    )
    text_edit.setText("DRAFT")
    assert canvas.state.text == "DRAFT"

    # Kind toggle to Image shows image path row still wired.
    image_kind = next(
        b for b in shell._options_host.findChildren(QToolButton) if b.text() == "Image"
    )
    image_kind.click()
    assert canvas.state.kind == "image"

    tools.close()


def test_watermark_preview_zoom_controls(qtbot, tmp_path, isolated_settings):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QPushButton

    from pagedrop.ui.watermark_preview import WatermarkPreviewCanvas

    pdf = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=280)
        doc.save(str(pdf))
    finally:
        doc.close()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.resize(960, 700)
    shell.show()
    shell.drop_zone.set_paths([str(pdf)])

    canvas = shell._options_host.findChild(WatermarkPreviewCanvas)
    assert canvas is not None
    qtbot.waitUntil(lambda: not canvas._page_pix.isNull(), timeout=5000)
    assert canvas.zoom_factor == 1.0

    zoom_in = next(
        b
        for b in shell._options_host.findChildren(QPushButton)
        if b.objectName() == "WatermarkZoomButton" and b.text() == "+"
    )
    zoom_in.click()
    assert abs(canvas.zoom_factor - 1.1) < 1e-6

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
    canvas.wheelEvent(event)
    assert abs(canvas.zoom_factor - 1.2) < 1e-6

    canvas.reset_zoom()
    assert canvas.zoom_factor == 1.0
    tools.close()


def test_watermark_overlay_move_and_angle_sync_sidebar(qtbot, tmp_path, isolated_settings):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QDoubleSpinBox

    from pagedrop.ui.watermark_preview import WatermarkPreviewCanvas

    pdf = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=400, height=400)
        doc.save(str(pdf))
    finally:
        doc.close()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.resize(960, 700)
    shell.show()
    shell.drop_zone.set_paths([str(pdf)])

    canvas = shell._options_host.findChild(WatermarkPreviewCanvas)
    assert canvas is not None
    qtbot.waitUntil(lambda: not canvas._page_pix.isNull(), timeout=5000)

    angle_spin = next(
        s for s in shell._options_host.findChildren(QDoubleSpinBox) if s.suffix() == "°"
    )
    assert angle_spin.value() == -45

    # Programmatic overlay angle → sidebar.
    canvas.angle_changed.emit(30.0)
    assert angle_spin.value() == 30

    # Drag move from page center toward top-left.
    wr = canvas._box_widget_rect()
    start = wr.center().toPoint()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(canvas, pos=start + QPoint(-40, -40))
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(-40, -40))
    assert canvas.state.center_x < 0.5
    assert canvas.state.center_y < 0.5

    tools.close()


def test_watermark_image_overlay_size_reuses_cache(qtbot, tmp_path):
    """O17-b: image _box_pts uses canvas _image_cache; no per-call disk decode."""
    from PyQt6.QtGui import QImage, QPixmap

    from pagedrop.ui.watermark_preview import (
        WatermarkOverlayState,
        WatermarkPreviewCanvas,
        _overlay_size_pts,
    )

    img = QImage(80, 40, QImage.Format.Format_RGB32)
    img.fill(0)
    path = tmp_path / "mark.png"
    assert img.save(str(path))

    # Passed pixmap wins over a broken path (size path must not re-decode).
    state = WatermarkOverlayState(
        kind="image",
        image_path="/no/such/watermark.png",
        size_mode="diagonal",
        diagonal_percent=50.0,
    )
    cached = QPixmap(str(path))
    w, h = _overlay_size_pts(state, 400.0, 400.0, image_pix=cached)
    diag = (400.0**2 + 400.0**2) ** 0.5
    assert abs(w - diag * 0.5) < 0.5
    assert abs(h / w - 0.5) < 0.01

    canvas = WatermarkPreviewCanvas()
    qtbot.addWidget(canvas)
    canvas._page_w = 400.0
    canvas._page_h = 400.0
    canvas.set_state(
        WatermarkOverlayState(
            kind="image",
            image_path=str(path),
            size_mode="diagonal",
            diagonal_percent=40.0,
        )
    )
    canvas._box_pts()  # warm cache
    assert not canvas._image_cache.isNull()
    assert canvas._image_cache_path == str(path)
    warm = canvas._image_cache
    for _ in range(20):
        canvas._box_pts()
    assert canvas._image_cache is warm  # same QPixmap object — no reload


def test_watermark_run_result_bar_no_auto_open(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    """Modeless shell: Run → BusyOverlay → toast + ResultActionsBar; no editor auto-open."""
    from pagedrop.ui.busy_overlay import BusyOverlay
    from pagedrop.ui.job_chrome import JobChromeMixin
    from pagedrop.ui.result_actions import ResultActionsBar

    src = tmp_path / "src.pdf"
    out = tmp_path / "src_watermarked.pdf"
    _write_pdf(src, text="body")

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    assert isinstance(shell, ToolShellWindow)
    assert isinstance(shell, JobChromeMixin)
    assert isinstance(shell._busy_overlay, BusyOverlay)
    assert isinstance(shell._result_bar, ResultActionsBar)
    assert shell._busy_overlay._cancel_btn.text() == "Cancel"

    shell.drop_zone.set_paths([str(src)])
    monkeypatch.setattr(
        "pagedrop.ui.modify_tools_shell._pick_save_path",
        lambda parent, title, suggested: str(out),
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.open_in_editor",
        lambda path, editor: opened.append(str(path)),
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    assert out.is_file()
    assert shell._result_bar.isVisible()
    assert shell._result_bar._path == str(out)
    assert shell._result_bar._preview_btn.text() == "Preview"
    assert shell._result_bar._open_btn.text() == "Open in editor"
    assert shell._result_bar._folder_btn.text() == "Show in folder"
    assert opened == []  # success path must not auto-open

    doc = fitz.open(str(out))
    try:
        assert "CONFIDENTIAL" in doc[0].get_text()
        assert "body" in doc[0].get_text()
    finally:
        doc.close()

    shell.close()
    tools.close()


def test_watermark_cancel_mid_run_clears_busy_chrome(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    """O13: Cancel mid watermark → no promote, BusyOverlay clears, idle status."""
    import time

    from pagedrop.core import modify_ops as ops

    src = tmp_path / "src.pdf"
    out = tmp_path / "src_watermarked.pdf"
    _write_pdf(src, text="body", pages=12)
    source_hash = hashlib.sha256(src.read_bytes()).hexdigest()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_modify_shell(tools, "watermark")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])
    monkeypatch.setattr(
        "pagedrop.ui.modify_tools_shell._pick_save_path",
        lambda parent, title, suggested: str(out),
    )

    real_check = ops._check_cancel
    checks = {"n": 0}

    def wait_for_ui_cancel(cancel):
        checks["n"] += 1
        if checks["n"] == 1:
            deadline = time.time() + 5.0
            while not cancel.is_cancelled() and time.time() < deadline:
                time.sleep(0.01)
        real_check(cancel)

    monkeypatch.setattr(ops, "_check_cancel", wait_for_ui_cancel)

    shell._run_btn.click()
    qtbot.waitUntil(
        lambda: (
            shell.is_job_running()
            and checks["n"] >= 1
            and shell._busy_overlay._cancel_btn.isVisible()
        ),
        timeout=5000,
    )
    assert shell._busy_overlay.isVisible()
    shell._busy_overlay._cancel_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=15000)

    assert not out.exists()
    qtbot.waitUntil(lambda: not shell._busy_overlay.isVisible(), timeout=1000)
    assert not shell._result_bar.isVisible()
    assert shell.statusBar().currentMessage() == "Cancelled"
    assert hashlib.sha256(src.read_bytes()).hexdigest() == source_hash

    shell.close()
    tools.close()


def test_blank_remove_requires_confirm(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "keep", fontsize=14)
        doc.save(str(pdf))
    finally:
        doc.close()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "blank_pages")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])

    # Force the confirm path (bypass PAGEDROP_TESTING short-circuit).
    confirmed: list[tuple[int, int]] = []

    def fake_confirm(parent, *, blank_count, page_count, heuristic_hint):
        confirmed.append((blank_count, page_count))
        assert "heuristic" in heuristic_hint.casefold() or "coverage" in heuristic_hint.casefold() or "text" in heuristic_hint.casefold()
        return False

    monkeypatch.setattr(
        "pagedrop.ui.modify_tools_shell.confirm_remove_blank_pages",
        fake_confirm,
    )
    save_called = {"n": 0}

    def fake_save(*_a, **_k):
        save_called["n"] += 1
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)

    shell._run_btn.click()
    # O17-e: detect is async — wait for confirm after BusyOverlay clears.
    qtbot.waitUntil(lambda: confirmed == [(1, 2)], timeout=10000)
    assert not shell.is_job_running()
    qtbot.waitUntil(lambda: not shell._busy_overlay.isVisible(), timeout=2000)
    assert save_called["n"] == 0
    assert "1 blank of 2" in shell._blank_preview.text()  # type: ignore[attr-defined]
    tools.close()


def test_blank_detect_none_found(qtbot, tmp_path, monkeypatch, isolated_settings):
    """O17-e: detect busy chrome then 'none found' when every page has content."""
    import time

    from pagedrop.core import modify_ops as ops

    pdf = tmp_path / "full.pdf"
    _write_pdf(pdf, text="keep", pages=2)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "blank_pages")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])

    infos: list[str] = []

    def fake_info(parent, title, text):
        infos.append(text)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_info)

    real_check = ops._check_cancel
    checks = {"n": 0}

    def slow_first_page(cancel):
        checks["n"] += 1
        if checks["n"] == 1:
            time.sleep(0.15)
        real_check(cancel)

    monkeypatch.setattr(ops, "_check_cancel", slow_first_page)

    shell._run_btn.click()
    qtbot.waitUntil(
        lambda: shell.is_job_running() and shell._busy_overlay.isVisible(),
        timeout=5000,
    )
    qtbot.waitUntil(lambda: infos == ["No blank pages detected."], timeout=10000)
    assert not shell.is_job_running()
    qtbot.waitUntil(lambda: not shell._busy_overlay.isVisible(), timeout=2000)
    tools.close()


def test_blank_detect_cancel_clears_busy_chrome(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    """O17-e: Cancel mid-detect → BusyOverlay clears; source untouched; no confirm."""
    import time

    from pagedrop.core import modify_ops as ops

    pdf = tmp_path / "many.pdf"
    _write_pdf(pdf, text="keep", pages=12)
    source_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "blank_pages")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])

    confirmed: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "pagedrop.ui.modify_tools_shell.confirm_remove_blank_pages",
        lambda *a, **k: confirmed.append((1, 1)) or False,
    )

    real_check = ops._check_cancel
    checks = {"n": 0}

    def wait_for_ui_cancel(cancel):
        checks["n"] += 1
        if checks["n"] == 1:
            deadline = time.time() + 5.0
            while not cancel.is_cancelled() and time.time() < deadline:
                time.sleep(0.01)
        real_check(cancel)

    monkeypatch.setattr(ops, "_check_cancel", wait_for_ui_cancel)

    shell._run_btn.click()
    qtbot.waitUntil(
        lambda: (
            shell.is_job_running()
            and checks["n"] >= 1
            and shell._busy_overlay._cancel_btn.isVisible()
        ),
        timeout=5000,
    )
    assert shell._busy_overlay.isVisible()
    shell._busy_overlay._cancel_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=15000)

    assert confirmed == []
    qtbot.waitUntil(lambda: not shell._busy_overlay.isVisible(), timeout=1000)
    assert shell.statusBar().currentMessage() == "Cancelled"
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == source_hash
    tools.close()


def test_raster_effect_warning_copy(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "color_effects")
    assert shell is not None
    qtbot.addWidget(shell)

    effect = shell._color_effect  # type: ignore[attr-defined]
    warning = shell._color_warning  # type: ignore[attr-defined]
    # Select invert (index 1).
    effect.setCurrentIndex(1)
    assert effect.currentData() == "invert"
    assert RASTER_EFFECT_WARNING in warning.text()
    assert "raster" in warning.text().casefold()
    tools.close()


def test_invert_run_shows_raster_warning_dialog(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    pdf = tmp_path / "src.pdf"
    _write_pdf(pdf)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_modify_shell(tools, "color_effects")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])
    shell._color_effect.setCurrentIndex(1)  # type: ignore[attr-defined]

    warned: list[str] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warned.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    save_called = {"n": 0}

    def fake_save(*_a, **_k):
        save_called["n"] += 1
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)

    shell._run_btn.click()
    assert any(RASTER_EFFECT_WARNING in t for t in warned)
    assert save_called["n"] == 0
    tools.close()
