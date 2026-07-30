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
    assert "QCheckBox:focus::indicator" in sheet
    assert "QRadioButton:focus::indicator" in sheet


def test_r10a_page_chips_and_prefs_chrome():
    """R10a: theme-aware chips, annot rail focus, prefs section/divider QSS."""
    from pagedrop.ui.theme import ACCENT, TEXT_ON_ACCENT

    dark = app_stylesheet()
    light = app_stylesheet(light=True)

    dark_chip = "rgba(19, 19, 22, 160)"
    light_chip = "rgba(26, 26, 31, 170)"

    for sheet, chip_bg in ((dark, dark_chip), (light, light_chip)):
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
        assert f"solid {ACCENT}" in sheet.split(
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
    assert len(dialog.findChildren(QLabel, "PreferencesSection")) == 5
    assert len(dialog.findChildren(QFrame, "PreferencesDivider")) == 4


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
    assert "Ctrl+O" in grid._empty_kbd.text()
    assert "Ctrl+A" in grid._empty_kbd.text()


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

    page_block = dark.split("QFrame#PageCard,")[1].split("QFrame#PageCard:hover")[0]
    assert "border: 1px solid" in page_block
    assert f'QFrame#PageCard[focused="true"]' in dark
    assert f"border: 2px solid {ACCENT}" in dark
    assert f"border: 3px solid {ACCENT}" in dark
    assert f"border: 3px solid {ACCENT}" in high  # focus in HC
    assert f"border: 4px solid {ACCENT}" in high  # selected in HC
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
    assert f'QFrame#PageCard[selected="true"]' in sheet
    assert f'QFrame#PageCard[focused="true"]' in sheet

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
    from pagedrop.ui.theme import ACCENT, app_stylesheet

    dark = app_stylesheet()
    high = app_stylesheet(high_contrast=True)

    rest = dark.split("QFrame#ToolTile {")[1].split("QFrame#ToolTile:hover")[0]
    assert "background-color: transparent" in rest
    assert "border: 1px solid transparent" in rest

    assert "QFrame#ToolTile:focus" in dark
    assert f"border: 2px solid {ACCENT}" in dark
    assert f"border: 3px solid {ACCENT}" in high
    assert 'QFrame#ToolTile[blocked="true"]:hover' in dark
    assert 'QFrame#ToolTile[compact="true"]' in dark


def test_r6_tool_shell_drop_and_result_match_secondary():
    """R6: drop zone + result actions use ghost/outline secondary language."""
    from pagedrop.ui.theme import ACCENT, app_stylesheet

    for sheet in (app_stylesheet(), app_stylesheet(light=True)):
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
        assert f"dashed {ACCENT}" in sheet


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


def test_r7_feedback_motion_only_in_busy_overlay():
    """R7: no QPropertyAnimation on tab switch / palette / grid keyboard paths."""
    from pathlib import Path

    ui_root = Path(__file__).resolve().parents[2] / "src" / "pagedrop" / "ui"
    animated = sorted(
        path.name
        for path in ui_root.glob("*.py")
        if "QPropertyAnimation" in path.read_text(encoding="utf-8")
    )
    assert animated == ["busy_overlay.py"]


def test_r8_light_hc_parity_freeze(isolated_settings):
    """R8: dark/light/HC sheets share chrome roles; light status ink meets AA; HC thickens."""
    from pagedrop.ui.settings import set_light_theme
    from pagedrop.ui.theme import (
        ACCENT,
        BG_CARD,
        BG_CARD_LIGHT,
        BG_GRID_LIGHT,
        CLOSE_TAB,
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
    assert f"border: 4px solid {ACCENT}" in dark_hc
    assert f"border: 3px solid {ACCENT}" in light_hc
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
