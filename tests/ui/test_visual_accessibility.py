"""Visual & platform accessibility — contrast, motion, focus, labels."""

from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.ui.accessibility import contrast_ratio, prefers_reduce_motion
from pagedrop.ui.base_file_card import BaseFileCard
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.preferences_dialog import PreferencesDialog
from pagedrop.ui.settings import reduce_motion, set_reduce_motion
from pagedrop.ui.theme import BG_BASE, TEXT_MUTED, app_stylesheet
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def test_p1_semantic_roles_and_shared_metrics(qtbot):
    """P1: role aliases and shared metrics drive light, dark, and HC chrome."""
    from pagedrop.ui.theme import (
        BACKGROUND,
        BACKGROUND_LIGHT,
        BG_BASE,
        BG_BASE_LIGHT,
        BG_CARD,
        BORDER,
        BORDER_DEFAULT,
        COMPACT_CONTROL_HEIGHT,
        DOCUMENT_CANVAS,
        FOREGROUND,
        FORM_CONTROL_HEIGHT,
        ICON_SIZE,
        ICON_SIZE_SMALL,
        INPUT,
        MUTED_FOREGROUND,
        ON_PRIMARY,
        PRIMARY,
        RAISED_SURFACE,
        RADIUS_CONTROL,
        RADIUS_SURFACE,
        SURFACE_DOCUMENT_CANVAS,
        SURFACE_RAISED,
        TEXT_MUTED,
        TEXT_ON_ACCENT,
        TEXT_PRIMARY,
    )

    assert (BACKGROUND, FOREGROUND, MUTED_FOREGROUND, BORDER, INPUT) == (
        BG_BASE,
        TEXT_PRIMARY,
        TEXT_MUTED,
        BORDER_DEFAULT,
        BG_CARD,
    )
    assert BACKGROUND_LIGHT == BG_BASE_LIGHT
    assert (PRIMARY, ON_PRIMARY) == ("#1868AD", TEXT_ON_ACCENT)
    assert DOCUMENT_CANVAS == SURFACE_DOCUMENT_CANVAS
    assert RAISED_SURFACE == SURFACE_RAISED
    assert (COMPACT_CONTROL_HEIGHT, FORM_CONTROL_HEIGHT) == (32, 36)
    assert (ICON_SIZE_SMALL, ICON_SIZE) == (16, 18)
    assert (RADIUS_CONTROL, RADIUS_SURFACE) == (6, 10)

    for sheet in (
        app_stylesheet(),
        app_stylesheet(light=True),
        app_stylesheet(high_contrast=True),
    ):
        for selector in (
            "QToolTip {",
            "QMenu {",
            "QDialog {",
            "QLineEdit {",
            "QToolBar {",
            "QLabel#ToolPageStatus {",
        ):
            assert selector in sheet
        assert f"border-radius: {RADIUS_CONTROL}px" in sheet
        assert f"border-radius: {RADIUS_SURFACE}px" in sheet

    app = QApplication.instance()
    assert app is not None
    previous_stylesheet = app.styleSheet()
    try:
        app.setStyleSheet(app_stylesheet())
        field = QLineEdit()
        qtbot.addWidget(field)
        field.setStyleSheet("font-size: 24px;")
        field.ensurePolished()
        assert field.minimumSizeHint().height() > FORM_CONTROL_HEIGHT
    finally:
        app.setStyleSheet(previous_stylesheet)


def test_text_muted_meets_wcag_aa_on_bg_base():
    assert contrast_ratio(TEXT_MUTED, BG_BASE) >= 4.5


def test_light_text_muted_meets_wcag_aa_on_bg_grid():
    # Keep in sync with app_stylesheet(light=True) text_muted / bg_grid tokens.
    from pagedrop.ui.theme import BG_GRID_LIGHT, TEXT_MUTED_LIGHT

    assert contrast_ratio(TEXT_MUTED_LIGHT, BG_GRID_LIGHT) >= 4.5
    assert TEXT_MUTED_LIGHT in app_stylesheet(light=True)


def test_high_contrast_stylesheet_strengthens_chrome():
    normal = app_stylesheet(high_contrast=False)
    high = app_stylesheet(high_contrast=True)
    assert "QToolBar QToolButton:focus" in normal
    assert "border: 2px solid" in normal
    assert "border: 3px solid" in high
    assert high != normal


def test_reduce_motion_setting_gates_shadow_hover(qtbot, isolated_settings):
    set_reduce_motion(True)
    assert reduce_motion() is True
    assert prefers_reduce_motion() is True

    card = MergeFileCard(0, "/tmp/a.pdf", 1)
    qtbot.addWidget(card)
    # Shadows are hover-only — resting cards carry no graphics effect.
    assert card._shadow is None

    pos = QPointF(8, 8)
    card.enterEvent(QEnterEvent(pos, pos, pos))
    # Reduce-motion: no shadow installed on hover either.
    assert card._shadow is None

    card.leaveEvent(None)
    set_reduce_motion(False)
    assert prefers_reduce_motion() is False
    card.enterEvent(QEnterEvent(pos, pos, pos))
    assert card._shadow is not None
    assert card._shadow.blurRadius() >= 18
    card.leaveEvent(None)
    assert card._shadow is None


def test_preferences_reduce_motion_persists(qtbot, isolated_settings):
    assert reduce_motion() is False
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    assert dialog._reduce_motion.isChecked() is False

    dialog._reduce_motion.setChecked(True)
    dialog._on_accept()
    assert reduce_motion() is True
    assert prefers_reduce_motion() is True

    dialog2 = PreferencesDialog()
    qtbot.addWidget(dialog2)
    assert dialog2._reduce_motion.isChecked() is True
    dialog2._reduce_motion.setChecked(False)
    dialog2._on_accept()
    assert reduce_motion() is False


def test_skeleton_pulse_skipped_when_reduce_motion(qtbot, isolated_settings):
    set_reduce_motion(True)
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid._skeleton_count = 1
    grid._start_skeleton_pulse()
    assert not grid._skeleton_pulse_active

    set_reduce_motion(False)
    grid._start_skeleton_pulse()
    assert grid._skeleton_pulse_active
    grid._stop_skeleton_pulse()
    assert not grid._skeleton_pulse_active


def test_stylesheet_includes_focus_rings_for_controls():
    sheet = app_stylesheet()
    assert "QToolBar QToolButton:focus" in sheet
    assert "QToolButton:checked" in sheet
    assert "QMenuBar::item:selected" in sheet
    # Menubar ::item:focus highlights every item under Qt — do not use it.
    assert "QMenuBar::item:focus" not in sheet
    assert "QMenu::item:selected" in sheet
    assert "QDialog {" in sheet
    assert "QListWidget," in sheet
    assert "QTreeWidget {" in sheet
    assert "QPushButton {" in sheet
    assert "QComboBox {" in sheet
    assert "QSpinBox," in sheet
    assert "QDoubleSpinBox {" in sheet
    assert "QPlainTextEdit," in sheet
    assert "QTextEdit {" in sheet
    assert "QGroupBox {" in sheet
    assert "QCheckBox," in sheet
    assert "QLineEdit {" in sheet
    assert "QSlider#ZoomSlider:focus" in sheet
    assert "QPushButton#ZoomButton:focus" in sheet
    assert "QTabWidget#PdfViewerSide::pane" in sheet
    assert "QCheckBox:focus::indicator" not in sheet
    assert "QRadioButton:focus::indicator" not in sheet
    assert "QCheckBox::indicator:focus" in sheet
    assert "QRadioButton::indicator:focus" in sheet


def test_checkbox_focus_ring_stays_on_indicator(qtbot, isolated_settings):
    """Fusion + ``:focus::indicator`` painted a full-widget accent box — keep ring on the square."""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication, QCheckBox, QVBoxLayout, QWidget

    from pagedrop.ui.theme import FOCUS_RING, app_stylesheet

    app = QApplication.instance()
    assert app is not None
    app.setStyleSheet(app_stylesheet(light=False))

    host = QWidget()
    host.setStyleSheet("background:#1A1A1F;")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(14, 14, 14, 14)
    cb = QCheckBox("Flatten watermark")
    lay.addWidget(cb)
    qtbot.addWidget(host)
    host.resize(400, 60)
    host.show()
    qtbot.waitExposed(host)
    cb.setFocus()
    qtbot.waitUntil(cb.hasFocus, timeout=1000)

    img = host.grab().toImage()
    ring = QColor(FOCUS_RING)
    g = cb.geometry()
    top_accent = sum(
        1
        for x in range(g.x(), g.x() + g.width())
        if img.pixelColor(x, g.y()) == ring
    )
    # Widget-level frame would paint nearly the full width; indicator is ~16–20px.
    assert top_accent < g.width() // 4
    assert top_accent > 0


