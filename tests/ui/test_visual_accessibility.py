"""Visual & platform accessibility — contrast, motion, focus, labels."""

from __future__ import annotations

import re
import time

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLineEdit,
    QLabel,
    QListWidget,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.ui.accessibility import contrast_ratio, prefers_reduce_motion
from pagedrop.ui.base_file_card import BaseFileCard
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.page_card import PageCard
from pagedrop.ui.preferences_dialog import PreferencesDialog
from pagedrop.ui.settings import reduce_motion, set_reduce_motion
from pagedrop.ui.theme import BG_BASE, TEXT_MUTED, app_stylesheet, tabular_font
from pagedrop.ui.tool_page import StatusFooter
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
        DARK,
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
    assert (PRIMARY, ON_PRIMARY) == (DARK.ink, DARK.on_ink)
    assert TEXT_ON_ACCENT == ON_PRIMARY
    assert DOCUMENT_CANVAS == SURFACE_DOCUMENT_CANVAS
    assert RAISED_SURFACE == SURFACE_RAISED
    assert (COMPACT_CONTROL_HEIGHT, FORM_CONTROL_HEIGHT) == (32, 36)
    assert (ICON_SIZE_SMALL, ICON_SIZE) == (16, 18)
    assert (RADIUS_CONTROL, RADIUS_SURFACE) == (4, 6)

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
    assert "QToolButton:checked:focus" in sheet
    assert "QPushButton:disabled" in sheet
    assert 'QPushButton[destructive="true"]:pressed' in sheet
    assert 'QPushButton[destructive="true"]:focus' in sheet
    assert 'QPushButton[destructive="true"]:disabled' in sheet
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
    for control in (
        "QLineEdit",
        "QComboBox",
        "QSpinBox",
        "QDoubleSpinBox",
        "QTextEdit",
        "QPlainTextEdit",
    ):
        assert f"{control}:hover:!focus:enabled" in sheet
        assert f"{control}:disabled" in sheet
        assert f'{control}[error="true"]' in sheet
    assert "QTextBrowser:disabled" in sheet
    assert "invalid" not in sheet


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
    from pagedrop.ui.theme import (
        FOCUS_RING,
        FOCUS_RING_LIGHT,
        PAGE_INK,
        SURFACE_PAPER,
        rgba,
    )

    dark = app_stylesheet()
    light = app_stylesheet(light=True)

    # Chips sit on page-paper thumbnails: a page-ink pill with paper text.
    dark_chip = rgba(PAGE_INK, 160)
    light_chip = rgba(PAGE_INK, 170)

    for sheet, chip_bg, ring in (
        (dark, dark_chip, FOCUS_RING),
        (light, light_chip, FOCUS_RING_LIGHT),
    ):
        page = sheet.split("QLabel#PageCardPageOverlay")[1].split("}")[0]
        rot = sheet.split("QLabel#PageCardRotationOverlay")[1].split("}")[0]
        assert chip_bg in page
        assert chip_bg in rot
        assert SURFACE_PAPER in page
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
    from pagedrop.ui.theme import DARK, LIGHT, app_stylesheet
    from pagedrop.ui.thumbnail_grid import ThumbnailGrid

    for sheet, theme in (
        (app_stylesheet(), DARK),
        (app_stylesheet(light=True), LIGHT),
    ):
        empty = sheet.split("QWidget#EmptyStatePanel {")[1].split(
            "QWidget#EmptyStatePanel[dropActive"
        )[0]
        assert "border: 1px dashed" in empty
        assert 'QWidget#EmptyStatePanel[dropActive="true"]' in sheet
        assert f"border-color: {theme.ink}" in sheet.split(
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
    from pagedrop.ui.theme import LIGHT

    light = app_stylesheet(light=True)
    assert LIGHT.chrome in light
    assert "QDialog {" in light
    assert "QListWidget::item:selected" in light
    assert "QTreeWidget::item:selected" in light
    assert "QTabWidget#PdfViewerSide::pane" in light
    # Viewer QToolButtons sit outside QToolBar — must still get light ink.
    assert "QToolButton," in light
    assert f"color: {LIGHT.text}" in light
    assert f"background-color: {LIGHT.raised}" in light
    assert "QFrame#WatermarkOptionsCard" in light
    assert "QPushButton#ToolbarPrimary" in light


def test_r3_toolbar_default_is_flat():
    """R3: default tool buttons are transparent/hairline, not dense bordered cards."""
    from pagedrop.ui.theme import DARK, LIGHT

    for sheet, theme in ((app_stylesheet(), DARK), (app_stylesheet(light=True), LIGHT)):
        block = sheet.split("QToolButton,")[1].split("QToolButton:hover,")[0]
        assert "transparent" in block
        assert "border: 1px solid transparent" in block
        # Primary fill still uses accent; default tools must not.
        assert theme.ink not in block


def test_r3_primary_label_meets_wcag_aa_on_accent():
    """R3: on_ink on ink fill/hover/pressed ≥ 4.5:1 in both themes."""
    from pagedrop.ui.theme import DARK, LIGHT

    for sheet, theme in ((app_stylesheet(), DARK), (app_stylesheet(light=True), LIGHT)):
        for bg in (theme.ink, theme.ink_hover, theme.ink_pressed):
            assert contrast_ratio(theme.on_ink, bg) >= 4.5
        # Primary QSS still wires the on-ink colour onto the ink fill.
        primary = sheet.split("QPushButton#ToolbarPrimary,")[1].split(
            "QPushButton#ToolbarPrimary:hover"
        )[0]
        assert theme.ink in primary
        assert theme.on_ink in primary


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


def test_theme_smoke_light_dark_and_high_contrast(qapp, isolated_settings, monkeypatch):
    """O8: tokens + objectName chrome present in dark, light, and HC sheets."""
    from pagedrop.ui.theme import (
        DARK,
        LIGHT,
        STATUS_SUCCESS,
        STATUS_SUCCESS_LIGHT,
        STATUS_WARNING,
        STATUS_WARNING_LIGHT,
        VIEWER_PAGE_BG,
        token_qcolor,
    )

    dark = app_stylesheet()
    light = app_stylesheet(light=True)
    high = app_stylesheet(high_contrast=True)

    for sheet, theme, success, warning in (
        (dark, DARK, STATUS_SUCCESS, STATUS_WARNING),
        (light, LIGHT, STATUS_SUCCESS_LIGHT, STATUS_WARNING_LIGHT),
        (high, DARK, STATUS_SUCCESS, STATUS_WARNING),
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
        assert f"color: {theme.on_ink}" in sheet
        # Success toast must not fall back to accent blue.
        assert 'ToastOverlayMessage[kind="success"]' in sheet
        success_block = sheet.split('ToastOverlayMessage[kind="success"]')[1].split("}")[0]
        assert success in success_block
        assert theme.ink.lstrip("#") not in success_block

    assert high != dark
    assert "border: 3px solid" in high
    assert STATUS_SUCCESS.startswith("#")
    assert STATUS_WARNING.startswith("#")
    assert token_qcolor(STATUS_SUCCESS, 90).alpha() == 90

    # The theme switch end to end: choice -> stylesheet -> current_theme().
    from pagedrop.ui import accessibility, settings
    from pagedrop.ui.theme import current_theme
    from tests.ui.test_user_preferences import _stub_color_scheme

    previous_sheet = qapp.styleSheet()
    try:
        for choice, theme in (("light", LIGHT), ("dark", DARK)):
            settings.set_appearance(choice)
            accessibility.refresh_themed_widgets(qapp)
            assert current_theme() is theme
            assert theme.chrome in qapp.styleSheet()
            assert theme.text in qapp.styleSheet()

        settings.set_appearance("system")
        sheets = []
        for scheme, theme in ((Qt.ColorScheme.Light, LIGHT), (Qt.ColorScheme.Dark, DARK)):
            _stub_color_scheme(monkeypatch, scheme)
            accessibility._on_color_scheme_changed()
            assert current_theme() is theme
            assert theme.chrome in qapp.styleSheet()
            sheets.append(qapp.styleSheet())
        assert sheets[0] != sheets[1]
    finally:
        qapp.setStyleSheet(previous_sheet)


def test_toolbar_secondary_is_ghost_not_primary():
    """R1: #ToolbarSecondary is outline/ghost, distinct from filled primary (dark+light)."""
    from pagedrop.ui.theme import DARK, LIGHT

    for sheet, theme in ((app_stylesheet(), DARK), (app_stylesheet(light=True), LIGHT)):
        assert "QPushButton#ToolbarSecondary" in sheet
        assert "QToolBar QToolButton#ToolbarSecondary" in sheet
        secondary = sheet.split("QPushButton#ToolbarSecondary,")[1].split(
            "QPushButton#ToolbarSecondary:hover"
        )[0]
        assert "transparent" in secondary
        assert theme.ink not in secondary
        assert f"color: {theme.text}" in secondary
        primary = sheet.split("QPushButton#ToolbarPrimary,")[1].split(
            "QPushButton#ToolbarPrimary:hover"
        )[0]
        assert theme.ink in primary
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


def test_watermark_selection_chrome_uses_accent_token(isolated_settings):
    """O14: chrome paint helpers follow the theme ink; page marks stay on the light ink."""
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import (
        DARK,
        LIGHT,
        accent_qcolor,
        on_accent_qcolor,
        page_accent_qcolor,
    )

    def hex_of(color) -> str:
        return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"

    for light, theme in ((False, DARK), (True, LIGHT)):
        set_light_theme(light)
        assert hex_of(accent_qcolor()) == theme.ink
        assert hex_of(on_accent_qcolor()) == theme.on_ink
        # The page behind handles and selections is white in both themes.
        assert hex_of(page_accent_qcolor()) == LIGHT.ink


def test_r2_fonts_and_spacing_tokens():
    """Bundled UI font stack leads with Public Sans; spacing scale feeds toolbar/grid chrome."""
    from pagedrop.ui.theme import (
        CARD_PADDING,
        FONT_UI,
        SPACE_2,
        SPACE_3,
        SPACE_4,
    )

    assert FONT_UI == '"Public Sans", "Segoe UI", "Noto Sans", sans-serif'
    # Do not expand beyond the bundled face and its fallbacks.
    assert "Ubuntu" not in FONT_UI
    assert "SF Pro" not in FONT_UI

    assert CARD_PADDING == SPACE_4 == 16
    assert SPACE_3 == 12
    sheet = app_stylesheet()
    assert FONT_UI in sheet
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
    from pagedrop.ui.theme import DARK, LIGHT, app_stylesheet

    dark = app_stylesheet()
    light = app_stylesheet(light=True)
    high = app_stylesheet(high_contrast=True)

    for sheet, theme in ((dark, DARK), (light, LIGHT), (high, DARK)):
        assert "QTabWidget#TabManager > QTabBar::tab:selected" in sheet
        selected = sheet.split("QTabWidget#TabManager > QTabBar::tab:selected")[
            1
        ].split("QTabWidget#TabManager > QTabBar::tab:hover")[0]
        assert f"border-bottom: 2px solid {theme.ink}" in selected
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
        BG_CARD,
        BG_CARD_LIGHT,
        DARK,
        LIGHT,
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
    assert f"border: 4px solid {DARK.ink}" in dark_hc
    assert f"border: 3px solid {FOCUS_RING_LIGHT}" in light_hc
    assert f"border: 4px solid {LIGHT.ink}" in light_hc
    assert TEXT_PRIMARY_LIGHT in light
    success_block = light.split('ToastOverlayMessage[kind="success"]')[1].split("}")[0]
    warning_block = light.split('ToastOverlayMessage[kind="warning"]')[1].split("}")[0]
    assert STATUS_SUCCESS_LIGHT in success_block
    assert STATUS_SUCCESS not in success_block
    assert STATUS_WARNING_LIGHT in warning_block
    assert STATUS_WARNING not in warning_block

    # Light toast / list status ink must hold AA on every light surface it can
    # sit on.
    for fg, bg in (
        (STATUS_SUCCESS_LIGHT, LIGHT.raised),
        (STATUS_SUCCESS_LIGHT, LIGHT.chrome),
        (STATUS_SUCCESS_LIGHT, LIGHT.canvas),
        (STATUS_WARNING_LIGHT, LIGHT.raised),
        (STATUS_WARNING_LIGHT, LIGHT.chrome),
        (STATUS_WARNING_LIGHT, LIGHT.canvas),
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
    """Every surface a focus ring can sit on, read from the theme."""
    from pagedrop.ui.theme import DARK, LIGHT

    theme = LIGHT if light else DARK
    return {
        "chrome": theme.chrome,
        "raised": theme.raised,
        "canvas": theme.canvas,
        "bar_top": theme.bar_top,
        "bar_tabs": theme.bar_tabs,
        "hover (ink_tint)": theme.ink_tint,
        "pressed / empty thumbnail (line)": theme.line,
    }


@pytest.mark.parametrize("light", [False, True])
def test_focus_ring_meets_3_to_1_on_every_surface(light):
    ring = _ring_for(light)
    for name, surface in _focus_surfaces(light).items():
        assert contrast_ratio(ring, surface) >= 3.0, (name, surface, ring)


@pytest.mark.parametrize("mode", _STYLE_MODES)
def test_focus_rules_use_ring_token_not_accent(mode):
    """Every :focus border uses the ring token; ACCENT only fills or primary buttons."""
    import re

    from pagedrop.ui.theme import DARK, LIGHT

    ink = (LIGHT if mode["light"] else DARK).ink
    sheet = re.sub(r"/\*.*?\*/", "", app_stylesheet(**mode), flags=re.S)
    ring = _ring_for(mode["light"])
    # Primary buttons and selected items sit on an ACCENT fill; they use ink instead.
    allowed_accent = ("ToolbarPrimary", "::handle", "::item:selected:focus", ":default:focus")
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
        assert all(ink not in line for line in borders), selector.strip()
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
        # The ring shares the text colour, so count what focus adds.
        resting = _color_count(button, ring)
        _focus(qtbot, button)
        assert button.size() == size
        assert _color_count(button, ring) >= resting + 40, button.objectName()


def test_window_close_keeps_hover_treatment_while_focused(
    qtbot, main_window, themed_app
):
    from PyQt6.QtGui import QColor

    from pagedrop.ui.theme import DARK, FOCUS_RING, blend

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
    assert inner == QColor(blend(DARK.danger, DARK.bar_top, 0.14))
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
    # The ring shares the text colour, so count what focus adds.
    resting = _color_count(button, ring)
    _focus(qtbot, button)
    assert _color_count(button, ring) >= resting + 20


@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("kind", ["list", "tree"])
def test_item_views_show_the_current_item_when_focused(
    qtbot, themed_app, light, selected, kind
):
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

    from pagedrop.ui.theme import DARK, LIGHT

    themed_app(light=light)
    ring = _ring_for(light)
    expected = (LIGHT if light else DARK).on_ink if selected else ring
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


@pytest.mark.parametrize("light", [False, True])
def test_selected_item_focus_ring_contrasts_with_accent_fill(light):
    from pagedrop.ui.theme import DARK, LIGHT

    theme = LIGHT if light else DARK
    # A focused selected item draws its ring in the on-ink colour.
    assert contrast_ratio(theme.on_ink, theme.ink) >= 3.0


def _swatch_button(fill: str):
    from pagedrop.ui.modify_tools_shell import _ColorSwatchButton

    swatch = _ColorSwatchButton()
    swatch.setObjectName("ToolbarSecondary")
    swatch.set_fill(fill)
    return swatch


@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize(
    "fill", ["#000000", "#FFFFFF", "#8C8C8C", "#FFFF00", "#00008B"]
)
def test_watermark_swatch_shows_colour_square_and_focus_ring(
    qtbot, themed_app, fill, light
):
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QPushButton

    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import DARK, LIGHT

    theme = LIGHT if light else DARK
    set_light_theme(light)
    themed_app(light=light)
    host = QWidget()
    layout = QVBoxLayout(host)
    swatch = _swatch_button(fill)
    sibling = QPushButton("other")
    layout.addWidget(swatch)
    layout.addWidget(sibling)
    _show(qtbot, host)

    # The chosen colour is a square in the icon; the button is not inline-styled.
    assert not swatch.styleSheet()
    assert swatch.text() == fill
    pix = swatch.icon().pixmap(swatch.iconSize())
    img = pix.toImage()
    assert img.pixelColor(pix.width() // 2, pix.height() // 2) == QColor(fill)
    assert img.pixelColor(0, 0) == QColor(theme.line_strong)

    sibling.setFocus()
    QApplication.processEvents()
    ring = _ring_for(light)
    resting = _color_count(swatch, ring)
    _focus(qtbot, swatch)
    assert _color_count(swatch, ring) >= resting + 40


def test_watermark_swatch_is_wide_enough_for_icon_and_label(qtbot, themed_app):
    themed_app(light=False)
    host = QWidget()
    layout = QVBoxLayout(host)
    swatch = _swatch_button("#8C8C8C")
    layout.addWidget(swatch)
    _show(qtbot, host)

    assert swatch.width() >= swatch.sizeHint().width()
    text_width = swatch.fontMetrics().horizontalAdvance(swatch.text())
    assert swatch.width() >= text_width + swatch.iconSize().width()


def test_watermark_swatch_edge_follows_theme_change(qtbot, isolated_settings):
    from PyQt6.QtGui import QColor

    from pagedrop.ui.accessibility import refresh_themed_widgets
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import DARK, LIGHT

    swatch = _swatch_button("#8C8C8C")
    qtbot.addWidget(swatch)
    for light, theme in ((False, DARK), (True, LIGHT), (False, DARK)):
        set_light_theme(light)
        refresh_themed_widgets()
        img = swatch.icon().pixmap(swatch.iconSize()).toImage()
        assert img.pixelColor(0, 0) == QColor(theme.line_strong)
        assert img.pixelColor(8, 8) == QColor("#8C8C8C")


def test_watermark_swatch_ring_is_wider_in_high_contrast(qtbot, themed_app):
    from PyQt6.QtWidgets import QPushButton

    host = QWidget()
    layout = QVBoxLayout(host)
    swatch = _swatch_button("#8C8C8C")
    sibling = QPushButton("other")
    layout.addWidget(swatch)
    layout.addWidget(sibling)
    _show(qtbot, host)
    ring = _ring_for(False)
    counts = {}
    for high_contrast in (False, True):
        themed_app(light=False, high_contrast=high_contrast)
        sibling.setFocus()
        QApplication.processEvents()
        resting = _color_count(swatch, ring)
        _focus(qtbot, swatch)
        counts[high_contrast] = _color_count(swatch, ring) - resting
    assert counts[True] > counts[False] >= 40


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


_TNUM = QFont.Tag("tnum")

# (font-size px, font-weight): page title, section title, panel title,
# body, label, caption.
_TYPE_SCALE = {(22, 600), (18, 600), (15, 600), (13, 400), (13, 500), (13, 600), (12, 400)}


def test_tabular_font_sets_tnum_without_pinning_size():
    font = tabular_font()
    assert font.isFeatureSet(_TNUM)
    assert font.featureValue(_TNUM) == 1
    # Nothing but the feature is pinned, so the style sheet keeps size control.
    assert font.pixelSize() == -1
    assert not font.bold()

    base = QFont()
    base.setPixelSize(17)
    derived = tabular_font(base)
    assert derived.isFeatureSet(_TNUM)
    assert derived.pixelSize() == 17
    assert not base.isFeatureSet(_TNUM)


def test_tabular_font_survives_app_stylesheet_reapply(qtbot):
    app = QApplication.instance()
    previous = app.styleSheet()
    label = QLabel("1,234")
    qtbot.addWidget(label)
    label.setFont(tabular_font())
    try:
        for light in (False, True, False):
            app.setStyleSheet(app_stylesheet(light=light))
            label.ensurePolished()
            assert label.font().isFeatureSet(_TNUM)
            assert label.font().pixelSize() == 13
    finally:
        app.setStyleSheet(previous)


def test_tabular_font_applied_to_numeric_displays(qtbot, main_window):
    from pagedrop.ui.page_card import drag_badge_font
    from pagedrop.ui.pdf_viewer import PdfViewerWidget
    from pagedrop.ui.tools_window import ToolsWindow

    badge = drag_badge_font()
    assert badge.isFeatureSet(_TNUM)
    assert badge.pixelSize() == 13

    for label in (main_window._selection_toolbar_label, main_window._selection_status):
        assert label.font().isFeatureSet(_TNUM)

    viewer = PdfViewerWidget()
    qtbot.addWidget(viewer)
    for widget in (viewer._page_edit, viewer._zoom_button, viewer._hit_label):
        assert widget.font().isFeatureSet(_TNUM)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    assert tools._match_label.font().isFeatureSet(_TNUM)

    card = PageCard(0)
    qtbot.addWidget(card)
    for widget in (card._page_overlay, card._rotation_overlay, card._page_label):
        assert widget.font().isFeatureSet(_TNUM)

    zoom = ZoomControls(min_width=80, max_width=480, step=16, initial=160)
    qtbot.addWidget(zoom)
    assert zoom._value_label.font().isFeatureSet(_TNUM)
    zoom.show()
    zoom._value_label.setText("1000px")
    metrics = zoom._value_label.fontMetrics()
    assert metrics.horizontalAdvance("1000px") <= zoom._value_label.width()

    merge_card = MergeFileCard(0, "/tmp/a.pdf", 1)
    qtbot.addWidget(merge_card)
    assert merge_card._subtitle_label.font().isFeatureSet(_TNUM)

    footer = StatusFooter()
    qtbot.addWidget(footer)
    assert footer.font().isFeatureSet(_TNUM)


def _qss_rules(sheet: str):
    sheet = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", sheet):
        yield " ".join(match.group(1).split()), match.group(2)


@pytest.mark.parametrize(
    ("light", "high_contrast"),
    [(False, False), (True, False), (False, True), (True, True)],
    ids=["dark", "light", "dark-hc", "light-hc"],
)
def test_stylesheet_text_uses_only_the_type_scale(light, high_contrast):
    sheet = app_stylesheet(light=light, high_contrast=high_contrast)
    checked = 0
    for selector, body in _qss_rules(sheet):
        size = re.search(r"font-size:\s*(\d+)px", body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        if not size and not weight:
            continue
        # A rule that sets only one property inherits the other: body size
        # and regular weight unless the rule says otherwise.
        pair = (
            int(size.group(1)) if size else 13,
            int(weight.group(1)) if weight else 400,
        )
        if "FreeTextFormatBold" in selector:
            assert pair == (13, 700)
            continue
        assert pair in _TYPE_SCALE, f"{selector}: {pair}"
        checked += 1
    assert checked > 50


def test_stylesheet_has_no_monospace_chrome():
    for light in (False, True):
        sheet = app_stylesheet(light=light)
        lowered = sheet.lower()
        for family in ("monospace", "consolas", "cascadia"):
            assert family not in lowered


# --- Form-control indicator images ------------------------------------------


def _theme_for(light: bool):
    from pagedrop.ui.theme import DARK, LIGHT

    return LIGHT if light else DARK


def _closer_to(img, rect, near: str, far: str) -> int:
    """Pixels in ``rect`` nearer to ``near`` than to ``far`` (anti-aliasing tolerant)."""
    from PyQt6.QtGui import QColor

    def dist(c, target) -> int:
        t = QColor(target)
        return (c.red() - t.red()) ** 2 + (c.green() - t.green()) ** 2 + (c.blue() - t.blue()) ** 2

    count = 0
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            c = img.pixelColor(x, y)
            if dist(c, near) < dist(c, far):
                count += 1
    return count


def _exact_count(img, rect, hex_color: str) -> int:
    from PyQt6.QtGui import QColor

    target = QColor(hex_color).rgb()
    return sum(
        1
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
        if img.pixelColor(x, y).rgb() == target
    )


def _indicator_interior(widget):
    """Inside the 16px indicator's border: only its fill and mark are in here."""
    from PyQt6.QtCore import QRect

    g = widget.geometry()
    return QRect(g.x() + 2, g.center().y() - 5, 12, 11)


def _hosted(qtbot, widget):
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.addWidget(widget)
    _show(qtbot, host)
    QApplication.processEvents()
    return host


@pytest.mark.parametrize("mode", _STYLE_MODES)
@pytest.mark.parametrize("kind", ["check", "radio"])
def test_checked_indicator_draws_mark_on_ink_fill(qtbot, themed_app, mode, kind):
    from PyQt6.QtWidgets import QCheckBox, QRadioButton

    themed_app(**mode)
    theme = _theme_for(mode["light"])
    widget = QCheckBox() if kind == "check" else QRadioButton()
    widget.setChecked(True)
    host = _hosted(qtbot, widget)
    img = host.grab().toImage()
    area = _indicator_interior(widget)
    assert _exact_count(img, area, theme.ink) >= 40
    # The mark's own pixels: nearer the on-ink tint than the ink fill.
    assert _closer_to(img, area, theme.on_ink, theme.ink) >= 6


@pytest.mark.parametrize("light", [False, True])
def test_unchecked_indicator_has_no_mark(qtbot, themed_app, light):
    from PyQt6.QtWidgets import QCheckBox

    themed_app(light=light)
    theme = _theme_for(light)
    box = QCheckBox()
    host = _hosted(qtbot, box)
    img = host.grab().toImage()
    assert _exact_count(img, _indicator_interior(box), theme.ink) == 0


@pytest.mark.parametrize("light", [False, True])
def test_combo_arrow_is_drawn_in_the_drop_down(qtbot, themed_app, light):
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QComboBox

    from pagedrop.ui.theme import FORM_BUTTON_WIDTH

    themed_app(light=light)
    theme = _theme_for(light)
    combo = QComboBox()
    combo.addItem("")
    host = _hosted(qtbot, combo)
    img = host.grab().toImage()
    g = combo.geometry()
    inner = g.adjusted(3, 3, -3, -3)
    arrow = QRect(inner.right() - FORM_BUTTON_WIDTH + 1, inner.top(), FORM_BUTTON_WIDTH, inner.height())
    assert _closer_to(img, arrow, theme.text_muted, theme.raised) >= 4


@pytest.mark.parametrize("cls_name", ["QSpinBox", "QDoubleSpinBox"])
@pytest.mark.parametrize("light", [False, True])
def test_spin_box_draws_both_arrows_at_the_right_edge(qtbot, themed_app, light, cls_name):
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox

    from pagedrop.ui.theme import FORM_BUTTON_WIDTH

    themed_app(light=light)
    theme = _theme_for(light)
    spin = {"QSpinBox": QSpinBox, "QDoubleSpinBox": QDoubleSpinBox}[cls_name]()
    spin.setValue(5)
    host = _hosted(qtbot, spin)
    img = host.grab().toImage()
    g = spin.geometry()
    inner = g.adjusted(3, 3, -3, -3)
    x = inner.right() - FORM_BUTTON_WIDTH + 1
    half = inner.height() // 2
    up = QRect(x, inner.top(), FORM_BUTTON_WIDTH, half)
    down = QRect(x, inner.top() + half, FORM_BUTTON_WIDTH, inner.height() - half)
    assert _closer_to(img, up, theme.text_muted, theme.raised) >= 3
    assert _closer_to(img, down, theme.text_muted, theme.raised) >= 3


def test_spin_box_arrow_dims_at_its_limit(qtbot, themed_app):
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QSpinBox

    from pagedrop.ui.theme import FORM_BUTTON_WIDTH

    themed_app(light=True)
    theme = _theme_for(True)
    spin = QSpinBox()
    spin.setRange(0, 10)
    spin.setValue(10)
    host = _hosted(qtbot, spin)
    img = host.grab().toImage()
    inner = spin.geometry().adjusted(3, 3, -3, -3)
    x = inner.right() - FORM_BUTTON_WIDTH + 1
    half = inner.height() // 2
    up = QRect(x, inner.top(), FORM_BUTTON_WIDTH, half)
    down = QRect(x, inner.top() + half, FORM_BUTTON_WIDTH, inner.height() - half)
    # The up arrow is at its limit, so it is paler than the live down arrow.
    assert _closer_to(img, down, theme.text_muted, theme.raised) > _closer_to(
        img, up, theme.text_muted, theme.raised
    )


def test_indicator_images_load_from_a_directory_with_a_space(
    qtbot, themed_app, tmp_path, monkeypatch
):
    from PyQt6.QtWidgets import QCheckBox

    from pagedrop.ui import icons

    folder = tmp_path / "with space"
    folder.mkdir()
    monkeypatch.setattr(icons, "_indicator_dir", lambda: folder)
    themed_app(light=True)
    assert list(folder.glob("*.png"))
    theme = _theme_for(True)
    box = QCheckBox()
    box.setChecked(True)
    host = _hosted(qtbot, box)
    img = host.grab().toImage()
    assert _closer_to(img, _indicator_interior(box), theme.on_ink, theme.ink) >= 6


def test_window_controls_are_icons_not_glyphs(qtbot, main_window, themed_app):
    from PyQt6.QtGui import QIcon

    themed_app()
    expected = {
        "WindowMinimize": "Minimize window",
        "WindowMaximize": "Maximize window",
        "WindowClose": "Close window",
    }
    for button in main_window._window_control_buttons:
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.accessibleName() == expected[button.objectName()]
        assert button.toolTip() == expected[button.objectName()]
        assert button.autoRaise()
    close = next(b for b in main_window._window_control_buttons if b.objectName() == "WindowClose")
    size = close.iconSize()
    normal = close.icon().pixmap(size, QIcon.Mode.Normal).toImage()
    active = close.icon().pixmap(size, QIcon.Mode.Active).toImage()
    assert normal != active


def test_window_close_icon_turns_red_when_hovered(qtbot, main_window, themed_app):
    from PyQt6.QtGui import QColor

    themed_app()
    theme = _theme_for(False)
    _show(qtbot, main_window)
    close = next(b for b in main_window._window_control_buttons if b.objectName() == "WindowClose")

    def mark_colour() -> QColor:
        """Colour of the pixel that stands furthest out from the button fill."""
        img = close.grab().toImage()
        fill = img.pixelColor(img.width() // 2, 3)

        def away(c: QColor) -> int:
            return abs(c.red() - fill.red()) + abs(c.green() - fill.green()) + abs(c.blue() - fill.blue())

        return max(
            (img.pixelColor(x, y) for x in range(img.width()) for y in range(3, img.height() - 3)),
            key=away,
        )

    def nearer(c: QColor, hex_color: str, other: str) -> bool:
        def dist(target: str) -> int:
            t = QColor(target)
            return (c.red() - t.red()) ** 2 + (c.green() - t.green()) ** 2 + (c.blue() - t.blue()) ** 2

        return dist(hex_color) < dist(other)

    assert nearer(mark_colour(), theme.on_bar, theme.danger)
    close.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    close.update()
    assert nearer(mark_colour(), theme.danger, theme.on_bar)


def test_maximize_control_swaps_icon_and_tooltip(qtbot, main_window):
    from PyQt6.QtGui import QIcon

    _show(qtbot, main_window)
    button = main_window._maximize_button
    size = button.iconSize()
    normal = button.icon().pixmap(size).toImage()
    main_window.showMaximized()
    qtbot.waitUntil(main_window.isMaximized)
    assert button.toolTip() == "Restore window"
    assert button.accessibleName() == "Restore window"
    assert button.text() == ""
    restore = button.icon().pixmap(size, QIcon.Mode.Normal).toImage()
    assert restore != normal
    main_window.showNormal()
    qtbot.waitUntil(lambda: not main_window.isMaximized())
    assert button.toolTip() == "Maximize window"
    assert button.icon().pixmap(size).toImage() == normal


def test_window_control_icons_retint_on_theme_change(qtbot, main_window, themed_app, isolated_settings):
    from pagedrop.ui import icons
    from pagedrop.ui.settings import set_light_theme

    set_light_theme(False)
    icons.refresh_icons()
    minimize = next(b for b in main_window._window_control_buttons if b.objectName() == "WindowMinimize")
    dark = minimize.icon().pixmap(minimize.iconSize()).toImage()
    set_light_theme(True)
    icons.refresh_icons()
    try:
        assert minimize.icon().pixmap(minimize.iconSize()).toImage() != dark
    finally:
        set_light_theme(False)
        icons.refresh_icons()


@pytest.mark.parametrize("kind", ["check", "radio"])
@pytest.mark.parametrize("light", [False, True])
def test_disabled_checked_indicator_draws_the_disabled_mark(qtbot, themed_app, light, kind):
    from PyQt6.QtWidgets import QCheckBox, QRadioButton

    from pagedrop.ui.theme import blend

    themed_app(light=light)
    theme = _theme_for(light)
    widget = QCheckBox() if kind == "check" else QRadioButton()
    widget.setChecked(True)
    widget.setEnabled(False)
    host = _hosted(qtbot, widget)
    img = host.grab().toImage()
    area = _indicator_interior(widget)
    # Not the ink fill of an enabled control: a muted mark on the plain surface.
    assert _exact_count(img, area, theme.ink) == 0
    assert _exact_count(img, area, theme.raised) >= 40
    assert _closer_to(img, area, blend(theme.text_muted, theme.raised, 0.5), theme.raised) >= 6


def test_selection_count_label_fits_the_longest_range(main_window, themed_app):
    from pagedrop.assets import register_fonts

    # Measure in the bundled UI font, which is wider than the fallbacks.
    register_fonts()
    themed_app()
    label = main_window._selection_toolbar_label
    label.ensurePolished()
    assert label.fontMetrics().horizontalAdvance("Pages 1000–1000 selected") <= label.width()


def test_spin_and_combo_text_stops_before_the_buttons(qtbot, themed_app):
    from PyQt6.QtWidgets import (
        QComboBox,
        QDoubleSpinBox,
        QSpinBox,
        QStyle,
        QStyleOptionComboBox,
        QStyleOptionSpinBox,
    )

    themed_app(light=True)
    host = QWidget()
    layout = QVBoxLayout(host)
    spins = (QSpinBox(), QDoubleSpinBox())
    combo = QComboBox()
    combo.addItem("A long item that has to be elided before the drop-down")
    for widget in (*spins, combo):
        layout.addWidget(widget)
    _show(qtbot, host)
    QApplication.processEvents()

    for spin in spins:
        option = QStyleOptionSpinBox()
        option.initFrom(spin)
        option.subControls = QStyle.SubControl.SC_All
        up = spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, spin
        )
        assert spin.lineEdit().geometry().right() + 1 <= up.left()
    option = QStyleOptionComboBox()
    option.initFrom(combo)
    option.subControls = QStyle.SubControl.SC_All
    style = combo.style()
    field = style.subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, combo
    )
    arrow = style.subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxArrow, combo
    )
    assert field.right() + 1 <= arrow.left()


def _rule_bodies(sheet: str, selector: str) -> list[str]:
    return [body for sel, body in _qss_rules(sheet) if selector in [x.strip() for x in sel.split(",")]]


@pytest.mark.parametrize("light", [False, True], ids=["dark", "light"])
def test_secondary_text_and_disabled_text_follow_the_button_spec(light):
    from pagedrop.ui.theme import blend

    theme = _theme_for(light)
    sheet = app_stylesheet(light=light)
    faded = blend(theme.text, theme.chrome, 0.5)
    assert faded != theme.text
    for selector in ("QPushButton", "QPushButton#ToolbarSecondary"):
        (rest,) = _rule_bodies(sheet, selector)
        assert f"color: {theme.text};" in rest
        assert "background-color: transparent" in rest
        (off,) = _rule_bodies(sheet, f"{selector}:disabled")
        assert f"color: {faded};" in off
        assert "background-color: transparent" in off
    for selector in ("QToolButton:disabled", 'QPushButton[destructive="true"]:disabled'):
        (off,) = _rule_bodies(sheet, selector)
        assert f"color: {faded};" in off
    (primary_off,) = _rule_bodies(sheet, "QPushButton#ToolbarPrimary:disabled")
    assert f"background-color: {blend(theme.ink, theme.chrome, 0.5)};" in primary_off
    assert f"color: {blend(theme.on_ink, theme.chrome, 0.5)};" in primary_off
    (primary,) = _rule_bodies(sheet, "QPushButton#ToolbarPrimary")
    assert "font-weight: 600" in primary


def _message_box_with_destructive(qtbot, *, default_destructive: bool):
    from PyQt6.QtWidgets import QMessageBox

    from pagedrop.ui.dialogs import fit_message_box_buttons

    box = QMessageBox()
    box.setText("Discard changes?")
    discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep editing", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(discard if default_destructive else keep)
    fit_message_box_buttons(box)
    _show(qtbot, box)
    QApplication.processEvents()
    return box, discard, keep


def _inner_border_pixel(img, rect):
    """Second pixel in from the left edge: ring only when the border is 2px."""
    return img.pixelColor(rect.left() + 1, rect.center().y()).name().upper()


def _button_rect(box, button):
    from PyQt6.QtCore import QRect

    return QRect(button.mapTo(box, button.rect().topLeft()), button.size())


@pytest.mark.parametrize("default_destructive", [False, True], ids=["safe-default", "danger-default"])
@pytest.mark.parametrize("light", [False, True], ids=["dark", "light"])
def test_destructive_button_keeps_danger_look_in_message_box(
    qtbot, themed_app, light, default_destructive
):
    themed_app(light=light)
    theme = _theme_for(light)
    box, discard, keep = _message_box_with_destructive(qtbot, default_destructive=default_destructive)
    img = box.grab().toImage()
    danger_rect = _button_rect(box, discard)
    keep_rect = _button_rect(box, keep)
    # The label is drawn in danger and the fill is never ink. The default
    # button is focused, so its border is the ring; judge the interior.
    inside = danger_rect.adjusted(4, 4, -4, -4)
    assert _closer_to(img, inside, theme.danger, theme.chrome) >= 20
    assert _exact_count(img, danger_rect, theme.ink) == 0
    if not default_destructive:
        assert _exact_count(img, danger_rect, theme.danger) >= 40
    # The other button is the ink-filled default only when it is the default.
    assert (_exact_count(img, keep_rect, theme.ink) > 100) == (not default_destructive)


@pytest.mark.parametrize("light", [False, True], ids=["dark", "light"])
def test_focused_destructive_button_shows_focus_ring(qtbot, themed_app, light):
    themed_app(light=light)
    theme = _theme_for(light)
    ring = _ring_for(light)
    box, discard, _keep = _message_box_with_destructive(qtbot, default_destructive=False)
    rect = _button_rect(box, discard)
    assert _inner_border_pixel(box.grab().toImage(), rect) != ring.upper()
    _focus(qtbot, discard)
    img = box.grab().toImage()
    assert _inner_border_pixel(img, rect) == ring.upper()
    # The label keeps the danger colour.
    assert _closer_to(img, rect.adjusted(4, 4, -4, -4), theme.danger, theme.chrome) >= 20


@pytest.mark.parametrize("light", [False, True], ids=["dark", "light"])
def test_checked_tool_button_shows_focus_ring(qtbot, themed_app, light):
    themed_app(light=light)
    ring = _ring_for(light)
    button = QToolButton()
    button.setText("Grid")
    button.setCheckable(True)
    button.setChecked(True)
    host = _hosted(qtbot, button)
    button.clearFocus()
    QApplication.processEvents()
    rect = button.geometry()
    assert _inner_border_pixel(host.grab().toImage(), rect) != ring.upper()
    _focus(qtbot, button)
    assert _inner_border_pixel(host.grab().toImage(), rect) == ring.upper()


def _input_factories():
    from PyQt6.QtWidgets import (
        QComboBox,
        QDoubleSpinBox,
        QPlainTextEdit,
        QSpinBox,
        QTextEdit,
    )

    def combo():
        box = QComboBox()
        box.addItems(["One", "Two"])
        return box

    return {
        "line": QLineEdit,
        "page-edit": lambda: _named(QLineEdit(), "PdfViewerPageEdit"),
        "tools-search": lambda: _named(QLineEdit(), "ToolsSearch"),
        "combo": combo,
        "spin": QSpinBox,
        "double-spin": QDoubleSpinBox,
        "text": QTextEdit,
        "plain-text": QPlainTextEdit,
    }


def _named(widget, name):
    widget.setObjectName(name)
    return widget


def _count_colour(widget, colour: str) -> int:
    """Pixels of *colour* along the widget's frame (outer 3px)."""
    from PyQt6.QtGui import QColor

    img = widget.window().grab().toImage()
    target = QColor(colour)
    rect = widget.geometry()
    return sum(
        1
        for x in range(rect.left(), rect.right() + 1)
        for y in range(rect.top(), rect.bottom() + 1)
        if (
            min(x - rect.left(), rect.right() - x, y - rect.top(), rect.bottom() - y) < 3
            and img.pixelColor(x, y) == target
        )
    )


@pytest.mark.parametrize("light", [False, True], ids=["dark", "light"])
@pytest.mark.parametrize(
    "kind",
    ["line", "page-edit", "tools-search", "combo", "spin", "double-spin", "text", "plain-text"],
)
def test_error_state_paints_danger_border_and_clears(qtbot, kind, light):
    from pagedrop.ui.accessibility import set_field_error_state
    from pagedrop.ui.theme import DARK, LIGHT

    theme = LIGHT if light else DARK
    app = QApplication.instance()
    assert app is not None
    app.setStyleSheet(app_stylesheet(light=light))
    try:
        host = QWidget()
        lay = QVBoxLayout(host)
        field = _input_factories()[kind]()
        other = QLineEdit()
        lay.addWidget(field)
        lay.addWidget(other)
        qtbot.addWidget(host)
        host.resize(320, 200)
        host.show()
        qtbot.waitExposed(host)

        assert _count_colour(field, theme.danger) == 0

        set_field_error_state(field, True)
        qtbot.waitUntil(lambda: _count_colour(field, theme.danger) > 0, timeout=1000)

        # A focused error field keeps both the focus width and the danger colour.
        field.setFocus()
        qtbot.waitUntil(field.hasFocus, timeout=1000)
        focused_danger = _count_colour(field, theme.danger)
        assert focused_danger > 0
        assert _count_colour(field, theme.focus) == 0

        other.setFocus()
        qtbot.waitUntil(other.hasFocus, timeout=1000)
        set_field_error_state(field, False)
        qtbot.waitUntil(lambda: _count_colour(field, theme.danger) == 0, timeout=1000)

        field.setFocus()
        qtbot.waitUntil(field.hasFocus, timeout=1000)
        assert _count_colour(field, theme.focus) > 0
    finally:
        app.setStyleSheet("")


def test_set_field_error_state_is_idempotent(qtbot):
    from pagedrop.ui.accessibility import set_field_error_state

    field = QLineEdit()
    qtbot.addWidget(field)
    set_field_error_state(field, False)
    assert not field.property("error")
    set_field_error_state(field, True)
    set_field_error_state(field, True)
    assert field.property("error") is True
    set_field_error_state(field, False)
    assert field.property("error") is False
    label = QLabel("no rule")
    qtbot.addWidget(label)
    set_field_error_state(label, True)
    assert label.property("error") is True
