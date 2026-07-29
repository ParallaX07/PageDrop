"""Document modification — Phase 22b modeless shells (Phase 28 UI)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.modify_ops import (
    BLANK_PAGE_HEURISTIC_HINT,
    RASTER_EFFECT_WARNING,
    detect_blank_pages,
    get_bookmarks,
)
from pagedrop.core.pdf_loader import (
    PdfLoader,
    PdfPasswordError,
    PdfPasswordRequiredError,
)
from pagedrop.core.supported_formats import is_pdf_path
from pagedrop.ui.dialogs import confirm_remove_blank_pages, prompt_pdf_password
from pagedrop.ui.organize_tools import editor_pdf_context
from pagedrop.ui.settings import last_directory, remember_directory
from pagedrop.ui.tool_page import present_tool_page, tool_shell_store
from pagedrop.ui.tool_shell import ToolShellWindow, run_tool_job
from pagedrop.utils.page_jump import parse_page_ranges
if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

SHELL_MODIFY_IDS: frozenset[str] = frozenset(
    {
        "crop",
        "watermark",
        "header_footer",
        "page_numbers",
        "bates",
        "bookmarks",
        "annotations",
        "blank_pages",
        "color_effects",
    }
)

_PDF_FILTER = "PDF files (*.pdf);;All files (*)"
_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"

_POSITIONS: tuple[tuple[str, str], ...] = (
    ("Bottom center", "bottom-center"),
    ("Bottom left", "bottom-left"),
    ("Bottom right", "bottom-right"),
    ("Top center", "top-center"),
    ("Top left", "top-left"),
    ("Top right", "top-right"),
    ("Center", "center"),
    ("Center left", "center-left"),
    ("Center right", "center-right"),
)

_WATERMARK_POSITION_GRID: tuple[tuple[str, str], ...] = (
    ("Top left", "top-left"),
    ("Top", "top-center"),
    ("Top right", "top-right"),
    ("Left", "center-left"),
    ("Center", "center"),
    ("Right", "center-right"),
    ("Bottom left", "bottom-left"),
    ("Bottom", "bottom-center"),
    ("Bottom right", "bottom-right"),
)

_OUTPUT_SUFFIX: dict[str, str] = {
    "crop": "_cropped",
    "watermark": "_watermarked",
    "header_footer": "_header_footer",
    "page_numbers": "_numbered",
    "bates": "_bates",
    "bookmarks": "_bookmarks",
    "annotations": "_annotations",
    "blank_pages": "_no_blanks",
    "color_effects": "_color",
}


def _pick_save_path(parent: QWidget, title: str, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, suggested, _PDF_FILTER)
    if not path:
        return None
    remember_directory(path)
    if not path.lower().endswith(".pdf"):
        path = f"{path}.pdf"
    return path


def _suggested_output(source: str, tool_id: str) -> str:
    path = Path(source)
    return str(path.with_name(f"{path.stem}{_OUTPUT_SUFFIX[tool_id]}{path.suffix}"))


def _margin_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 2000.0)
    spin.setDecimals(1)
    spin.setSuffix(" pt")
    spin.setValue(36.0)
    return spin


def _configure_crop(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    left, right, top, bottom = (_margin_spin() for _ in range(4))
    mode = QComboBox()
    mode.addItem("CropBox (soft crop)", "cropbox")
    mode.addItem("Rebuild (hard clip)", "rebuild")
    form.addRow("Left", left)
    form.addRow("Right", right)
    form.addRow("Top", top)
    form.addRow("Bottom", bottom)
    form.addRow("Mode", mode)
    hint = QLabel(
        "Margins in points. CropBox keeps page size metadata; "
        "rebuild writes pages sized to the clipped region."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save cropped PDF", _suggested_output(source, "crop")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="crop",
            inputs=[source],
            output=output,
            options={
                "left": left.value(),
                "right": right.value(),
                "top": top.value(),
                "bottom": bottom.value(),
                "mode": mode.currentData(),
            },
            progress_message="Cropping PDF…",
        )

    shell.set_run_handler(on_run)


def _set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    field.setVisible(visible)
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)


def _configure_watermark(shell: ToolShellWindow) -> None:
    from pagedrop.core.modify_ops import position_center_fractions
    from pagedrop.ui.watermark_preview import (
        WatermarkOverlayState,
        WatermarkPreviewCanvas,
        WatermarkPreviewScroll,
    )

    # —— Chrome: Change File + meta (shown after pick) ——
    chrome = QWidget()
    chrome_row = QHBoxLayout(chrome)
    chrome_row.setContentsMargins(0, 0, 0, 0)
    chrome_row.setSpacing(8)
    change_btn = QPushButton("Change File")
    change_btn.setObjectName("ToolbarSecondary")
    change_btn.clicked.connect(shell.drop_zone.open_picker)
    file_meta = QLabel()
    file_meta.setObjectName("ToolsHint")
    file_meta.setWordWrap(True)
    chrome_row.addWidget(change_btn)
    chrome_row.addWidget(file_meta, stretch=1)
    shell.set_chrome_widget(chrome)
    shell._chrome_host.hide()  # type: ignore[attr-defined]

    # —— Split body: preview card | options card ——
    body = QWidget()
    body.setObjectName("WatermarkToolBody")
    body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    body_row = QHBoxLayout(body)
    body_row.setContentsMargins(0, 0, 0, 0)
    body_row.setSpacing(12)

    preview_card = QFrame()
    preview_card.setObjectName("WatermarkPreviewCard")
    preview_lay = QVBoxLayout(preview_card)
    preview_lay.setContentsMargins(12, 12, 12, 12)
    preview_lay.setSpacing(8)

    header = QHBoxLayout()
    header.setSpacing(8)
    preview_title = QLabel("Preview")
    preview_title.setObjectName("WatermarkPreviewTitle")
    prev_btn = QPushButton("‹")
    prev_btn.setObjectName("ToolbarSecondary")
    prev_btn.setFixedWidth(32)
    prev_btn.setAccessibleName("Previous page")
    next_btn = QPushButton("›")
    next_btn.setObjectName("ToolbarSecondary")
    next_btn.setFixedWidth(32)
    next_btn.setAccessibleName("Next page")
    page_label = QLabel("—")
    page_label.setObjectName("ToolsHint")
    page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    page_label.setMinimumWidth(48)

    zoom_out = QPushButton("−")
    zoom_out.setObjectName("WatermarkZoomButton")
    zoom_out.setToolTip("Zoom out (Ctrl+scroll)")
    zoom_out.setAccessibleName("Zoom out")
    zoom_label = QLabel("100%")
    zoom_label.setObjectName("WatermarkZoomLabel")
    zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    zoom_label.setToolTip("Ctrl+0 resets to fit")
    zoom_in = QPushButton("+")
    zoom_in.setObjectName("WatermarkZoomButton")
    zoom_in.setToolTip("Zoom in (Ctrl+scroll)")
    zoom_in.setAccessibleName("Zoom in")

    drag_hint = QLabel("Drag watermark to position")
    drag_hint.setObjectName("ToolsHint")

    header.addWidget(preview_title)
    header.addStretch(1)
    header.addWidget(prev_btn)
    header.addWidget(page_label)
    header.addWidget(next_btn)
    header.addSpacing(12)
    header.addWidget(zoom_out)
    header.addWidget(zoom_label)
    header.addWidget(zoom_in)
    header.addSpacing(8)
    header.addWidget(drag_hint)
    preview_lay.addLayout(header)

    canvas = WatermarkPreviewCanvas()
    preview_scroll = WatermarkPreviewScroll(canvas)
    preview_lay.addWidget(preview_scroll, stretch=1)
    body_row.addWidget(preview_card, stretch=3)

    options_card = QFrame()
    options_card.setObjectName("WatermarkOptionsCard")
    options_card.setMinimumWidth(280)
    form = QFormLayout(options_card)
    form.setContentsMargins(14, 14, 14, 14)
    form.setVerticalSpacing(10)
    form.setHorizontalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

    kind_host = QWidget()
    kind_host.setObjectName("WatermarkKindToggle")
    kind_row = QHBoxLayout(kind_host)
    kind_row.setContentsMargins(0, 0, 0, 0)
    kind_row.setSpacing(0)
    kind_group = QButtonGroup(kind_host)
    kind_group.setExclusive(True)
    kind_value = {"v": "text"}
    text_kind = QToolButton()
    text_kind.setText("Text")
    text_kind.setCheckable(True)
    text_kind.setChecked(True)
    image_kind = QToolButton()
    image_kind.setText("Image")
    image_kind.setCheckable(True)
    kind_group.addButton(text_kind)
    kind_group.addButton(image_kind)
    kind_row.addWidget(text_kind)
    kind_row.addWidget(image_kind)
    kind_row.addStretch(1)

    page_range = QLineEdit("all")
    page_range.setPlaceholderText("all or e.g. 1-3,5,7-9")
    page_hint = QLabel('Use "all" or specify pages, e.g. 1-3, 5, 7-9')
    page_hint.setObjectName("ToolsHint")
    page_hint.setWordWrap(True)

    text = QLineEdit("CONFIDENTIAL")
    fontsize = QDoubleSpinBox()
    fontsize.setRange(4.0, 400.0)
    fontsize.setValue(72.0)
    fontsize.setDecimals(1)

    color_btn = QPushButton()
    color_btn.setObjectName("ToolbarSecondary")
    color_btn.setFixedWidth(88)
    color_rgb = [0.55, 0.55, 0.55]

    def _set_color_btn(rgb: list[float]) -> None:
        r, g, b = (int(c * 255) for c in rgb)
        color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid palette(mid);"
        )
        color_btn.setText(f"#{r:02X}{g:02X}{b:02X}")

    def pick_color() -> None:
        initial = QColor(
            int(color_rgb[0] * 255),
            int(color_rgb[1] * 255),
            int(color_rgb[2] * 255),
        )
        chosen = QColorDialog.getColor(initial, shell, "Watermark color")
        if chosen.isValid():
            color_rgb[0] = chosen.redF()
            color_rgb[1] = chosen.greenF()
            color_rgb[2] = chosen.blueF()
            _set_color_btn(color_rgb)
            _push_overlay_from_sidebar()

    color_btn.clicked.connect(pick_color)
    _set_color_btn(color_rgb)

    image_host = QWidget()
    image_row = QHBoxLayout(image_host)
    image_row.setContentsMargins(0, 0, 0, 0)
    image = QLineEdit()
    image_row.addWidget(image, stretch=1)
    browse = QPushButton("Browse…")
    browse.setObjectName("ToolbarSecondary")

    def pick_image() -> None:
        path, _ = QFileDialog.getOpenFileName(
            shell, "Choose watermark image", last_directory(), _IMAGE_FILTER
        )
        if path:
            remember_directory(path)
            image.setText(path)
            _push_overlay_from_sidebar()

    browse.clicked.connect(pick_image)
    image_row.addWidget(browse)

    size_mode = QComboBox()
    size_mode.addItem("% of page diagonal", "diagonal")
    size_mode.addItem("Font size (text) / scale (image)", "absolute")

    diagonal_pct = QDoubleSpinBox()
    diagonal_pct.setRange(1.0, 100.0)
    diagonal_pct.setDecimals(1)
    diagonal_pct.setSuffix(" %")
    diagonal_pct.setValue(50.0)

    image_scale = QDoubleSpinBox()
    image_scale.setRange(0.05, 1.0)
    image_scale.setSingleStep(0.05)
    image_scale.setValue(0.5)

    # Hidden spins keep range/tests; sliders are the Bento-facing controls.
    opacity = QDoubleSpinBox()
    opacity.setRange(0.05, 1.0)
    opacity.setSingleStep(0.05)
    opacity.setValue(0.3)
    opacity.hide()

    angle = QDoubleSpinBox()
    angle.setRange(-180.0, 180.0)
    angle.setDecimals(0)
    angle.setSuffix("°")
    angle.setValue(-45.0)
    angle.hide()

    opacity_host = QWidget()
    opacity_row = QHBoxLayout(opacity_host)
    opacity_row.setContentsMargins(0, 0, 0, 0)
    opacity_row.setSpacing(8)
    opacity_slider = QSlider(Qt.Orientation.Horizontal)
    opacity_slider.setObjectName("WatermarkSlider")
    opacity_slider.setRange(5, 100)
    opacity_slider.setValue(30)
    opacity_slider.setAccessibleName("Opacity")
    opacity_value = QLabel("0.3")
    opacity_value.setObjectName("ToolsHint")
    opacity_value.setMinimumWidth(28)
    opacity_row.addWidget(opacity_slider, stretch=1)
    opacity_row.addWidget(opacity_value)

    angle_host = QWidget()
    angle_row = QHBoxLayout(angle_host)
    angle_row.setContentsMargins(0, 0, 0, 0)
    angle_row.setSpacing(8)
    angle_slider = QSlider(Qt.Orientation.Horizontal)
    angle_slider.setObjectName("WatermarkSlider")
    angle_slider.setRange(-180, 180)
    angle_slider.setValue(-45)
    angle_slider.setAccessibleName("Angle")
    angle_value = QLabel("-45°")
    angle_value.setObjectName("ToolsHint")
    angle_value.setMinimumWidth(40)
    angle_row.addWidget(angle_slider, stretch=1)
    angle_row.addWidget(angle_value)

    pos_host = QWidget()
    pos_grid = QGridLayout(pos_host)
    pos_grid.setContentsMargins(0, 0, 0, 0)
    pos_grid.setSpacing(4)
    pos_group = QButtonGroup(pos_host)
    pos_group.setExclusive(True)
    position_value = {"v": "center"}
    short_labels = {
        "top-left": "TL",
        "top-center": "T",
        "top-right": "TR",
        "center-left": "L",
        "center": "C",
        "center-right": "R",
        "bottom-left": "BL",
        "bottom-center": "B",
        "bottom-right": "BR",
    }
    for idx, (label, data) in enumerate(_WATERMARK_POSITION_GRID):
        btn = QToolButton()
        btn.setText(short_labels[data])
        btn.setCheckable(True)
        btn.setToolTip(label)
        btn.setMinimumSize(36, 28)
        if data == "center":
            btn.setChecked(True)
        pos_group.addButton(btn)
        pos_grid.addWidget(btn, idx // 3, idx % 3)

        def _on_pos(checked: bool, value: str = data) -> None:
            if not checked:
                return
            position_value["v"] = value
            _apply_snap(value)

        btn.toggled.connect(_on_pos)

    flatten = QCheckBox("Flatten watermark")
    flatten_hint = QLabel(
        "Bakes the watermark into page pixels, making it tamper-resistant. "
        "Text will no longer be selectable."
    )
    flatten_hint.setObjectName("ToolsHint")
    flatten_hint.setWordWrap(True)

    form.addRow(kind_host)
    form.addRow("Page range", page_range)
    form.addRow(page_hint)
    form.addRow("Text", text)
    form.addRow("Font size", fontsize)
    form.addRow("Color", color_btn)
    form.addRow("Image", image_host)
    form.addRow("Size mode", size_mode)
    form.addRow("Size (% of diagonal)", diagonal_pct)
    form.addRow("Image scale", image_scale)
    form.addRow("Opacity", opacity_host)
    form.addRow("Angle", angle_host)
    form.addRow("Snap", pos_host)
    # Hidden spins keep range + test findability; sliders drive the UI.
    opacity.setParent(options_card)
    angle.setParent(options_card)
    opacity.hide()
    angle.hide()
    form.addRow("", flatten)
    form.addRow(flatten_hint)

    options_scroll = QScrollArea()
    options_scroll.setObjectName("WatermarkOptionsScroll")
    options_scroll.setWidgetResizable(True)
    options_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    options_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    options_scroll.setWidget(options_card)
    body_row.addWidget(options_scroll, stretch=2)

    while shell._options_layout.count():
        item = shell._options_layout.takeAt(0)
        child = item.widget()
        if child is not None:
            child.deleteLater()
    shell._options_layout.addWidget(body, stretch=1)

    _syncing = {"v": False}
    _page_count = {"n": 0}

    def _apply_snap(value: str) -> None:
        if canvas.page_count <= 0 or canvas._page_pix.isNull():  # noqa: SLF001
            return
        pw, ph = canvas.page_size
        cx, cy = position_center_fractions(pw, ph, value)  # type: ignore[arg-type]
        _syncing["v"] = True
        try:
            canvas.update_state(center_x=cx, center_y=cy)
        finally:
            _syncing["v"] = False

    def sync_kind_visibility() -> None:
        is_text = kind_value["v"] == "text"
        absolute = size_mode.currentData() == "absolute"
        _set_form_row_visible(form, text, is_text)
        _set_form_row_visible(form, color_btn, is_text)
        _set_form_row_visible(form, image_host, not is_text)
        _set_form_row_visible(form, diagonal_pct, not absolute)
        _set_form_row_visible(form, fontsize, is_text and absolute)
        _set_form_row_visible(form, image_scale, (not is_text) and absolute)

    def _sidebar_state() -> WatermarkOverlayState:
        return WatermarkOverlayState(
            kind=kind_value["v"],
            text=text.text(),
            image_path=image.text().strip(),
            color=(color_rgb[0], color_rgb[1], color_rgb[2]),
            opacity=opacity.value(),
            angle=angle.value(),
            center_x=canvas.state.center_x,
            center_y=canvas.state.center_y,
            size_mode=str(size_mode.currentData()),
            diagonal_percent=diagonal_pct.value(),
            fontsize=fontsize.value(),
            image_scale=image_scale.value(),
        )

    def _push_overlay_from_sidebar() -> None:
        if _syncing["v"]:
            return
        _syncing["v"] = True
        try:
            canvas.set_state(_sidebar_state())
        finally:
            _syncing["v"] = False

    def _pull_size_from_canvas() -> None:
        if _syncing["v"]:
            return
        st = canvas.state
        _syncing["v"] = True
        try:
            diagonal_pct.setValue(st.diagonal_percent)
            fontsize.setValue(st.fontsize)
            image_scale.setValue(st.image_scale)
        finally:
            _syncing["v"] = False

    def _pull_angle_from_canvas(value: float) -> None:
        if _syncing["v"]:
            return
        _syncing["v"] = True
        try:
            rounded = round(value)
            angle.setValue(rounded)
            angle_slider.setValue(int(rounded))
            angle_value.setText(f"{int(rounded)}°")
        finally:
            _syncing["v"] = False

    def _on_opacity_slider(v: int) -> None:
        if _syncing["v"]:
            return
        op = max(0.05, min(1.0, v / 100.0))
        _syncing["v"] = True
        try:
            opacity.setValue(op)
            opacity_value.setText(f"{op:.2g}")
        finally:
            _syncing["v"] = False
        _push_overlay_from_sidebar()

    def _on_angle_slider(v: int) -> None:
        if _syncing["v"]:
            return
        _syncing["v"] = True
        try:
            angle.setValue(float(v))
            angle_value.setText(f"{v}°")
        finally:
            _syncing["v"] = False
        _push_overlay_from_sidebar()

    def _on_kind_toggled(checked: bool) -> None:
        if not checked:
            return
        kind_value["v"] = "text" if text_kind.isChecked() else "image"
        sync_kind_visibility()
        _push_overlay_from_sidebar()

    def _on_placement(_cx: float, _cy: float) -> None:
        # Free drag clears exclusive snap highlight without changing center again.
        if _syncing["v"]:
            return
        checked = pos_group.checkedButton()
        if checked is not None:
            pos_group.setExclusive(False)
            checked.setChecked(False)
            pos_group.setExclusive(True)

    def _update_page_label() -> None:
        n = _page_count["n"]
        if n <= 0:
            page_label.setText("—")
            prev_btn.setEnabled(False)
            next_btn.setEnabled(False)
            return
        i = canvas.page_index + 1
        page_label.setText(f"{i} / {n}")
        prev_btn.setEnabled(i > 1)
        next_btn.setEnabled(i < n)

    def _update_zoom_label(factor: float) -> None:
        zoom_label.setText(f"{int(round(factor * 100))}%")

    def _on_files_changed() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            shell._chrome_host.hide()  # type: ignore[attr-defined]
            shell.set_drop_zone_visible(True)
            canvas.clear_source()
            _page_count["n"] = 0
            file_meta.setText("")
            _update_page_label()
            return
        source = paths[0]
        filename = Path(source).name
        password: str | None = None
        while True:
            try:
                loader = PdfLoader(source, password=password)
                try:
                    count = loader.page_count
                finally:
                    loader.close()
                break
            except PdfPasswordRequiredError:
                password = prompt_pdf_password(shell, filename)
                if password is None:
                    shell.drop_zone.clear()
                    return
            except PdfPasswordError:
                password = prompt_pdf_password(shell, filename, incorrect=True)
                if password is None:
                    shell.drop_zone.clear()
                    return
            except Exception as exc:
                QMessageBox.warning(
                    shell, shell.WINDOW_TITLE, f"Could not open PDF:\n{exc}"
                )
                shell.drop_zone.clear()
                return
        _page_count["n"] = count
        name = Path(source).name
        file_meta.setText(f"{name}  ·  {count} page{'s' if count != 1 else ''}")
        shell._chrome_host.show()  # type: ignore[attr-defined]
        shell.set_drop_zone_visible(False)
        canvas.set_source(
            source, page_count=count, page_index=0, password=password
        )
        _push_overlay_from_sidebar()
        _update_page_label()

    def _on_geometry_ready(_w: float, _h: float) -> None:
        checked = pos_group.checkedButton()
        if checked is not None:
            _apply_snap(position_value["v"])

    text_kind.toggled.connect(_on_kind_toggled)
    image_kind.toggled.connect(_on_kind_toggled)
    size_mode.currentIndexChanged.connect(
        lambda *_: (sync_kind_visibility(), _push_overlay_from_sidebar())
    )
    text.textChanged.connect(lambda *_: _push_overlay_from_sidebar())
    image.textChanged.connect(lambda *_: _push_overlay_from_sidebar())
    fontsize.valueChanged.connect(lambda *_: _push_overlay_from_sidebar())
    diagonal_pct.valueChanged.connect(lambda *_: _push_overlay_from_sidebar())
    image_scale.valueChanged.connect(lambda *_: _push_overlay_from_sidebar())
    opacity.valueChanged.connect(lambda *_: _push_overlay_from_sidebar())
    angle.valueChanged.connect(lambda *_: _push_overlay_from_sidebar())
    opacity_slider.valueChanged.connect(_on_opacity_slider)
    angle_slider.valueChanged.connect(_on_angle_slider)

    canvas.placement_changed.connect(_on_placement)
    canvas.angle_changed.connect(_pull_angle_from_canvas)
    canvas.size_changed.connect(_pull_size_from_canvas)
    canvas.page_changed.connect(lambda *_: _update_page_label())
    canvas.geometry_ready.connect(_on_geometry_ready)
    canvas.zoom_changed.connect(_update_zoom_label)
    canvas.render_error.connect(
        lambda msg: QMessageBox.warning(shell, shell.WINDOW_TITLE, f"Preview failed:\n{msg}")
    )

    prev_btn.clicked.connect(lambda: canvas.set_page(canvas.page_index - 1))
    next_btn.clicked.connect(lambda: canvas.set_page(canvas.page_index + 1))
    zoom_out.clicked.connect(lambda: canvas.zoom_by(-0.1))
    zoom_in.clicked.connect(lambda: canvas.zoom_by(0.1))

    sync_kind_visibility()
    shell.drop_zone.files_changed.connect(_on_files_changed)
    _on_files_changed()

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        page_count = _page_count["n"]
        if page_count <= 0:
            try:
                loader = PdfLoader(source)
                try:
                    page_count = loader.page_count
                finally:
                    loader.close()
            except Exception as exc:
                QMessageBox.warning(shell, shell.WINDOW_TITLE, f"Could not open PDF:\n{exc}")
                return

        raw_range = page_range.text().strip().casefold()
        pages: list[int] | None
        if raw_range in {"", "all"}:
            pages = None
        else:
            parsed = parse_page_ranges(page_range.text().strip(), page_count)
            if not parsed:
                QMessageBox.warning(
                    shell,
                    shell.WINDOW_TITLE,
                    'Enter "all" or valid page ranges (e.g. 1-3,5).',
                )
                return
            pages = []
            for start, end in parsed:
                pages.extend(range(start, end + 1))
            pages = sorted(set(pages))

        output = _pick_save_path(
            shell, "Save watermarked PDF", _suggested_output(source, "watermark")
        )
        if not output:
            return

        st = canvas.state
        k = kind_value["v"]
        use_diag = size_mode.currentData() == "diagonal"
        opts: dict = {
            "kind": k,
            "opacity": opacity.value(),
            "rotate": angle.value(),
            "position": position_value["v"],
            "center_x": st.center_x,
            "center_y": st.center_y,
            "flatten": flatten.isChecked(),
            "pages": pages,
            "diagonal_percent": diagonal_pct.value() if use_diag else None,
        }
        if k == "image":
            img = image.text().strip()
            if not img or not Path(img).is_file():
                QMessageBox.warning(shell, shell.WINDOW_TITLE, "Choose a watermark image.")
                return
            opts["image_path"] = img
            if not use_diag:
                opts["scale"] = image_scale.value()
        else:
            if not text.text().strip():
                QMessageBox.warning(shell, shell.WINDOW_TITLE, "Enter watermark text.")
                return
            opts["text"] = text.text().strip()
            opts["color"] = list(color_rgb)
            if not use_diag:
                opts["fontsize"] = fontsize.value()

        run_tool_job(
            shell,
            job_type="watermark",
            inputs=[source],
            output=output,
            options=opts,
            progress_message="Applying watermark…",
        )

    shell.set_run_handler(on_run)


def _configure_header_footer(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    header = QLineEdit()
    header.setPlaceholderText("Optional — tokens {page} {total}")
    footer = QLineEdit()
    footer.setPlaceholderText("Optional — tokens {page} {total}")
    form.addRow("Header", header)
    form.addRow("Footer", footer)
    hint = QLabel("At least one of header or footer is required.")
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        if not header.text().strip() and not footer.text().strip():
            QMessageBox.warning(
                shell, shell.WINDOW_TITLE, "Enter a header and/or footer."
            )
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save PDF", _suggested_output(source, "header_footer")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="header_footer",
            inputs=[source],
            output=output,
            options={
                "header": header.text().strip(),
                "footer": footer.text().strip(),
            },
            progress_message="Adding header and footer…",
        )

    shell.set_run_handler(on_run)


def _configure_page_numbers(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    template = QLineEdit("{page} / {total}")
    position = QComboBox()
    for label, data in _POSITIONS:
        position.addItem(label, data)
    start = QSpinBox()
    start.setRange(0, 999_999)
    start.setValue(1)
    form.addRow("Template", template)
    form.addRow("Position", position)
    form.addRow("Start at", start)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save numbered PDF", _suggested_output(source, "page_numbers")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="page_numbers",
            inputs=[source],
            output=output,
            options={
                "template": template.text().strip() or "{page}",
                "position": position.currentData(),
                "start": start.value(),
            },
            progress_message="Adding page numbers…",
        )

    shell.set_run_handler(on_run)


def _configure_bates(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    prefix = QLineEdit()
    prefix.setPlaceholderText("Optional prefix, e.g. EX-")
    start = QSpinBox()
    start.setRange(0, 999_999_999)
    start.setValue(1)
    digits = QSpinBox()
    digits.setRange(1, 12)
    digits.setValue(6)
    position = QComboBox()
    for label, data in _POSITIONS:
        position.addItem(label, data)
    position.setCurrentIndex(2)  # bottom-right
    form.addRow("Prefix", prefix)
    form.addRow("Start at", start)
    form.addRow("Digits", digits)
    form.addRow("Position", position)
    hint = QLabel(
        "Drop one or more PDFs. Numbering continues across files in drop order."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        opts = {
            "prefix": prefix.text(),
            "start": start.value(),
            "digits": digits.value(),
            "position": position.currentData(),
        }
        if len(paths) == 1:
            output = _pick_save_path(
                shell, "Save Bates PDF", _suggested_output(paths[0], "bates")
            )
            if not output:
                return
            run_tool_job(
                shell,
                job_type="bates",
                inputs=paths,
                output=output,
                options=opts,
                progress_message="Applying Bates numbers…",
            )
            return

        folder = QFileDialog.getExistingDirectory(
            shell, "Choose output folder for Bates PDFs", last_directory()
        )
        if not folder:
            return
        remember_directory(folder)
        first_name = f"{Path(paths[0]).stem}_bates.pdf"
        output = str(Path(folder) / first_name)
        opts["output_dir"] = folder
        run_tool_job(
            shell,
            job_type="bates",
            inputs=paths,
            output=output,
            options=opts,
            progress_message="Applying Bates numbers…",
        )

    shell.set_run_handler(on_run)


def _parse_bookmark_lines(text: str) -> list[list]:
    """Parse lines ``level|title|page`` (1-based page)."""
    rows: list[list] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            raise ValueError(
                f"Each bookmark line must be level|title|page (got {line!r})"
            )
        level, title, page = int(parts[0]), parts[1], int(parts[2])
        if level < 1 or page < 1 or not title:
            raise ValueError(f"Invalid bookmark entry: {line!r}")
        rows.append([level, title, page])
    return rows


def _configure_bookmarks(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    action = QComboBox()
    action.addItem("Replace from list", "set")
    action.addItem("One bookmark per page", "pages")
    action.addItem("Generate TOC page", "toc_page")
    action.addItem("Clear bookmarks", "clear")
    editor = QPlainTextEdit()
    editor.setPlaceholderText("level|title|page — one per line\n1|Introduction|1")
    editor.setMaximumHeight(120)
    status = QLabel("Drop a PDF to inspect existing bookmarks.")
    status.setObjectName("ToolsHint")
    status.setWordWrap(True)
    form.addRow("Action", action)
    form.addRow("Bookmarks", editor)
    form.addRow(status)
    shell.set_options_widget(options)

    def refresh_status() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            status.setText("Drop a PDF to inspect existing bookmarks.")
            return
        try:
            marks = get_bookmarks(paths[0])
        except Exception as exc:
            status.setText(f"Could not read bookmarks: {exc}")
            return
        if not marks:
            status.setText("No bookmarks in this PDF.")
            return
        status.setText(f"{len(marks)} bookmark(s). First: {marks[0].title!r}")
        if action.currentData() == "set" and not editor.toPlainText().strip():
            editor.setPlainText(
                "\n".join(f"{m.level}|{m.title}|{m.page}" for m in marks)
            )

    shell.drop_zone.files_changed.connect(refresh_status)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        act = action.currentData()
        opts: dict = {"action": act}
        if act == "set":
            try:
                rows = _parse_bookmark_lines(editor.toPlainText())
            except ValueError as exc:
                QMessageBox.warning(shell, shell.WINDOW_TITLE, str(exc))
                return
            opts["bookmarks"] = rows
        elif act == "toc_page":
            try:
                if not get_bookmarks(source):
                    QMessageBox.warning(
                        shell,
                        shell.WINDOW_TITLE,
                        "This PDF has no bookmarks to build a TOC from.",
                    )
                    return
            except Exception as exc:
                QMessageBox.warning(shell, shell.WINDOW_TITLE, str(exc))
                return
        output = _pick_save_path(
            shell, "Save PDF with bookmarks", _suggested_output(source, "bookmarks")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="bookmarks",
            inputs=[source],
            output=output,
            options=opts,
            progress_message="Updating bookmarks…",
        )

    shell.set_run_handler(on_run)


def _configure_annotations(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    action = QComboBox()
    action.addItem("Remove annotations", "remove")
    action.addItem("Flatten (bake into content)", "flatten")
    include = QComboBox()
    include.addItem("Include form fields", True)
    include.addItem("Annotations only", False)
    form.addRow("Action", action)
    form.addRow("Forms", include)
    hint = QLabel(
        "Flatten converts appearances to permanent page content. "
        "Author new markup from the PDF viewer annotation toolbar."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save PDF", _suggested_output(source, "annotations")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="annotations",
            inputs=[source],
            output=output,
            options={
                "action": action.currentData(),
                "include_widgets": include.currentData(),
            },
            progress_message="Processing annotations…",
        )

    shell.set_run_handler(on_run)


def _configure_blank_pages(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    threshold = QDoubleSpinBox()
    threshold.setRange(0.0, 1.0)
    threshold.setDecimals(3)
    threshold.setSingleStep(0.005)
    threshold.setValue(0.01)
    preview = QLabel("Drop a PDF, then Run to detect and confirm removal.")
    preview.setObjectName("ToolsHint")
    preview.setWordWrap(True)
    form.addRow("Ink threshold", threshold)
    form.addRow(preview)
    hint = QLabel(BLANK_PAGE_HEURISTIC_HINT)
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)
    shell._blank_preview = preview  # type: ignore[attr-defined]

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        try:
            report = detect_blank_pages(
                source, ink_threshold=threshold.value()
            )
        except Exception as exc:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, str(exc))
            return
        preview.setText(
            f"Detected {report.blank_count} blank of {report.page_count} pages "
            f"(indices {[i + 1 for i in report.blank_indices]})."
        )
        if report.blank_count == 0:
            QMessageBox.information(
                shell, shell.WINDOW_TITLE, "No blank pages detected."
            )
            return
        if not confirm_remove_blank_pages(
            shell,
            blank_count=report.blank_count,
            page_count=report.page_count,
            heuristic_hint=BLANK_PAGE_HEURISTIC_HINT,
        ):
            return
        output = _pick_save_path(
            shell, "Save PDF without blanks", _suggested_output(source, "blank_pages")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="blank_pages",
            inputs=[source],
            output=output,
            options={"ink_threshold": threshold.value()},
            progress_message="Removing blank pages…",
        )

    shell.set_run_handler(on_run)


def _configure_color_effects(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    effect = QComboBox()
    effect.addItem("Greyscale (keeps vectors)", "greyscale")
    effect.addItem("Invert (rasterizes)", "invert")
    effect.addItem("Background tint (keeps vectors)", "background")
    warning = QLabel("")
    warning.setObjectName("ToolsHint")
    warning.setWordWrap(True)

    def update_warning() -> None:
        if effect.currentData() == "invert":
            warning.setText(RASTER_EFFECT_WARNING)
        else:
            warning.setText("Greyscale and background tint keep vector content.")

    effect.currentIndexChanged.connect(update_warning)
    update_warning()
    form.addRow("Effect", effect)
    form.addRow(warning)
    shell.set_options_widget(options)
    shell._color_effect = effect  # type: ignore[attr-defined]
    shell._color_warning = warning  # type: ignore[attr-defined]

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        eff = effect.currentData()
        if eff == "invert":
            reply = QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                RASTER_EFFECT_WARNING + "\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        output = _pick_save_path(
            shell, "Save PDF", _suggested_output(source, "color_effects")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="color_effects",
            inputs=[source],
            output=output,
            options={"effect": eff},
            progress_message="Applying color effect…",
        )

    shell.set_run_handler(on_run)


_CONFIGURERS = {
    "crop": _configure_crop,
    "watermark": _configure_watermark,
    "header_footer": _configure_header_footer,
    "page_numbers": _configure_page_numbers,
    "bates": _configure_bates,
    "bookmarks": _configure_bookmarks,
    "annotations": _configure_annotations,
    "blank_pages": _configure_blank_pages,
    "color_effects": _configure_color_effects,
}


def open_modify_shell(tools: ToolsWindow, tool_id: str) -> ToolShellWindow | None:
    """Lazy-create / raise a Phase 28 document-modification shell."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    if tool_id not in SHELL_MODIFY_IDS:
        return None
    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    if entry is None:
        return None

    store = tool_shell_store(tools)  # type: ignore[assignment]

    shell = store.get(tool_id)
    ctx = editor_pdf_context(tools.editor)

    if shell is None:
        multi = tool_id == "bates"
        shell = ToolShellWindow(
            title=entry.title,
            description=entry.description,
            editor=tools.editor,
            window_manager=getattr(tools, "_window_manager", None),
            multi=multi,
            accept=is_pdf_path,
            dialog_filter=_PDF_FILTER,
            browse_title=f"Choose PDF — {entry.title}",
        )
        _CONFIGURERS[tool_id](shell)
        store[tool_id] = shell
    else:
        shell.set_editor(tools.editor)

    if ctx is not None and Path(ctx.path).is_file():
        shell.drop_zone.set_paths([ctx.path])

    present_tool_page(tools.editor, shell, page_id=f"tool:{tool_id}")
    return shell