def test_r10a_page_chips_and_prefs_chrome():
    """R10a: theme-aware chips, annot rail focus, prefs section/divider QSS."""
    from pagedrop.ui.theme import FOCUS_RING, FOCUS_RING_LIGHT, TEXT_ON_ACCENT

    dark = app_stylesheet()
    light = app_stylesheet(light=True)

    dark_chip = "rgba(19, 19, 22, 160)"
    light_chip = "rgba(26, 26, 31, 170)"

    for sheet, chip_bg, ring in (
        (dark, dark_chip, FOCUS_RING),
        (light, light_chip, FOCUS_RING_LIGHT),
    ):
        page = sheet.split("QLabel#PageCardPageOverlay")[1].split("}")[0]
        rot = sheet.split("QLabel#PageCardRotationOverlay")[1].split("}")[0]
        assert chip_bg in page
        assert chip_bg in rot
        assert TEXT_ON_ACCENT in page
        assert "QLabel#PreferencesSection" in sheet
        assert "QFrame#PreferencesDivider" in sheet
        assert "QWidget#PdfViewerAnnotTools QToolButton:focus" in sheet
        assert "QWidget#PdfViewerAnnotTools QToolButton:pressed" in sheet
        assert "QToolButton#PdfViewerAnnotCollapse:focus" in sheet
        assert "QToolButton#PdfViewerAnnotExpand:pressed" in sheet
        assert f"solid {ring}" in sheet.split(
            "QWidget#PdfViewerAnnotTools QToolButton:focus"
        )[1].split("}")[0]

    # Light sheet must not rely on the dark-only hardcoded chip rgba alone.
    light_page = light.split("QLabel#PageCardPageOverlay")[1].split("}")[0]
    assert dark_chip not in light_page
    assert light_chip in light_page


def test_r10a_prefs_dialog_has_section_dividers(qtbot, isolated_settings):
    """R10a: prefs groups are separated by PreferencesDivider frames."""
    from PyQt6.QtWidgets import QFrame, QLabel

    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    assert len(dialog.findChildren(QLabel, "PreferencesSection")) == 6
    assert len(dialog.findChildren(QFrame, "PreferencesDivider")) == 5


def test_preferences_advanced_details_do_not_crowd_routine_controls(
    qtbot, isolated_settings
):
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.findChild(QScrollArea, "PreferencesScroll") is not None
    assert dialog.findChild(QDialogButtonBox) is not None
    assert dialog._advanced_button.accessibleName() != ""
    assert dialog._advanced.isHidden()
    dialog._advanced_button.click()
    assert dialog._advanced.isVisible()


def test_r10b_empty_drop_affordance_and_glyphs(qtbot):
    """R10b: editor empty dashed/dropActive; queue kbd; logo-only editor."""
    from PyQt6.QtWidgets import QLabel, QPushButton

    from pagedrop.ui.convert_file_grid import ConvertFileGrid
    from pagedrop.ui.merge_file_grid import MergeFileGrid
    from pagedrop.ui.theme import ACCENT, app_stylesheet
    from pagedrop.ui.thumbnail_grid import ThumbnailGrid

    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
        empty = sheet.split("QWidget#EmptyStatePanel {")[1].split(
            "QWidget#EmptyStatePanel[dropActive"
        )[0]
        assert "border: 1px dashed" in empty
        assert 'QWidget#EmptyStatePanel[dropActive="true"]' in sheet
        assert f"border-color: {ACCENT}" in sheet.split(
            'QWidget#EmptyStatePanel[dropActive="true"]'
        )[1].split("}")[0]

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    assert grid._empty_kbd.text() == "or drop a file here"
    assert grid._empty_logo.accessibleName() == "PageDrop logo"
    # Editor keeps logo only — no second empty glyph label.
    empty_labels = [
        w
        for w in grid._empty_state.findChildren(QLabel)
        if w.parent() is grid._empty_state
    ]
    assert empty_labels == [
        grid._empty_logo,
        grid._empty_title,
        grid._empty_hint,
        grid._empty_kbd,
    ]
    assert isinstance(grid._empty_open_button, QPushButton)

    merge = MergeFileGrid()
    convert = ConvertFileGrid()
    qtbot.addWidget(merge)
    qtbot.addWidget(convert)
    assert "Drop PDFs" in merge._empty_kbd.text()
    assert "Drop images" in convert._empty_kbd.text()
    assert "← →" not in merge._empty_kbd.text()
    assert merge._empty_glyph_name == "stack"
    assert convert._empty_glyph_name == "images"


