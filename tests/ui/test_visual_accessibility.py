"""Visual & platform accessibility — contrast, motion, focus, labels."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QToolButton

from pagedrop.ui.accessibility import contrast_ratio, prefers_reduce_motion
from pagedrop.ui.base_file_card import BaseFileCard
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.preferences_dialog import PreferencesDialog
from pagedrop.ui.settings import reduce_motion, set_reduce_motion
from pagedrop.ui.theme import BG_BASE, TEXT_MUTED, app_stylesheet
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from pagedrop.ui.zoom_controls import ZoomControls


def test_text_muted_meets_wcag_aa_on_bg_base():
    assert contrast_ratio(TEXT_MUTED, BG_BASE) >= 4.5


def test_light_text_muted_meets_wcag_aa_on_bg_grid():
    # Keep in sync with app_stylesheet(light=True) text_muted_tok / bg_grid.
    light_muted = "#5A5D68"
    light_bg_grid = "#F0F1F4"
    assert contrast_ratio(light_muted, light_bg_grid) >= 4.5
    assert light_muted in app_stylesheet(light=True)


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
    assert card._shadow.blurRadius() > 14
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
    assert not grid._skeleton_pulse_timer.isActive()

    set_reduce_motion(False)
    grid._start_skeleton_pulse()
    assert grid._skeleton_pulse_timer.isActive()
    grid._stop_skeleton_pulse()


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
    assert "QSpinBox {" in sheet
    assert "QCheckBox," in sheet
    assert "QLineEdit {" in sheet
    assert "QSlider#ZoomSlider:focus" in sheet
    assert "QPushButton#ZoomButton:focus" in sheet
    assert "QTabWidget#PdfViewerSide::pane" in sheet


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
    assert "background-color: transparent" in sheet.split("QWidget#ZoomControls")[1].split(
        "QLabel#ZoomCaption"
    )[0]


def test_r3_toolbar_roles_match_action_weight(main_window, qtbot):
    """R3: Open / Merge / Save PDF / Run are primary; browse/add are secondary."""
    open_btn = main_window._toolbar.widgetForAction(main_window._actions["open"])
    assert open_btn is not None
    assert open_btn.objectName() == "ToolbarPrimary"
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
        STATUS_WARNING,
        TEXT_ON_ACCENT,
        VIEWER_PAGE_BG,
        token_qcolor,
    )

    dark = app_stylesheet()
    light = app_stylesheet(light=True)
    high = app_stylesheet(high_contrast=True)

    for sheet in (dark, light, high):
        assert "QFrame#DropIndicator" in sheet
        assert "QLabel#ToolsErrorHint" in sheet
        assert "QLabel#ComparePaneTitle" in sheet
        assert "QLabel#CompareModeLabel" in sheet
        assert "QLabel#CompareSummary" in sheet
        assert VIEWER_PAGE_BG in sheet
        assert "QPushButton#ToolbarSecondary" in sheet
        assert f"color: {STATUS_SUCCESS}" in sheet
        assert f"color: {STATUS_WARNING}" in sheet
        assert f"color: {TEXT_ON_ACCENT}" in sheet
        # Success toast must not fall back to accent blue.
        assert 'ToastOverlayMessage[kind="success"]' in sheet
        success_block = sheet.split('ToastOverlayMessage[kind="success"]')[1].split("}")[0]
        assert STATUS_SUCCESS in success_block
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
    from pagedrop.ui.accessibility import apply_app_stylesheet, refresh_themed_widgets
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
    refresh_themed_widgets()
    light_border = border_hover_qcolor()
    assert light_border.name().upper() == BORDER_HOVER_LIGHT.upper()
    light_shadow = shadow_qcolor(alpha=72)
    assert (light_shadow.red(), light_shadow.green(), light_shadow.blue()) == SHADOW_RGB_LIGHT
    assert light_shadow.alpha() == SHADOW_ALPHA_CAP_LIGHT

    set_light_theme(False)
    apply_app_stylesheet()
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

    new_tab = main_window._tab_manager.cornerWidget(Qt.Corner.TopRightCorner)
    assert isinstance(new_tab, QToolButton)
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


def test_r2_empty_state_shortcuts_unchanged(qtbot):
    """R2: empty-state kbd strings stay accurate; spacing reads from tokens."""
    from pagedrop.ui.theme import SPACE_3, SPACE_4, SPACE_6, SPACE_7

    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    assert grid._layout.spacing() == SPACE_3
    assert grid._layout.contentsMargins().left() == SPACE_4
    empty_margins = grid._empty_state.layout().contentsMargins()
    assert empty_margins.left() == SPACE_6
    assert empty_margins.top() == SPACE_7
    assert "Ctrl+O" in grid._empty_kbd.text()
    assert "Ctrl+A" in grid._empty_kbd.text()