def test_r10c_press_feedback_gaps(qtbot):
    """R10c: named pushables + ToolTile expose pressed darken (no CSS scale)."""
    from PyQt6.QtCore import QPoint, Qt

    from pagedrop.ui.theme import app_stylesheet
    from pagedrop.ui.tools_window import TOOL_CATALOGUE, ToolTile

    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
        assert "QPushButton#BusyOverlayCancel:pressed" in sheet
        assert "QPushButton#ToastOverlayUndo:pressed" in sheet
        assert "QPushButton#WatermarkZoomButton:pressed:enabled" in sheet
        assert 'QFrame#ToolTile[pressed="true"]' in sheet
        assert "QTabWidget#TabManager QTabBar QAbstractButton:pressed" in sheet
        assert "QWidget#PdfViewerAnnotTools QToolButton:pressed" in sheet
        assert "transform:" not in sheet
        assert "scale(" not in sheet

    entry = next(e for e in TOOL_CATALOGUE if e.id == "merge")
    tile = ToolTile(entry)
    qtbot.addWidget(tile)
    tile.resize(200, 100)
    tile.show()
    assert tile.property("pressed") is False

    activated: list[str] = []
    tile.activated.connect(activated.append)
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert tile.property("pressed") is True
    qtbot.mouseRelease(tile, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert tile.property("pressed") is False
    assert activated == [entry.id]


def test_r10e_feedback_hygiene_chrome():
    """R10e: Tools footer / undo / splitter / scrollbar pressed; no progress sweep."""
    from pagedrop.ui.theme import app_stylesheet

    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
        assert "QLabel#ToolPageStatus" in sheet
        assert "QWidget#MoveUndoToast QLabel" in sheet
        assert "QPushButton#MoveUndoButton:pressed" in sheet
        assert "QScrollBar::handle:vertical:pressed" in sheet
        assert "QScrollBar::handle:horizontal:pressed" in sheet
        assert "QSplitter::handle:pressed" in sheet
        # Static accent chunk only — no indeterminate shimmer widget.
        assert "QProgressBar::chunk" in sheet
        assert "@keyframes" not in sheet
        assert "indeterminate" not in sheet.lower()


def test_light_stylesheet_styles_dialogs(isolated_settings):
    light = app_stylesheet(light=True)
    assert "#F7F8FA" in light
    assert "QDialog {" in light
    assert "QListWidget::item:selected" in light
    assert "QTreeWidget::item:selected" in light
    assert "QTabWidget#PdfViewerSide::pane" in light
    # Viewer QToolButtons sit outside QToolBar — must still get light ink.
    assert "QToolButton," in light
    assert "color: #1A1A1F" in light
    assert "background-color: #FFFFFF" in light
    assert "QFrame#WatermarkOptionsCard" in light
    assert "QPushButton#ToolbarPrimary" in light


def test_r3_toolbar_default_is_flat():
    """R3: default tool buttons are transparent/hairline, not dense bordered cards."""
    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
        block = sheet.split("QToolButton,")[1].split("QToolButton:hover,")[0]
        assert "transparent" in block
        assert "border: 1px solid transparent" in block
        # Primary fill still uses accent; default tools must not.
        from pagedrop.ui.theme import ACCENT

        assert ACCENT not in block


def test_r3_primary_label_meets_wcag_aa_on_accent():
    """R3: TEXT_ON_ACCENT on accent fill/hover/pressed ≥ 4.5:1 (dark + light share tokens)."""
    from pagedrop.ui.theme import ACCENT, ACCENT_HOVER, ACCENT_PRESSED, TEXT_ON_ACCENT

    for bg in (ACCENT, ACCENT_HOVER, ACCENT_PRESSED):
        assert contrast_ratio(TEXT_ON_ACCENT, bg) >= 4.5
    # Primary QSS still wires white ink onto the accent fill.
    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
        primary = sheet.split("QPushButton#ToolbarPrimary,")[1].split(
            "QPushButton#ToolbarPrimary:hover"
        )[0]
        assert ACCENT in primary
        assert TEXT_ON_ACCENT in primary


def test_r3_zoom_controls_use_spacing_tokens(qtbot):
    """R3: zoom cluster margins/gaps read from SPACE_* tokens."""
    from pagedrop.ui.theme import SPACE_1, SPACE_2

    zoom = ZoomControls(min_width=80, max_width=480, step=16, initial=160)
    qtbot.addWidget(zoom)
    margins = zoom.layout().contentsMargins()
    assert margins.left() == SPACE_2
    assert margins.top() == SPACE_1
    assert margins.right() == SPACE_2
    assert margins.bottom() == SPACE_1
    assert zoom.layout().spacing() == SPACE_1
    sheet = app_stylesheet()
    assert "QWidget#ZoomControls" in sheet
    zoom_block = sheet.split("QWidget#ZoomControls")[1].split("QPushButton#ZoomButton")[0]
    assert "background-color:" in zoom_block
    assert "transparent" not in zoom_block.split("background-color:")[1].split(";")[0]


def test_r3_toolbar_roles_match_action_weight(main_window, qtbot):
    """R3: Open / Merge / Save PDF / Run are primary; browse/add are secondary."""
    from pagedrop.ui import icons
    from pagedrop.ui.theme import ICON_SIZE, ON_PRIMARY

    open_btn = main_window._toolbar.widgetForAction(main_window._actions["open"])
    assert open_btn is not None
    assert open_btn.objectName() == "ToolbarPrimary"
    assert open_btn.icon().cacheKey() == icons.icon(
        "folder-open", color=ON_PRIMARY
    ).cacheKey()
    assert main_window._toolbar.iconSize().width() == ICON_SIZE
    preview = main_window._toolbar.widgetForAction(main_window._actions["preview"])
    assert preview is not None
    assert preview.objectName() == ""

    from pagedrop.ui.merge_window import MergeWindow

    merge = MergeWindow()
    qtbot.addWidget(merge)
    assert merge._toolbar.widgetForAction(merge._add_action).objectName() == "ToolbarSecondary"
    assert (
        merge._toolbar.widgetForAction(merge._add_folder_action).objectName()
        == "ToolbarSecondary"
    )
    assert merge._toolbar.widgetForAction(merge._merge_action).objectName() == "ToolbarPrimary"
    assert merge._merge_action.icon().cacheKey() == icons.icon(
        "floppy-disk", color=ON_PRIMARY
    ).cacheKey()
    assert merge._toolbar.iconSize().width() == ICON_SIZE

    from pagedrop.ui.convert_window import ConvertWindow

    convert = ConvertWindow()
    qtbot.addWidget(convert)
    assert (
        convert._toolbar.widgetForAction(convert._add_action).objectName()
        == "ToolbarSecondary"
    )
    assert (
        convert._toolbar.widgetForAction(convert._create_action).objectName()
        == "ToolbarPrimary"
    )
    assert convert._create_action.icon().cacheKey() == icons.icon(
        "floppy-disk", color=ON_PRIMARY
    ).cacheKey()
    assert convert._toolbar.iconSize().width() == ICON_SIZE

    from pagedrop.ui.tool_shell import ToolShellWindow

    shell = ToolShellWindow(title="Demo", description="Role audit")
    qtbot.addWidget(shell)
    assert shell._run_btn.objectName() == "ToolbarPrimary"
    assert shell.drop_zone._clear_btn.objectName() == "ToolbarSecondary"


def test_theme_smoke_light_dark_and_high_contrast():
    """O8: tokens + objectName chrome present in dark, light, and HC sheets."""
    from pagedrop.ui.theme import (
        ACCENT,
        STATUS_SUCCESS,
        STATUS_SUCCESS_LIGHT,
        STATUS_WARNING,
        STATUS_WARNING_LIGHT,
        TEXT_ON_ACCENT,
        VIEWER_PAGE_BG,
        token_qcolor,
    )

    dark = app_stylesheet()
    light = app_stylesheet(light=True)
    high = app_stylesheet(high_contrast=True)

    for sheet, success, warning in (
        (dark, STATUS_SUCCESS, STATUS_WARNING),
        (light, STATUS_SUCCESS_LIGHT, STATUS_WARNING_LIGHT),
        (high, STATUS_SUCCESS, STATUS_WARNING),
    ):
        assert "QFrame#DropIndicator" in sheet
        assert "QLabel#ToolsErrorHint" in sheet
        assert "QLabel#ComparePaneTitle" in sheet
        assert "QLabel#CompareModeLabel" in sheet
        assert "QLabel#CompareSummary" in sheet
        assert VIEWER_PAGE_BG in sheet
        assert "QPushButton#ToolbarSecondary" in sheet
        assert f"color: {success}" in sheet
        assert f"color: {warning}" in sheet
        assert f"color: {TEXT_ON_ACCENT}" in sheet
        # Success toast must not fall back to accent blue.
        assert 'ToastOverlayMessage[kind="success"]' in sheet
        success_block = sheet.split('ToastOverlayMessage[kind="success"]')[1].split("}")[0]
        assert success in success_block
        assert ACCENT.lstrip("#") not in success_block
        assert "2F9BE6" not in success_block

    assert high != dark
    assert "border: 3px solid" in high
    assert STATUS_SUCCESS.startswith("#")
    assert STATUS_WARNING.startswith("#")
    assert token_qcolor(STATUS_SUCCESS, 90).alpha() == 90


def test_toolbar_secondary_is_ghost_not_primary():
    """R1: #ToolbarSecondary is outline/ghost, distinct from filled primary (dark+light)."""
    from pagedrop.ui.theme import ACCENT

    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
        assert "QPushButton#ToolbarSecondary" in sheet
        assert "QToolBar QToolButton#ToolbarSecondary" in sheet
        secondary = sheet.split("QPushButton#ToolbarSecondary,")[1].split(
            "QPushButton#ToolbarSecondary:hover"
        )[0]
        assert "transparent" in secondary
        assert ACCENT not in secondary
        primary = sheet.split("QPushButton#ToolbarPrimary,")[1].split(
            "QPushButton#ToolbarPrimary:hover"
        )[0]
        assert ACCENT in primary
        assert "transparent" not in primary


def test_paint_helpers_pair_with_light_stylesheet(isolated_settings):
    """R1: border/shadow paint helpers share light tokens with app_stylesheet."""
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import (
        BORDER_HOVER,
        BORDER_HOVER_LIGHT,
        SHADOW_ALPHA_CAP_LIGHT,
        SHADOW_RGB,
        SHADOW_RGB_LIGHT,
        border_hover_qcolor,
        shadow_qcolor,
    )

    light_sheet = app_stylesheet(light=True)
    dark_sheet = app_stylesheet(light=False)
    assert BORDER_HOVER_LIGHT in light_sheet
    assert BORDER_HOVER in dark_sheet

    set_light_theme(True)
    light_border = border_hover_qcolor()
    assert light_border.name().upper() == BORDER_HOVER_LIGHT.upper()
    light_shadow = shadow_qcolor(alpha=72)
    assert (light_shadow.red(), light_shadow.green(), light_shadow.blue()) == SHADOW_RGB_LIGHT
    assert light_shadow.alpha() == SHADOW_ALPHA_CAP_LIGHT

    set_light_theme(False)
    dark_border = border_hover_qcolor()
    assert dark_border.name().upper() == BORDER_HOVER.upper()
    dark_shadow = shadow_qcolor(alpha=72)
    assert (dark_shadow.red(), dark_shadow.green(), dark_shadow.blue()) == SHADOW_RGB
    assert dark_shadow.alpha() == 72


def test_drop_indicator_uses_object_name_not_inline_stylesheet(qtbot):
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    assert grid._drop_indicator.objectName() == "DropIndicator"
    # Theme stylesheet owns the accent fill so theme refresh stays coherent.
    assert not grid._drop_indicator.styleSheet()


def test_progress_and_empty_state_accessible_names(main_window, qtbot):
    assert main_window._progress_bar.accessibleName() == "Page rendering progress"

    grid = main_window._thumbnail_grid
    assert isinstance(grid, ThumbnailGrid)
    assert grid._empty_state.accessibleName()
    assert grid._empty_logo.accessibleName() == "PageDrop logo"

    corner = main_window._tab_manager.cornerWidget(Qt.Corner.TopRightCorner)
    new_tab = corner.findChild(QToolButton, "NewTabButton")
    assert new_tab.accessibleName() == "New tab"

    zoom = main_window._zoom_controls
    assert isinstance(zoom, ZoomControls)
    assert zoom.accessibleName() == "Thumbnail zoom"
    assert zoom._slider.accessibleName() == "Thumbnail size"
    assert zoom._zoom_out.accessibleName() == "Zoom out"
    assert zoom._zoom_in.accessibleName() == "Zoom in"


def test_base_file_card_is_not_imported_cycle():
    assert issubclass(MergeFileCard, BaseFileCard)


def test_watermark_selection_chrome_uses_accent_token():
    """O14: watermark selection border/handles use the accent theme token, not a literal."""
    from pagedrop.ui.theme import ACCENT, accent_qcolor, on_accent_qcolor

    # accent_qcolor() must match the ACCENT token in both light and dark mode.
    color = accent_qcolor()
    assert color.isValid()
    assert f"#{color.red():02X}{color.green():02X}{color.blue():02X}" == ACCENT.upper()

    # on_accent_qcolor() must be fully opaque white (readable on accent backgrounds).
    ink = on_accent_qcolor()
    assert ink.isValid()
    assert ink.red() == 255
    assert ink.green() == 255
    assert ink.blue() == 255

    assert ACCENT.upper() == "#1868AD"


def test_r2_fonts_and_spacing_tokens():
    """R2: Windows-first fonts unchanged; spacing scale feeds toolbar/grid chrome."""
    from pagedrop.ui.theme import (
        CARD_PADDING,
        FONT_MONO,
        FONT_UI,
        SPACE_2,
        SPACE_3,
        SPACE_4,
    )

    assert FONT_UI.startswith('"Segoe UI Variable"')
    assert "Segoe UI" in FONT_UI
    assert FONT_MONO.startswith('"Cascadia Mono"')
    # R2: do not expand for Linux-friendly product faces.
    assert "Ubuntu" not in FONT_UI
    assert "Noto" not in FONT_UI
    assert "SF Pro" not in FONT_UI

    assert CARD_PADDING == SPACE_4 == 16
    assert SPACE_3 == 12
    sheet = app_stylesheet()
    assert FONT_UI in sheet
    assert FONT_MONO in sheet
    assert f"padding: {SPACE_2}px {SPACE_3}px" in sheet
    assert f"padding: 0 0 {SPACE_3}px 0" in sheet


def test_r2_empty_state_drop_copy_and_spacing(qtbot):
    """Empty-state drop copy stays concise; spacing reads from tokens."""
    from pagedrop.ui.theme import SPACE_2, SPACE_3, SPACE_4, SPACE_6, SPACE_7

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    assert grid._layout.spacing() == SPACE_3
    assert grid._layout.contentsMargins().left() == SPACE_4
    empty_layout = grid._empty_state.layout()
    assert empty_layout.spacing() == SPACE_2
    empty_margins = empty_layout.contentsMargins()
    assert empty_margins.left() == SPACE_6
    assert empty_margins.top() == SPACE_7
    assert grid._empty_kbd.text() == "or drop a file here"


def test_r5_card_chrome_and_empty_tokens():
    """R5: quieter rest border, HC-aware select/focus widths, empty QSS tokens."""
    from pagedrop.ui.theme import (
        ACCENT,
        RADIUS_BADGE,
        SHADOW_ALPHA_CAP_LIGHT,
        SPACE_2,
        app_stylesheet,
    )

    dark = app_stylesheet()
    high = app_stylesheet(high_contrast=True)

    page_block = dark.split("QFrame#PageCard {")[1].split("QFrame#MergeFileCard,")[0]
    assert "background-color: transparent" in page_block
    assert "QLabel#PageCardFocusRing" in dark
    assert "QLabel#PageCardSelectionIndicator" in dark
    assert f"border: 3px solid {ACCENT}" in dark
    assert f"border: 4px solid {ACCENT}" in high
    assert f"border-radius: {RADIUS_BADGE}px" in dark
    assert f"padding: {SPACE_2}px 0 0 0" in dark
    assert SHADOW_ALPHA_CAP_LIGHT == 48


def test_r5_multi_select_drag_badge_visible(qtbot):
    """R5: multi-page drag pixmap paints an accent count badge."""
    from PyQt6.QtGui import QColor, QPixmap

    from pagedrop.ui.page_card import PageCard
    from pagedrop.ui.theme import ACCENT

    card = PageCard(0)
    qtbot.addWidget(card)
    thumb = QPixmap(80, 100)
    thumb.fill(QColor("#CCCCCC"))
    card.set_thumbnail(thumb)

    badge_pixmap = card._build_drag_pixmap(3)
    assert badge_pixmap is not None
    assert badge_pixmap.width() > thumb.width()

    accent = QColor(ACCENT)
    found_accent = False
    # Sample the top-right badge region for accent fill pixels.
    image = badge_pixmap.toImage()
    for y in range(2, min(28, badge_pixmap.height())):
        for x in range(max(0, badge_pixmap.width() - 40), badge_pixmap.width()):
            c = QColor(image.pixel(x, y))
            if (
                abs(c.red() - accent.red()) < 8
                and abs(c.green() - accent.green()) < 8
                and abs(c.blue() - accent.blue()) < 8
            ):
                found_accent = True
                break
        if found_accent:
            break
    assert found_accent


def test_r5_smoke_select_hover_focus_drag_badge(qtbot, isolated_settings):
    """R5 smoke stand-in: select, multi-select chrome, hover shadow, focus, drag badge."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QColor, QEnterEvent, QPixmap

    from pagedrop.ui.page_card import PageCard
    from pagedrop.ui.settings import set_reduce_motion
    from pagedrop.ui.theme import ACCENT, app_stylesheet

    set_reduce_motion(False)
    sheet = app_stylesheet()
    assert "QFrame#PageCard:hover" in sheet
    assert 'QFrame#PageCard[selected="true"]' in sheet
    assert "QLabel#PageCardFocusRing" in sheet

    card = PageCard(0)
    qtbot.addWidget(card)
    thumb = QPixmap(80, 100)
    thumb.fill(QColor("#DDDDDD"))
    card.set_thumbnail(thumb)

    # Select / focus rings stay property-driven (no inline stylesheet).
    card.set_selected(True)
    assert card.property("selected") is True
    assert not card.styleSheet()
    card.set_keyboard_focused(True)
    assert card.property("focused") is True

    # Hover installs cool drop shadow (reduce-motion off).
    assert card._shadow is None
    pos = QPointF(8, 8)
    card.enterEvent(QEnterEvent(pos, pos, pos))
    assert card._shadow is not None
    assert card._shadow.blurRadius() >= 18
    card.leaveEvent(None)
    assert card._shadow is None

    # Multi-select drag badge still paints accent ink.
    badge = card._build_drag_pixmap(4)
    assert badge is not None
    accent = QColor(ACCENT)
    image = badge.toImage()
    assert any(
        abs(QColor(image.pixel(x, y)).red() - accent.red()) < 8
        and abs(QColor(image.pixel(x, y)).green() - accent.green()) < 8
        and abs(QColor(image.pixel(x, y)).blue() - accent.blue()) < 8
        for y in range(2, min(28, badge.height()))
        for x in range(max(0, badge.width() - 40), badge.width())
    )


def test_r6_tab_manager_underline_and_inactive_mute():
    """R6: selected tab uses accent underline; inactive tabs stay muted; no filled box."""
    from pagedrop.ui.theme import ACCENT, app_stylesheet

    dark = app_stylesheet()
    light = app_stylesheet(light=True)
    high = app_stylesheet(high_contrast=True)

    for sheet in (dark, light, high):
        assert "QTabWidget#TabManager > QTabBar::tab:selected" in sheet
        selected = sheet.split("QTabWidget#TabManager > QTabBar::tab:selected")[
            1
        ].split("QTabWidget#TabManager > QTabBar::tab:hover")[0]
        assert f"border-bottom: 2px solid {ACCENT}" in selected
        assert "background-color: transparent" in selected
        rest = sheet.split("QTabWidget#TabManager > QTabBar::tab {")[1].split(
            "QTabWidget#TabManager > QTabBar::tab:selected"
        )[0]
        assert "color:" in rest
        assert "background-color: transparent" in rest


def test_r6_tool_tile_quiet_chrome_keeps_focus_rings():
    """R6: ToolTiles are quiet at rest; focus rings stay HC-aware and visible."""
    from pagedrop.ui.theme import FOCUS_RING, FOCUS_RING_LIGHT, app_stylesheet

    dark = app_stylesheet()
    high = app_stylesheet(high_contrast=True)
    light = app_stylesheet(light=True)

    rest = dark.split("QFrame#ToolTile {")[1].split("QFrame#ToolTile:hover")[0]
    assert "background-color: transparent" in rest
    assert "border: 1px solid transparent" in rest

    assert "QFrame#ToolTile:focus" in dark
    assert f"border: 2px solid {FOCUS_RING}" in dark
    assert f"border: 3px solid {FOCUS_RING}" in high
    assert f"border: 2px solid {FOCUS_RING_LIGHT}" in light
    assert 'QFrame#ToolTile[blocked="true"]:hover' in dark
    assert 'QFrame#ToolTile[compact="true"]' in dark


def test_r6_tool_shell_drop_and_result_match_secondary():
    """R6: drop zone + result actions use ghost/outline secondary language."""
    from pagedrop.ui.theme import (
        BG_BASE,
        BG_BASE_LIGHT,
        FOCUS_RING,
        FOCUS_RING_LIGHT,
        app_stylesheet,
    )

    for sheet, expected_base, ring in (
        (app_stylesheet(), BG_BASE, FOCUS_RING),
        (app_stylesheet(light=True), BG_BASE_LIGHT, FOCUS_RING_LIGHT),
    ):
        drop = sheet.split("QFrame#ToolShellDropZone {")[1].split(
            "QFrame#ToolShellDropZone[dropActive"
        )[0]
        assert "background-color: transparent" in drop
        assert "border: 1px dashed" in drop

        bar = sheet.split("QWidget#ResultActionsBar {")[1].split(
            "QLabel#ResultActionsLabel"
        )[0]
        assert "background-color: transparent" in bar

        btn = sheet.split("QPushButton#ResultActionsPreview,")[1].split(
            "QPushButton#ResultActionsPreview:hover"
        )[0]
        assert "background-color: transparent" in btn
        assert "border: 1px solid" in btn
        assert "QFrame#ToolShellDropZone:focus" in sheet
        assert f"dashed {ring}" in sheet

        # Light/dark: options scroll must be solid — transparent + unthemed
        # viewport paints charcoal under light ink (Watermark-class bug).
        opts = sheet.split("QScrollArea#ToolShellOptionsScroll {")[1].split("}")[0]
        assert "transparent" not in opts
        assert expected_base in opts
        assert "QWidget#ToolShellWindow" in sheet
        assert "QWidget#ToolShellCentral" not in sheet


def test_r7_toast_motion_gated_by_reduce_motion(qtbot, isolated_settings):
    """R7: toast slides/fades when motion on; instant when reduce-motion."""
    from PyQt6.QtCore import QAbstractAnimation
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.busy_overlay import ToastOverlay
    from pagedrop.ui.theme import STATUS_SUCCESS

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(400, 300)
    parent.show()
    toast = ToastOverlay(parent)

    set_reduce_motion(False)
    toast.show_toast("Saved", kind="success")
    assert toast.isVisible()
    assert toast._message.property("kind") == "success"
    # Kind chrome stays semantic during enter (R1 success green, not delayed).
    assert STATUS_SUCCESS.startswith("#")
    assert toast._motion_anim.state() == QAbstractAnimation.State.Running
    assert toast.motion_t > 0.0
    qtbot.waitUntil(
        lambda: toast._motion_anim.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    assert toast.motion_t == 0.0
    assert toast._opacity_effect is not None
    assert toast._opacity_effect.opacity() == 1.0

    toast.hide()
    set_reduce_motion(True)
    toast.show_toast("Saved", kind="success")
    assert toast.isVisible()
    assert toast._motion_anim.state() == QAbstractAnimation.State.Stopped
    assert toast.motion_t == 0.0
    assert toast._opacity_effect is None
    assert toast._message.property("kind") == "success"


def test_r7_busy_overlay_opacity_fade_keeps_cancel_hittable(qtbot, isolated_settings):
    """R7: busy fades opacity only; Cancel works mid-fade."""
    from PyQt6.QtCore import QAbstractAnimation
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.busy_overlay import BusyOverlay

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(320, 240)
    host.show()
    overlay = BusyOverlay(host)
    overlay.set_cancellable(True)
    cancelled: list[bool] = []
    overlay.cancelled.connect(lambda: cancelled.append(True))

    set_reduce_motion(False)
    overlay.show_message("Working…")
    assert overlay.isVisible()
    assert overlay._fade.state() == QAbstractAnimation.State.Running
    assert overlay._opacity_effect is not None
    assert overlay._opacity_effect.opacity() < 1.0
    assert overlay._cancel_btn.isVisible()
    assert overlay._cancel_btn.isEnabled()
    overlay._cancel_btn.click()
    assert cancelled == [True]

    overlay.hide_overlay()
    assert overlay._hiding is True
    assert overlay.isVisible()
    assert overlay._cancel_btn.isVisible()
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=1000)
    assert overlay._opacity_effect is None

    set_reduce_motion(True)
    overlay.show_message("Working…")
    assert overlay.isVisible()
    assert overlay._fade.state() == QAbstractAnimation.State.Stopped
    assert overlay._opacity_effect is None
    overlay.hide_overlay()
    assert not overlay.isVisible()


def test_r10c_busy_overlay_no_refade_while_visible(qtbot, isolated_settings):
    """R10c: progress updates change the label without restarting opacity fade."""
    from PyQt6.QtCore import QAbstractAnimation
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.busy_overlay import BusyOverlay

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(320, 240)
    host.show()
    overlay = BusyOverlay(host)
    overlay.set_cancellable(True)

    set_reduce_motion(False)
    overlay.show_message("Working…")
    qtbot.waitUntil(
        lambda: overlay._fade.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    assert overlay._opacity_effect is not None
    assert overlay._opacity_effect.opacity() == 1.0

    overlay.show_message("Page 2 of 10…")
    assert overlay._message.text() == "Page 2 of 10…"
    assert overlay._fade.state() == QAbstractAnimation.State.Stopped
    assert overlay._opacity_effect.opacity() == 1.0
    assert overlay._cancel_btn.isVisible()
    assert overlay._cancel_btn.isEnabled()

    # Mid-enter progress tick must not restart the fade from 0.
    overlay.hide_overlay()
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=1000)
    overlay.show_message("Working…")
    assert overlay._fade.state() == QAbstractAnimation.State.Running
    opacity_mid = overlay._opacity_effect.opacity()
    overlay.show_message("Still working…")
    assert overlay._message.text() == "Still working…"
    assert overlay._fade.state() == QAbstractAnimation.State.Running
    assert overlay._opacity_effect.opacity() >= opacity_mid

    set_reduce_motion(True)
    overlay.hide_overlay()
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=1000)
    overlay.show_message("Working…")
    assert overlay._opacity_effect is None
    overlay.show_message("Almost done…")
    assert overlay._message.text() == "Almost done…"
    assert overlay._fade.state() == QAbstractAnimation.State.Stopped
    assert overlay._opacity_effect is None


def test_r7_feedback_motion_only_in_busy_overlay():
    """R7/R10d: QPropertyAnimation only on allowlisted feedback surfaces."""
    from pathlib import Path

    ui_root = Path(__file__).resolve().parents[2] / "src" / "pagedrop" / "ui"
    animated = sorted(
        path.name
        for path in ui_root.glob("*.py")
        if "QPropertyAnimation" in path.read_text(encoding="utf-8")
    )
    # busy_overlay (toast/busy); grid_helpers (drop indicator); page_card (skeleton).
    assert animated == ["busy_overlay.py", "grid_helpers.py", "page_card.py"]


def test_r10d_drop_indicator_fade_show_hide_only(qtbot, five_page_pdf, isolated_settings):
    """R10d: fade on first show / final hide; reposition while visible is instant."""
    from PyQt6.QtCore import QAbstractAnimation

    from pagedrop.core.pdf_loader import PdfLoader
    from pagedrop.ui.settings import set_reduce_motion
    from tests.conftest import wait_for_grid_loaded

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    grid.show()
    loader = PdfLoader(str(five_page_pdf))
    grid.load_pdf(loader)
    wait_for_grid_loaded(qtbot, grid)
    grid._reflow_grid(force=True)

    set_reduce_motion(False)
    indicator = grid._drop_indicator
    grid._update_drop_indicator(1)
    assert indicator.isVisible()
    assert indicator._fade.state() == QAbstractAnimation.State.Running
    qtbot.waitUntil(
        lambda: indicator._fade.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    assert indicator._opacity_effect is not None
    assert indicator._opacity_effect.opacity() == 1.0
    geo_a = indicator.geometry()

    grid._update_drop_indicator(2)
    assert indicator.isVisible()
    assert indicator._fade.state() == QAbstractAnimation.State.Stopped
    assert indicator._opacity_effect.opacity() == 1.0
    assert indicator.geometry() != geo_a

    grid._hide_drop_indicator()
    assert indicator._hiding is True
    assert indicator.isVisible()
    qtbot.waitUntil(lambda: not indicator.isVisible(), timeout=1000)
    assert indicator._opacity_effect is None

    set_reduce_motion(True)
    grid._update_drop_indicator(1)
    assert indicator.isVisible()
    assert indicator._fade.state() == QAbstractAnimation.State.Stopped
    assert indicator._opacity_effect is None
    grid._hide_drop_indicator()
    assert not indicator.isVisible()
    loader.close()


def test_r10d_skeleton_opacity_loop_gated(qtbot, isolated_settings):
    """R10d: skeleton uses InOutSine opacity loop; reduce-motion stays static."""
    from PyQt6.QtCore import QAbstractAnimation, QEasingCurve

    from pagedrop.ui.page_card import PageCard
    from pagedrop.ui.settings import set_reduce_motion

    set_reduce_motion(False)
    card = PageCard(0)
    qtbot.addWidget(card)
    card.show()
    card.start_skeleton_pulse()
    assert card._skeleton_pulse_anim is not None
    assert card._skeleton_pulse_anim.state() == QAbstractAnimation.State.Running
    assert card._skeleton_pulse_effect is not None
    up = card._skeleton_pulse_anim.animationAt(0)
    assert up.easingCurve().type() == QEasingCurve.Type.InOutSine
    assert 400 <= up.duration() <= 600
    card.clear_skeleton_pulse()
    assert card._skeleton_pulse_anim is None
    assert card._skeleton_pulse_effect is None

    set_reduce_motion(True)
    card.start_skeleton_pulse()
    assert card._skeleton_pulse_anim is None
    assert card._skeleton_pulse_effect is None


def test_r8_light_hc_parity_freeze(isolated_settings):
    """R8: dark/light/HC sheets share chrome roles; light status ink meets AA; HC thickens."""
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import (
        ACCENT,
        BG_CARD,
        BG_CARD_LIGHT,
        BG_GRID_LIGHT,
        CLOSE_TAB,
        FOCUS_RING,
        FOCUS_RING_LIGHT,
        CLOSE_TAB_LIGHT,
        STATUS_SUCCESS,
        STATUS_SUCCESS_LIGHT,
        STATUS_WARNING,
        STATUS_WARNING_LIGHT,
        TEXT_MUTED,
        TEXT_MUTED_LIGHT,
        TEXT_PRIMARY_LIGHT,
        VIEWER_PAGE_BG,
        chrome_card_qcolor,
        chrome_text_muted_qcolor,
        close_tab_hex,
        status_success_hex,
        status_warning_hex,
    )

    modes = (
        dict(light=False, high_contrast=False),
        dict(light=True, high_contrast=False),
        dict(light=False, high_contrast=True),
        dict(light=True, high_contrast=True),
    )
    roles = (
        "QPushButton#ToolbarPrimary",
        "QPushButton#ToolbarSecondary",
        "QFrame#PageCard",
        "QFrame#ToolTile",
        "ToastOverlayMessage",
        "QWidget#BusyOverlay",
        "QTabWidget#TabManager",
        "QWidget#ZoomControls",
        "QFrame#ToolShellDropZone",
        "QWidget#EmptyStatePanel",
    )
    sheets = {f"{m['light']}_{m['high_contrast']}": app_stylesheet(**m) for m in modes}
    for sheet in sheets.values():
        for role in roles:
            assert role in sheet
        assert VIEWER_PAGE_BG in sheet

    dark, light, dark_hc, light_hc = (
        sheets["False_False"],
        sheets["True_False"],
        sheets["False_True"],
        sheets["True_True"],
    )
    assert light != dark
    assert light_hc != light
    assert light_hc != dark_hc
    assert "border: 2px solid" in dark
    assert "border: 3px solid" in dark_hc
    assert f"border: 3px solid {FOCUS_RING}" in dark_hc
    assert f"border: 4px solid {ACCENT}" in dark_hc
    assert f"border: 3px solid {FOCUS_RING_LIGHT}" in light_hc
    assert f"border: 4px solid {ACCENT}" in light_hc
    assert TEXT_PRIMARY_LIGHT in light
    success_block = light.split('ToastOverlayMessage[kind="success"]')[1].split("}")[0]
    warning_block = light.split('ToastOverlayMessage[kind="warning"]')[1].split("}")[0]
    assert STATUS_SUCCESS_LIGHT in success_block
    assert STATUS_SUCCESS not in success_block
    assert STATUS_WARNING_LIGHT in warning_block
    assert STATUS_WARNING not in warning_block

    # Light toast / list status ink must hold AA on white and off-white chrome.
    for fg, bg in (
        (STATUS_SUCCESS_LIGHT, "#FFFFFF"),
        (STATUS_SUCCESS_LIGHT, BG_GRID_LIGHT),
        (STATUS_WARNING_LIGHT, "#FFFFFF"),
        (STATUS_WARNING_LIGHT, BG_GRID_LIGHT),
        (TEXT_MUTED_LIGHT, BG_GRID_LIGHT),
    ):
        assert contrast_ratio(fg, bg) >= 4.5

    # Paint helpers stay paired with stylesheet tokens after toggle.
    set_light_theme(True)
    assert chrome_card_qcolor().name().upper() == BG_CARD_LIGHT.upper()
    assert chrome_text_muted_qcolor().name().upper() == TEXT_MUTED_LIGHT.upper()
    assert status_success_hex() == STATUS_SUCCESS_LIGHT
    assert status_warning_hex() == STATUS_WARNING_LIGHT
    assert close_tab_hex() == CLOSE_TAB_LIGHT
    set_light_theme(False)
    assert chrome_card_qcolor().name().upper() == BG_CARD.upper()
    assert chrome_text_muted_qcolor().name().upper() == TEXT_MUTED.upper()
    assert status_success_hex() == STATUS_SUCCESS
    assert status_warning_hex() == STATUS_WARNING
    assert close_tab_hex() == CLOSE_TAB


# --- Toast: mouse only on the card, pause while hovered or focused ---------


class _PressRecorder:
    """Event filter that notes which widgets received a real mouse press."""

    def __init__(self, *widgets):
        from PyQt6.QtCore import QEvent, QObject

        outer = self

        class _Filter(QObject):
            def eventFilter(self, watched, event):  # noqa: N802
                if event.type() == QEvent.Type.MouseButtonPress:
                    outer.pressed.append(watched)
                return False

        self.pressed: list = []
        self._filter = _Filter()
        for widget in widgets:
            widget.installEventFilter(self._filter)


def _window_click(window, widget, pos):
    from PyQt6.QtTest import QTest

    point = widget.mapTo(window, pos)
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=point)


def _window_move(window, widget, pos):
    from PyQt6.QtTest import QTest

    QTest.mouseMove(window.windowHandle(), widget.mapTo(window, pos))


def _within(widget, candidate) -> bool:
    return candidate is widget or (
        candidate is not None and widget.isAncestorOf(candidate)
    )


def _loaded_main_window(qtbot, main_window, pdf):
    from tests.conftest import load_pdf_in_active_tab, wait_for_pdf_loaded

    main_window.resize(900, 700)
    main_window.show()
    qtbot.waitExposed(main_window)
    load_pdf_in_active_tab(main_window, str(pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    return main_window._thumbnail_grid, main_window._tab_manager, main_window._toast


def _grid_point(grid):
    return grid.viewport().rect().topLeft() + QPointF(12, 12).toPoint()


def _assert_mask_follows_card(tabs, toast, grid):
    """Over the card the card answers; a few pixels above it the grid does."""
    card = toast._card
    top = card.geometry().top()
    inside = card.mapTo(tabs, card.rect().center())
    just_above = card.mapTo(tabs, card.rect().topLeft()) - type(inside)(0, 4)
    assert top >= 0
    assert _within(card, tabs.childAt(inside))
    assert _within(grid, tabs.childAt(just_above))
    assert _within(grid, tabs.childAt(card.mapTo(tabs, card.rect().center()) - type(inside)(0, 200)))
    assert toast.mask().boundingRect() == card.geometry()


@pytest.mark.parametrize("reduce", [False, True])
def test_undo_toast_takes_mouse_on_its_card_only(
    qtbot, main_window, five_page_pdf, isolated_settings, reduce
):
    set_reduce_motion(reduce)
    grid, tabs, toast = _loaded_main_window(qtbot, main_window, five_page_pdf)
    undone: list[str] = []
    main_window._show_toast("Deleted 1 page", kind="undo", on_undo=lambda: undone.append("u"))

    # Right after show the slide may still be running; the mask must already match.
    _assert_mask_follows_card(tabs, toast, grid)
    if not reduce:
        from PyQt6.QtCore import QAbstractAnimation

        qtbot.waitUntil(
            lambda: toast._motion_anim.state() == QAbstractAnimation.State.Stopped,
            timeout=1000,
        )
        _assert_mask_follows_card(tabs, toast, grid)

    # A real click outside the card reaches the grid underneath.
    recorder = _PressRecorder(grid.viewport())
    _window_click(main_window, grid.viewport(), _grid_point(grid))
    assert recorder.pressed == [grid.viewport()]

    # The undo button on the card still works.
    assert toast._undo_button.isVisible()
    _window_click(main_window, toast._undo_button, toast._undo_button.rect().center())
    assert undone == ["u"]
    assert not toast.isVisible()


def test_toast_mask_tracks_the_slide(qtbot, main_window, five_page_pdf, isolated_settings):
    set_reduce_motion(False)
    grid, tabs, toast = _loaded_main_window(qtbot, main_window, five_page_pdf)
    main_window._show_toast("Deleted 1 page", kind="undo", on_undo=lambda: None)
    toast._motion_anim.stop()
    for t in (0.0, 0.5, 1.0):
        toast.motion_t = t
        _assert_mask_follows_card(tabs, toast, grid)
    # A point that is on the card at rest but below it when slid down.
    toast.motion_t = 0.0
    rest_top = toast._card.geometry().top()
    toast.motion_t = 1.0
    assert toast._card.geometry().top() > rest_top
    probe = toast._card.mapTo(tabs, toast._card.rect().topLeft())
    probe.setY(probe.y() - 2)
    assert _within(grid, tabs.childAt(probe))


@pytest.mark.parametrize("kind", ["info", "success", "error"])
def test_plain_toast_clicks_outside_card_reach_the_grid(
    qtbot, main_window, five_page_pdf, isolated_settings, kind
):
    set_reduce_motion(True)
    grid, tabs, toast = _loaded_main_window(qtbot, main_window, five_page_pdf)
    main_window._show_toast("Saved", kind=kind)
    assert not toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    _assert_mask_follows_card(tabs, toast, grid)

    recorder = _PressRecorder(grid.viewport())
    _window_click(main_window, grid.viewport(), _grid_point(grid))
    assert recorder.pressed == [grid.viewport()]


@pytest.fixture
def toast_host(qtbot, isolated_settings):
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.busy_overlay import ToastOverlay

    set_reduce_motion(True)
    host = QWidget()
    qtbot.addWidget(host)
    host.setStyleSheet(app_stylesheet())
    host.resize(500, 300)
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    return host, ToastOverlay(host)


def test_toast_pauses_while_hovered_and_resumes_with_remaining_time(qtbot, toast_host):
    host, toast = toast_host
    timeout_ms = 200
    shown = time.monotonic()
    toast.show_toast("Saved", timeout_ms=timeout_ms)
    away = host.rect().topLeft() + QPointF(5, 5).toPoint()
    _window_move(host, host, away)
    _window_move(host, toast._card, toast._card.rect().center())
    qtbot.waitUntil(lambda: toast._paused, timeout=5000)
    assert toast.isVisible()

    # Held well past the original timeout: still up and still paused.
    margin = 0.5
    qtbot.waitUntil(
        lambda: time.monotonic() - shown > timeout_ms / 1000 + margin, timeout=10000
    )
    assert toast.isVisible()
    assert toast._paused
    assert not toast._timer.isActive()

    _window_move(host, host, away)
    qtbot.waitUntil(lambda: toast._timer.isActive(), timeout=5000)
    assert not toast._paused
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=10000)


def test_toast_resume_keeps_a_floor_when_little_time_was_left(qtbot, toast_host):
    host, toast = toast_host
    toast.show_toast("Saved", timeout_ms=60)
    _window_move(host, host, QPointF(5, 5).toPoint())
    _window_move(host, toast._card, toast._card.rect().center())
    qtbot.waitUntil(lambda: toast._paused, timeout=1000)
    assert toast._remaining_ms >= 500
    _window_move(host, host, QPointF(5, 5).toPoint())
    qtbot.waitUntil(lambda: toast._timer.isActive(), timeout=1000)
    assert toast._timer.remainingTime() > 400


def test_toast_pauses_while_undo_button_has_focus(qtbot, toast_host):
    host, toast = toast_host
    toast.show_toast("Deleted", kind="undo", timeout_ms=1500, on_undo=lambda: None)
    qtbot.waitUntil(host.isActiveWindow, timeout=2000)
    toast._undo_button.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(lambda: not toast._timer.isActive(), timeout=1000)
    assert toast._paused
    assert toast.isVisible()

    host.setFocus(Qt.FocusReason.OtherFocusReason)
    toast._undo_button.clearFocus()
    qtbot.waitUntil(lambda: toast._timer.isActive(), timeout=1000)
    assert not toast._paused
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=3000)


def test_new_toast_clears_a_stale_pause(qtbot, toast_host):
    host, toast = toast_host
    toast.show_toast("First", timeout_ms=1500)
    _window_move(host, host, QPointF(5, 5).toPoint())
    _window_move(host, toast._card, toast._card.rect().center())
    qtbot.waitUntil(lambda: toast._paused, timeout=1000)

    # Pointer leaves while the toast is hidden, so no Leave reaches the card.
    toast.hide()
    assert not toast._paused
    _window_move(host, host, QPointF(5, 5).toPoint())
    toast.show_toast("Second", timeout_ms=1500)
    assert not toast._paused
    assert toast._timer.isActive()


def test_toast_shown_under_the_pointer_waits(qtbot, toast_host):
    host, toast = toast_host
    toast.show_toast("First", timeout_ms=1500)
    centre = toast._card.mapTo(host, toast._card.rect().center())
    toast.hide()
    from PyQt6.QtGui import QCursor

    original = QCursor.pos()
    try:
        QCursor.setPos(host.mapToGlobal(centre))
        toast.show_toast("Second", timeout_ms=1500)
        qtbot.waitUntil(lambda: toast._paused, timeout=1000)
        assert not toast._timer.isActive()
        assert toast.isVisible()
    finally:
        QCursor.setPos(original)


def test_hover_during_exit_is_ignored(qtbot, isolated_settings):
    from PyQt6.QtWidgets import QWidget

    from pagedrop.ui.busy_overlay import ToastOverlay

    set_reduce_motion(False)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(500, 300)
    host.show()
    qtbot.waitExposed(host)
    toast = ToastOverlay(host)
    toast.show_toast("Saved", timeout_ms=30)
    qtbot.waitUntil(lambda: toast._exiting, timeout=2000)
    _window_move(host, toast._card, toast._card.rect().center())
    assert not toast._paused
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=2000)


# --- Focus ring: contrast, window controls, item views, swatch -------------

_LIGHT_SURFACES = {
    "BG_BASE_LIGHT": "#F7F8FA",
    "BG_CARD_LIGHT": "#FFFFFF",
    "BG_GRID_LIGHT": "#F0F1F4",
    "card hover": "#EEF0F4",
    "empty thumbnail / pressed": "#E2E4EA",
}

_STYLE_MODES = (
    dict(light=False, high_contrast=False),
    dict(light=True, high_contrast=False),
    dict(light=False, high_contrast=True),
    dict(light=True, high_contrast=True),
)


def _ring_for(light: bool) -> str:
    from pagedrop.ui.theme import FOCUS_RING, FOCUS_RING_LIGHT

    return FOCUS_RING_LIGHT if light else FOCUS_RING


def _focus_surfaces(light: bool) -> dict[str, str]:
    from pagedrop.ui import theme

    if light:
        return _LIGHT_SURFACES
    names = (
        "BG_BASE",
        "BG_SURFACE",
        "BG_GRID",
        "BG_CARD",
        "BG_CARD_HOVER",
        "BG_TOOLBAR",
        "BG_STATUS",
        "BG_TAB_BAR",
        "BG_PREVIEW_FOOTER",
    )
    surfaces = {name: getattr(theme, name) for name in names}
    surfaces["empty thumbnail"] = "#2A2A32"
    return surfaces




@pytest.mark.parametrize("light", [False, True])
def test_focus_ring_meets_3_to_1_on_every_surface(light):
    ring = _ring_for(light)
    for name, surface in _focus_surfaces(light).items():
        assert contrast_ratio(ring, surface) >= 3.0, (name, surface, ring)


@pytest.mark.parametrize("mode", _STYLE_MODES)
def test_focus_rules_use_ring_token_not_accent(mode):
    """Every :focus border uses the ring token; ACCENT only fills or primary buttons."""
    import re

    from pagedrop.ui.theme import ACCENT

    sheet = re.sub(r"/\*.*?\*/", "", app_stylesheet(**mode), flags=re.S)
    ring = _ring_for(mode["light"])
    # Primary buttons and selected items sit on an ACCENT fill; they use ink instead.
    allowed_accent = ("ToolbarPrimary", "::handle", "::item:selected:focus")
    seen = 0
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
        if ":focus" not in selector:
            continue
        borders = [
            line
            for line in body.splitlines()
            if line.strip().startswith("border") and "none" not in line
        ]
        if not borders:
            continue
        if any(token in selector for token in allowed_accent):
            continue
        seen += 1
        assert all(ACCENT not in line for line in borders), selector.strip()
        assert any(ring in line for line in borders), selector.strip()
    assert seen > 20
    assert ring in sheet.split("QLabel#PageCardFocusRing")[1].split("}")[0]


@pytest.fixture
def themed_app(qtbot, isolated_settings):
    app = QApplication.instance()
    assert app is not None
    previous = app.styleSheet()

    def apply(**mode):
        app.setStyleSheet(app_stylesheet(**mode))

    yield apply
    app.setStyleSheet(previous)


def _color_count(widget, hex_color: str) -> int:
    from PyQt6.QtGui import QColor

    img = widget.grab().toImage()
    target = QColor(hex_color).rgb()
    return sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if img.pixelColor(x, y).rgb() == target
    )


def _focus(qtbot, widget) -> None:
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(widget.hasFocus, timeout=1000)
    QApplication.processEvents()


def _show(qtbot, widget) -> None:
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)


@pytest.mark.parametrize("mode", _STYLE_MODES)
def test_window_control_buttons_show_focus_without_resizing(
    qtbot, main_window, themed_app, mode
):
    themed_app(**mode)
    ring = _ring_for(mode["light"])
    _show(qtbot, main_window)
    buttons = main_window._window_control_buttons
    assert {b.objectName() for b in buttons} == {
        "WindowMinimize",
        "WindowMaximize",
        "WindowClose",
    }
    for button in buttons:
        button.clearFocus()
        QApplication.processEvents()
        size = button.size()
        assert _color_count(button, ring) == 0
        _focus(qtbot, button)
        assert button.size() == size
        assert _color_count(button, ring) >= 40, button.objectName()


def test_window_close_keeps_hover_treatment_while_focused(
    qtbot, main_window, themed_app
):
    from PyQt6.QtGui import QColor

    from pagedrop.ui.theme import CLOSE_TAB_HOVER_BG, FOCUS_RING

    themed_app()
    _show(qtbot, main_window)
    close = next(
        b for b in main_window._window_control_buttons if b.objectName() == "WindowClose"
    )
    _focus(qtbot, close)
    close.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    close.update()
    img = close.grab().toImage()
    inner = img.pixelColor(img.width() // 2, 4)
    assert inner == QColor(CLOSE_TAB_HOVER_BG)
    assert _color_count(close, FOCUS_RING) >= 40


@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("tool", "NewTabButton"),
        ("tool", "ChromeToggleButton"),
        ("tool", "OpenTabsButton"),
        ("tool", "WindowClose"),
        ("push", "MoveUndoButton"),
        ("push", "ZoomButton"),
        ("push", "ToastOverlayUndo"),
        ("tool", "ToolsUpcomingToggle"),
    ],
)
def test_chrome_buttons_show_visible_focus(qtbot, themed_app, light, kind, name):
    from PyQt6.QtWidgets import QPushButton

    themed_app(light=light)
    ring = _ring_for(light)
    host = QWidget()
    layout = QVBoxLayout(host)
    button = (QToolButton if kind == "tool" else QPushButton)()
    button.setText("+")
    button.setObjectName(name)
    other = QPushButton("other")
    layout.addWidget(button)
    layout.addWidget(other)
    _show(qtbot, host)
    other.setFocus()
    QApplication.processEvents()
    assert _color_count(button, ring) == 0
    _focus(qtbot, button)
    assert _color_count(button, ring) >= 20


@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("kind", ["list", "tree"])
def test_item_views_show_the_current_item_when_focused(
    qtbot, themed_app, light, selected, kind
):
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

    themed_app(light=light)
    ring = _ring_for(light)
    expected = ("#000000" if light else "#FFFFFF") if selected else ring
    if kind == "list":
        view = QListWidget()
        view.addItems(["one", "two", "three"])
        item = view.item(1)
    else:
        view = QTreeWidget()
        view.setHeaderHidden(True)
        for label in ("a", "b", "c"):
            QTreeWidgetItem(view, [label])
        item = view.topLevelItem(1)
    view.resize(220, 160)
    host = QWidget()
    layout = QVBoxLayout(host)
    field = QLineEdit()
    layout.addWidget(field)
    layout.addWidget(view)
    _show(qtbot, host)
    view.setCurrentItem(item)
    item.setSelected(selected)

    def edge_pixel() -> QColor:
        rect = view.visualItemRect(item)
        img = view.viewport().grab().toImage()
        return img.pixelColor(rect.left() + 1, rect.center().y())

    _focus(qtbot, field)
    assert not view.hasFocus()
    assert edge_pixel() != QColor(expected)
    size = view.visualItemRect(item).size()
    _focus(qtbot, view)
    assert edge_pixel() == QColor(expected)
    assert view.visualItemRect(item).size() == size


def test_selected_item_focus_ring_contrasts_with_accent_fill():
    from pagedrop.ui.theme import ACCENT

    assert contrast_ratio("#FFFFFF", ACCENT) >= 3.0
    assert contrast_ratio("#000000", ACCENT) >= 3.0


@pytest.mark.parametrize(
    "fill", ["#000000", "#FFFFFF", "#8C8C8C", "#FFFF00", "#00008B"]
)
def test_watermark_swatch_label_is_readable_and_focus_ring_visible(
    qtbot, themed_app, fill
):
    import re

    from PyQt6.QtWidgets import QPushButton

    from pagedrop.ui.modify_tools_shell import _color_swatch_style

    themed_app()
    style = _color_swatch_style(fill)
    ink = re.search(r"; color: (#[0-9A-F]{6});", style).group(1)
    assert ink in ("#000000", "#FFFFFF")
    other = "#FFFFFF" if ink == "#000000" else "#000000"
    assert contrast_ratio(ink, fill) >= contrast_ratio(other, fill)
    assert contrast_ratio(ink, fill) >= 4.5

    host = QWidget()
    layout = QVBoxLayout(host)
    swatch = QPushButton(fill)
    swatch.setObjectName("ToolbarSecondary")
    swatch.setFixedWidth(88)
    swatch.setStyleSheet(style)
    sibling = QPushButton("other")
    layout.addWidget(swatch)
    layout.addWidget(sibling)
    _show(qtbot, host)
    sibling.setFocus()
    QApplication.processEvents()
    ring = _ring_for(False)
    assert _color_count(swatch, ring) == 0
    _focus(qtbot, swatch)
    assert _color_count(swatch, ring) >= 40


def test_watermark_swatch_ring_follows_theme(isolated_settings):
    from pagedrop.ui.modify_tools_shell import _color_swatch_style
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import FOCUS_RING, FOCUS_RING_LIGHT, focus_ring_hex

    assert focus_ring_hex() == FOCUS_RING
    assert f"2px solid {FOCUS_RING}" in _color_swatch_style("#8C8C8C")
    set_light_theme(True)
    assert focus_ring_hex() == FOCUS_RING_LIGHT
    assert f"2px solid {FOCUS_RING_LIGHT}" in _color_swatch_style("#8C8C8C")


def test_watermark_swatch_uses_high_contrast_width(monkeypatch):
    from pagedrop.ui import modify_tools_shell

    monkeypatch.setattr(modify_tools_shell, "prefers_high_contrast", lambda: True)
    assert "3px solid" in modify_tools_shell._color_swatch_style("#8C8C8C")


# --- Platform contrast preference -----------------------------------------


class _StubHints:
    def __init__(self, preference):
        self._preference = preference

    def contrastPreference(self):  # noqa: N802
        return self._preference


def test_prefers_high_contrast_follows_platform_preference(monkeypatch):
    from pagedrop.ui import accessibility

    monkeypatch.setattr(
        accessibility,
        "_accessibility_hints",
        lambda: _StubHints(Qt.ContrastPreference.HighContrast),
    )
    assert accessibility.prefers_high_contrast() is True


def test_prefers_high_contrast_ignores_a_high_contrast_palette(monkeypatch):
    from PyQt6.QtGui import QColor, QPalette

    from pagedrop.ui import accessibility

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Window, QColor("#000000"))
    previous = QApplication.palette()
    QApplication.setPalette(palette)
    try:
        monkeypatch.setattr(
            accessibility,
            "_accessibility_hints",
            lambda: _StubHints(Qt.ContrastPreference.NoPreference),
        )
        assert accessibility.prefers_high_contrast() is False
    finally:
        QApplication.setPalette(previous)
