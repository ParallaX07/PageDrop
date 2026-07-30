"""PageDrop visual design tokens and Qt Style Sheets."""

from __future__ import annotations

# Cold charcoal + electric blue (devtool / document utility)
BG_BASE = "#131316"
BG_SURFACE = "#1A1A1F"
BG_GRID = "#16161A"
BG_CARD = "#222228"
BG_CARD_HOVER = "#2A2A32"
BG_TOOLBAR = "#1A1A1F"
BG_STATUS = "#1A1A1F"
BG_TAB_BAR = "#17171C"
BG_PREVIEW_FOOTER = "#1A1A1F"

BORDER_SUBTLE = "#2E2E36"
BORDER_DEFAULT = "#45454F"
BORDER_HOVER = "#5C5C68"
# Light chrome border — shared by app_stylesheet locals + paint helpers
BORDER_HOVER_LIGHT = "#9CA3AF"

# ponytail: darkened from #2F9BE6 so TEXT_ON_ACCENT meets WCAG AA ≥ 4.5 on
# fill / hover / pressed; brighten only if labels move off the fill.
ACCENT = "#1868AD"
ACCENT_HOVER = "#1C74BC"
ACCENT_PRESSED = "#13558E"

TEXT_PRIMARY = "#F2F2F4"
TEXT_SECONDARY = "#A8A8B3"
TEXT_MUTED = "#82828E"
# Ink on accent / filled interactive chrome (labels, selection text, focus rings)
TEXT_ON_ACCENT = "#FFFFFF"

# Light chrome mirrors — paint helpers + app_stylesheet(light=True) share these
# so toggling light never leaves dark-only module hex on white surfaces.
TEXT_PRIMARY_LIGHT = "#1A1A1F"
TEXT_SECONDARY_LIGHT = "#4A4A55"
TEXT_MUTED_LIGHT = "#5A5D68"
BG_CARD_LIGHT = "#FFFFFF"
BG_BASE_LIGHT = "#F7F8FA"
BG_GRID_LIGHT = "#F0F1F4"

CLOSE_TAB = "#E85D5D"
CLOSE_TAB_HOVER_BG = "#3D2228"
CLOSE_TAB_PRESSED_BG = "#2A1519"
CLOSE_TAB_LIGHT = "#D14343"
CLOSE_TAB_HOVER_BG_LIGHT = "#F5D6D6"
CLOSE_TAB_PRESSED_BG_LIGHT = "#E8B4B4"

# Semantic status (compare diffs, validation errors, toast kinds)
STATUS_SUCCESS = "#4CAF6E"
STATUS_WARNING = "#F0B43C"
# Darker status ink for light chrome text (toast / lists) — AA ≥ 4.5 on white
STATUS_SUCCESS_LIGHT = "#1B7A3D"
STATUS_WARNING_LIGHT = "#8A6200"

# Viewer page paper — intentional light plane even under dark chrome
VIEWER_PAGE_BG = "#FAFAFA"
# Marks drawn on page paper (stay dark regardless of chrome theme)
PAGE_INK = "#141414"
# Find / search overlays drawn on the page (content, not chrome)
SEARCH_HIT = "#FFDC00"
SEARCH_HIT_ACTIVE = "#FF9100"
SEARCH_HIT_ACTIVE_EDGE = "#C85A00"
COMMENT_PIN = "#FFDC50"
COMMENT_PIN_EDGE = "#B48C00"

# Tinted shadow (cool blue, not pure black)
SHADOW_RGB = (14, 22, 38)
SHADOW_RGB_LIGHT = (30, 40, 60)
# R5: light hover needs a bit more depth than the old 40 cap; raise again if washout
SHADOW_ALPHA_CAP_LIGHT = 48

RADIUS_CARD = 12
RADIUS_CONTROL = 8
RADIUS_BADGE = 6

FONT_UI = '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'

# Spacing scale (4px steps) — toolbar / grid / empty-state rhythm
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32
SPACE_7 = 48

CARD_PADDING = SPACE_4
DEFAULT_THUMBNAIL_WIDTH = 160
MIN_THUMBNAIL_WIDTH = 80
MAX_THUMBNAIL_WIDTH = 480
ZOOM_WHEEL_STEP = 16
# Below-card labels are easy to miss once thumbnails get large.
PAGE_NUMBER_OVERLAY_MIN_WIDTH = DEFAULT_THUMBNAIL_WIDTH + ZOOM_WHEEL_STEP * 5
MIN_PREVIEW_RENDER_WIDTH = 400
CARD_WIDTH = DEFAULT_THUMBNAIL_WIDTH + CARD_PADDING
# Mid-toolbar PDF name cap — long names must not shove zoom off-screen (R14).
TOOLBAR_FILENAME_MAX_WIDTH = 220


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance for a #RRGGBB color."""
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def app_stylesheet(*, high_contrast: bool = False, light: bool = False) -> str:
    # Light / HC overrides under distinct locals so we never mutate module tokens.
    if light:
        # Cool off-white base; white cards; light borders (Bento light translation).
        bg_base = BG_BASE_LIGHT
        bg_surface = BG_CARD_LIGHT
        bg_grid = BG_GRID_LIGHT
        bg_card = BG_CARD_LIGHT
        bg_card_hover = "#EEF0F4"
        bg_thumb_empty = "#E2E4EA"
        bg_toolbar = BG_CARD_LIGHT
        bg_status = BG_CARD_LIGHT
        bg_tab_bar = BG_BASE_LIGHT
        bg_preview_footer = BG_CARD_LIGHT
        border_subtle_tok = "#E5E7EB"
        border_default_tok = "#D1D5DB"
        border_hover = BORDER_HOVER_LIGHT
        text_primary = TEXT_PRIMARY_LIGHT
        text_secondary = TEXT_SECONDARY_LIGHT
        text_muted_tok = TEXT_MUTED_LIGHT
        close_tab = CLOSE_TAB_LIGHT
        close_tab_hover_bg = CLOSE_TAB_HOVER_BG_LIGHT
        close_tab_pressed_bg = CLOSE_TAB_PRESSED_BG_LIGHT
        status_success = STATUS_SUCCESS_LIGHT
        status_warning = STATUS_WARNING_LIGHT
        busy_overlay_bg = "rgba(247, 248, 250, 200)"
        # Chips sit on page-paper thumbs (always light) — dark pill either chrome.
        page_chip_bg = "rgba(26, 26, 31, 170)"
        # R10c: one step deeper than bg_base for generic press fills.
        bg_pressed = "#E2E4EA"
    else:
        bg_base = BG_BASE
        bg_surface = BG_SURFACE
        bg_grid = BG_GRID
        bg_card = BG_CARD
        bg_card_hover = BG_CARD_HOVER
        bg_thumb_empty = "#2A2A32"
        bg_toolbar = BG_TOOLBAR
        bg_status = BG_STATUS
        bg_tab_bar = BG_TAB_BAR
        bg_preview_footer = BG_PREVIEW_FOOTER
        border_subtle_tok = BORDER_SUBTLE
        border_default_tok = BORDER_DEFAULT
        border_hover = BORDER_HOVER
        text_primary = TEXT_PRIMARY
        text_secondary = TEXT_SECONDARY
        text_muted_tok = TEXT_MUTED
        close_tab = CLOSE_TAB
        close_tab_hover_bg = CLOSE_TAB_HOVER_BG
        close_tab_pressed_bg = CLOSE_TAB_PRESSED_BG
        status_success = STATUS_SUCCESS
        status_warning = STATUS_WARNING
        busy_overlay_bg = "rgba(19, 19, 22, 180)"
        page_chip_bg = "rgba(19, 19, 22, 160)"
        bg_pressed = "#0E0E11"

    text_muted = text_secondary if high_contrast else text_muted_tok
    border_default = border_hover if high_contrast else border_default_tok
    border_subtle = border_default_tok if high_contrast else border_subtle_tok
    focus_width = 3 if high_contrast else 2
    # Selection reads thicker than keyboard focus (multi-select still obvious in HC)
    selected_width = focus_width + 1
    return f"""
    * {{
        font-family: {FONT_UI};
        font-size: 13px;
        color: {text_primary};
    }}

    QMainWindow {{
        background-color: {bg_base};
    }}

    QToolTip {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        padding: 4px 8px;
    }}

    QMenuBar {{
        background-color: {bg_surface};
        color: {text_primary};
        border-bottom: 1px solid {border_subtle};
        padding: 2px 0;
    }}

    QMenuBar::item {{
        background: transparent;
        padding: 6px 12px;
        border-radius: {RADIUS_CONTROL}px;
        border: {focus_width}px solid transparent;
    }}

    /* no ::item:focus — Qt marks every menubar item focused at once */
    QMenuBar::item:selected {{
        background-color: {bg_card_hover};
        border-color: {ACCENT};
    }}

    QMenu {{
        background-color: {bg_surface};
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px;
    }}

    QMenu::item {{
        padding: 8px 28px 8px 16px;
        border-radius: 6px;
        border: {focus_width}px solid transparent;
    }}

    QMenu::item:selected {{
        background-color: {bg_card_hover};
        border-color: {ACCENT};
    }}

    QMenu::separator {{
        height: 1px;
        background: {border_subtle};
        margin: 4px 8px;
    }}

    QDialog {{
        background-color: {bg_base};
        color: {text_primary};
    }}

    QLineEdit {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 8px 10px;
        selection-background-color: {ACCENT};
        selection-color: {TEXT_ON_ACCENT};
    }}

    QLineEdit:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QListWidget,
    QTreeWidget {{
        background-color: {bg_surface};
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        outline: none;
        padding: 4px;
    }}

    QListWidget::item,
    QTreeWidget::item {{
        padding: 8px 10px;
        border-radius: 6px;
        color: {text_primary};
    }}

    QListWidget::item:selected,
    QTreeWidget::item:selected {{
        background-color: {ACCENT};
        color: {TEXT_ON_ACCENT};
    }}

    QListWidget::item:hover:!selected,
    QTreeWidget::item:hover:!selected {{
        background-color: {bg_card_hover};
    }}

    QLabel#CommandPaletteHint {{
        color: {text_muted};
        font-size: 11px;
        font-family: {FONT_MONO};
    }}

    QPushButton {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 14px;
        font-weight: 600;
    }}

    QPushButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QPushButton:pressed {{
        background-color: {bg_pressed};
    }}

    QPushButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QPushButton:disabled {{
        color: {text_muted};
        border-color: {border_subtle};
    }}

    QCheckBox,
    QRadioButton {{
        color: {text_primary};
        spacing: 8px;
        border: none;
        background-color: transparent;
        outline: none;
    }}

    QCheckBox::indicator,
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {border_default};
        background-color: {bg_card};
    }}

    QCheckBox::indicator {{
        border-radius: 3px;
    }}

    QRadioButton::indicator {{
        border-radius: 8px;
    }}

    QCheckBox::indicator:checked,
    QRadioButton::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT_PRESSED};
    }}

    QCheckBox:focus,
    QRadioButton:focus {{
        outline: none;
        border: none;
    }}

    /* ::indicator:focus — NOT :focus::indicator. Fusion paints a full-widget
       accent frame for the latter (Flatten watermark blue box). */
    QCheckBox::indicator:focus,
    QRadioButton::indicator:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QComboBox {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 10px;
        min-height: 20px;
    }}

    QComboBox:hover {{
        border-color: {border_hover};
    }}

    QComboBox:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {bg_surface};
        color: {text_primary};
        border: 1px solid {border_subtle};
        selection-background-color: {ACCENT};
        selection-color: {TEXT_ON_ACCENT};
    }}

    QSpinBox,
    QDoubleSpinBox {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 8px;
        selection-background-color: {ACCENT};
        selection-color: {TEXT_ON_ACCENT};
    }}

    QSpinBox:focus,
    QDoubleSpinBox:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QPlainTextEdit,
    QTextEdit {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 8px 10px;
        selection-background-color: {ACCENT};
        selection-color: {TEXT_ON_ACCENT};
    }}

    QPlainTextEdit:focus,
    QTextEdit:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QGroupBox {{
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {text_secondary};
    }}

    /* Encrypt permissions — surface + card radius so it matches section language. */
    QGroupBox#EncryptPermissions {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CARD}px;
    }}

    QGroupBox#EncryptPermissions::title {{
        color: {text_secondary};
    }}

    QToolBar {{
        background-color: {bg_toolbar};
        border: none;
        border-bottom: 1px solid {border_subtle};
        spacing: {SPACE_2}px;
        padding: {SPACE_2}px {SPACE_3}px;
    }}

    /* Viewer chrome uses QToolButton outside QToolBar; keep both in sync.
       R3: default tools are flat/hairline; filled primary + outline secondary stay. */
    QToolButton,
    QToolBar QToolButton {{
        background-color: transparent;
        color: {text_primary};
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 10px;
        font-weight: 500;
    }}

    QToolButton:hover,
    QToolBar QToolButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_subtle};
    }}

    QToolButton:pressed,
    QToolBar QToolButton:pressed {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}

    QToolButton:focus,
    QToolBar QToolButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QToolButton:checked {{
        background-color: {ACCENT};
        color: {TEXT_ON_ACCENT};
        border: 1px solid {ACCENT_PRESSED};
        font-weight: 600;
    }}

    QToolButton:checked:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    QToolButton:disabled,
    QToolBar QToolButton:disabled {{
        color: {text_muted};
        background-color: transparent;
        border-color: transparent;
    }}

    QPushButton#ToolbarPrimary,
    QToolBar QToolButton#ToolbarPrimary {{
        background-color: {ACCENT};
        color: {TEXT_ON_ACCENT};
        border: 1px solid {ACCENT_PRESSED};
        font-weight: 600;
        padding: 6px 14px;
    }}

    QPushButton#ToolbarPrimary:hover,
    QToolBar QToolButton#ToolbarPrimary:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    QPushButton#ToolbarPrimary:pressed,
    QToolBar QToolButton#ToolbarPrimary:pressed {{
        background-color: {ACCENT_PRESSED};
        border-color: {ACCENT_PRESSED};
    }}

    QPushButton#ToolbarPrimary:focus,
    QToolBar QToolButton#ToolbarPrimary:focus {{
        border: {focus_width}px solid {TEXT_ON_ACCENT};
    }}

    QPushButton#ToolbarPrimary:disabled {{
        background-color: {bg_card_hover};
        color: {text_muted};
        border-color: {border_subtle};
    }}

    /* Ghost / outline secondary — quieter than default fill, not accent primary. */
    QPushButton#ToolbarSecondary,
    QToolBar QToolButton#ToolbarSecondary {{
        background-color: transparent;
        color: {text_secondary};
        border: 1px solid {border_default};
        font-weight: 600;
    }}

    QPushButton#ToolbarSecondary:hover,
    QToolBar QToolButton#ToolbarSecondary:hover {{
        background-color: {bg_card_hover};
        color: {text_primary};
        border-color: {border_hover};
    }}

    QPushButton#ToolbarSecondary:pressed,
    QToolBar QToolButton#ToolbarSecondary:pressed {{
        background-color: {bg_pressed};
        color: {text_primary};
    }}

    QPushButton#ToolbarSecondary:focus,
    QToolBar QToolButton#ToolbarSecondary:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QPushButton#ToolbarSecondary:disabled,
    QToolBar QToolButton#ToolbarSecondary:disabled {{
        color: {text_muted};
        border-color: {border_subtle};
        background-color: transparent;
    }}

    QToolButton#NewTabButton {{
        background-color: transparent;
        color: {text_secondary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        font-size: 16px;
        font-weight: 600;
        min-width: 28px;
        max-width: 28px;
        min-height: 28px;
        max-height: 28px;
        padding: 0;
    }}

    QToolButton#NewTabButton:hover {{
        background-color: {bg_card_hover};
        color: {text_primary};
        border-color: {border_hover};
    }}

    QToolButton#NewTabButton:pressed {{
        background-color: {bg_pressed};
    }}

    QToolButton#NewTabButton:focus {{
        border: {focus_width}px solid {ACCENT};
        color: {text_primary};
    }}

    QToolButton#ChromeToggleButton {{
        background-color: transparent;
        color: {text_secondary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        font-size: 14px;
        font-weight: 600;
        min-width: 28px;
        max-width: 28px;
        min-height: 28px;
        max-height: 28px;
        padding: 0;
    }}

    QToolButton#ChromeToggleButton:hover {{
        background-color: {bg_card_hover};
        color: {text_primary};
        border-color: {border_hover};
    }}

    QToolButton#ChromeToggleButton:pressed {{
        background-color: {bg_pressed};
    }}

    QToolButton#ChromeToggleButton:focus {{
        border: {focus_width}px solid {ACCENT};
        color: {text_primary};
    }}

    QLabel#ToolbarFilename {{
        color: {text_secondary};
        font-weight: 500;
        padding: 0 4px;
    }}

    QLabel#ToolbarFilename[active="true"] {{
        color: {text_primary};
    }}

    QWidget#ZoomControls {{
        background-color: transparent;
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: {SPACE_1}px;
    }}

    QLabel#ZoomCaption {{
        color: {text_muted};
        font-size: 11px;
        font-weight: 600;
        padding: 0 {SPACE_1}px 0 0;
    }}

    QPushButton#ZoomButton {{
        background-color: transparent;
        color: {text_primary};
        border: 1px solid transparent;
        border-radius: 6px;
        font-size: 15px;
        font-weight: 600;
        padding: 0;
    }}

    QPushButton#ZoomButton:hover:enabled {{
        background-color: {bg_card_hover};
        border-color: {border_subtle};
        color: {text_primary};
    }}

    QPushButton#ZoomButton:pressed:enabled {{
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QPushButton#ZoomButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QPushButton#ZoomButton:disabled {{
        color: {text_muted};
        background-color: transparent;
        border-color: transparent;
    }}

    QSlider#ZoomSlider {{
        min-height: 20px;
    }}

    QSlider#ZoomSlider::groove:horizontal {{
        background: {bg_base};
        border: 1px solid {border_subtle};
        height: 4px;
        border-radius: 2px;
    }}

    QSlider#ZoomSlider::sub-page:horizontal {{
        background: {ACCENT};
        border: 1px solid {ACCENT_PRESSED};
        height: 4px;
        border-radius: 2px;
    }}

    QSlider#ZoomSlider::add-page:horizontal {{
        background: {bg_base};
        border: 1px solid {border_subtle};
        height: 4px;
        border-radius: 2px;
    }}

    QSlider#ZoomSlider::handle:horizontal {{
        background: {text_primary};
        border: 2px solid {ACCENT};
        width: 12px;
        height: 12px;
        margin: -5px 0;
        border-radius: 6px;
    }}

    QSlider#ZoomSlider::handle:horizontal:hover {{
        background: {TEXT_ON_ACCENT};
        border-color: {ACCENT_HOVER};
    }}

    QSlider#ZoomSlider:focus {{
        background: transparent;
    }}

    QSlider#ZoomSlider:focus::groove:horizontal {{
        border: {focus_width}px solid {ACCENT};
    }}

    QSlider#ZoomSlider:focus::handle:horizontal {{
        background: {ACCENT};
        border: 2px solid {TEXT_ON_ACCENT};
        width: 14px;
        height: 14px;
        margin: -6px 0;
    }}

    QSlider#ZoomSlider:disabled::groove:horizontal,
    QSlider#ZoomSlider:disabled::sub-page:horizontal,
    QSlider#ZoomSlider:disabled::add-page:horizontal {{
        background: {bg_surface};
        border-color: {border_subtle};
    }}

    QSlider#ZoomSlider:disabled::handle:horizontal {{
        background: {border_default};
        border-color: {border_subtle};
    }}

    QLabel#ZoomValueLabel {{
        color: {text_secondary};
        font-family: {FONT_MONO};
        font-size: 11px;
        font-weight: 600;
    }}

    QStatusBar {{
        background-color: {bg_status};
        color: {text_secondary};
        border-top: 1px solid {border_subtle};
    }}

    QStatusBar QLabel {{
        color: {text_secondary};
    }}

    /* R10e: tool-tab footers mirror QStatusBar so Tools/editor chrome feel related. */
    QLabel#ToolPageStatus {{
        background-color: {bg_status};
        color: {text_secondary};
        border-top: 1px solid {border_subtle};
        padding: {SPACE_1}px {SPACE_3}px;
        min-height: 22px;
    }}

    QWidget#MoveUndoToast QLabel {{
        color: {text_secondary};
        font-weight: 600;
    }}

    QPushButton#MoveUndoButton {{
        color: {text_primary};
        background-color: {bg_card};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 2px 10px;
        font-weight: 600;
    }}

    QPushButton#MoveUndoButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QPushButton#MoveUndoButton:pressed {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}

    QProgressBar {{
        background-color: {bg_card};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        text-align: center;
        color: {text_muted};
        min-height: 8px;
        max-height: 8px;
    }}

    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 7px;
    }}

    QScrollArea#ThumbnailGrid {{
        background-color: {bg_grid};
        border: none;
    }}

    QWidget#ThumbnailContainer {{
        background-color: {bg_grid};
    }}

    /* R10b: editor empty reads as a drop zone — same dashed language as Tools. */
    QWidget#EmptyStatePanel {{
        background-color: transparent;
        border: 1px dashed {border_default};
        border-radius: {RADIUS_CARD}px;
        margin: {SPACE_4}px;
    }}

    QWidget#EmptyStatePanel[dropActive="true"] {{
        border-color: {ACCENT};
        border-style: dashed;
        background-color: {bg_card_hover};
    }}

    QLabel#GridEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 {SPACE_3}px 0;
    }}

    QLabel#GridEmptyState {{
        color: {text_secondary};
        font-size: 15px;
        font-weight: 600;
        letter-spacing: -0.2px;
        padding: 0;
    }}

    QLabel#GridEmptyHint {{
        color: {text_muted};
        font-size: 13px;
        font-weight: 400;
        padding: 0;
    }}

    QLabel#GridEmptyKbd,
    QLabel#MergeEmptyKbd,
    QLabel#ConvertEmptyKbd {{
        color: {text_muted};
        font-family: {FONT_MONO};
        font-size: 11px;
        padding: {SPACE_2}px 0 0 0;
    }}

    /* R6: flat tab strip — accent underline + muted inactive; no filled selected box. */
    QTabWidget#TabManager::pane {{
        border: none;
        background-color: {bg_base};
        top: -1px;
    }}

    QTabWidget#TabManager > QTabBar {{
        background-color: {bg_tab_bar};
        border-bottom: 1px solid {border_subtle};
    }}

    QTabWidget#TabManager > QTabBar::tab {{
        background-color: transparent;
        color: {text_muted};
        border: none;
        border-bottom: 2px solid transparent;
        padding: {SPACE_2}px {SPACE_3}px {SPACE_2 - 1}px {SPACE_3}px;
        margin-right: 2px;
        min-width: 80px;
        max-width: 220px;
        font-weight: 500;
    }}

    QTabWidget#TabManager > QTabBar::tab:selected {{
        color: {text_primary};
        background-color: transparent;
        border-bottom: 2px solid {ACCENT};
        font-weight: 600;
    }}

    QTabWidget#TabManager > QTabBar::tab:hover:!selected {{
        color: {text_secondary};
        background-color: transparent;
    }}

    QTabWidget#TabManager > QTabBar::tab:selected:hover {{
        color: {text_primary};
    }}

    QTabWidget#TabManager QTabBar QAbstractButton {{
        background-color: transparent;
        border: none;
        border-radius: {SPACE_1}px;
        padding: 2px;
        min-width: 18px;
        max-width: 18px;
        min-height: 18px;
        max-height: 18px;
    }}

    QTabWidget#TabManager QTabBar QAbstractButton:hover {{
        background-color: {close_tab_hover_bg};
    }}

    QTabWidget#TabManager QTabBar QAbstractButton:pressed {{
        background-color: {close_tab_pressed_bg};
    }}

    QTabWidget#TabManager QTabBar QAbstractButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QScrollBar:vertical {{
        background: {bg_grid};
        width: 10px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background: {border_default};
        border-radius: 5px;
        min-height: 32px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {border_hover};
    }}

    QScrollBar::handle:vertical:pressed {{
        background: {text_muted};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar:horizontal {{
        background: {bg_grid};
        height: 10px;
        margin: 0;
    }}

    QScrollBar::handle:horizontal {{
        background: {border_default};
        border-radius: 5px;
        min-width: 32px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {border_hover};
    }}

    QScrollBar::handle:horizontal:pressed {{
        background: {text_muted};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* R10e: splitter grip press feedback (viewer / compare). */
    QSplitter::handle {{
        background-color: {border_subtle};
    }}

    QSplitter::handle:hover {{
        background-color: {border_default};
    }}

    QSplitter::handle:pressed {{
        background-color: {border_hover};
    }}

    QSplitter::handle:horizontal {{
        height: 3px;
    }}

    QSplitter::handle:vertical {{
        width: 3px;
    }}

    QMessageBox {{
        background-color: {bg_surface};
    }}

    QMessageBox QLabel {{
        color: {text_primary};
    }}

    QMessageBox QPushButton {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 20px;
    }}

    QMessageBox QPushButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QMessageBox QPushButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QMessageBox QPushButton:default {{
        background-color: {ACCENT};
        border-color: {ACCENT};
        color: {TEXT_ON_ACCENT};
        font-weight: 600;
    }}

    QMessageBox QPushButton:default:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    QScrollArea#PagePreviewScroll {{
        background-color: {bg_grid};
        border: none;
    }}

    QWidget#PagePreview {{
        background-color: {bg_base};
    }}

    QLabel#PagePreviewImage {{
        background-color: {VIEWER_PAGE_BG};
        padding: 8px;
    }}

    QWidget#PreviewFooter {{
        background-color: {bg_preview_footer};
        border-top: 1px solid {border_subtle};
    }}

    QLabel#PagePreviewHint {{
        color: {text_secondary};
        font-size: 11px;
        font-family: {FONT_MONO};
        padding: 10px 16px;
    }}

    QWidget#PdfViewer {{
        background-color: {bg_base};
    }}

    QScrollArea#PdfViewerScroll {{
        background-color: {bg_grid};
        border: none;
    }}

    QWidget#PdfViewerCanvas {{
        background-color: {bg_grid};
    }}

    QWidget#PdfViewerPage {{
        background-color: {VIEWER_PAGE_BG};
        border: 1px solid {border_subtle};
    }}

    QWidget#PdfViewerToolbar {{
        background-color: {bg_preview_footer};
        border-bottom: 1px solid {border_subtle};
    }}

    QFrame#PdfViewerAnnotRail {{
        background-color: {bg_surface};
        border-left: 1px solid {border_subtle};
    }}

    QLabel#PdfViewerAnnotRailTitle {{
        color: {text_secondary};
        font-size: 11px;
        font-weight: 600;
        padding: 2px 4px;
    }}

    QWidget#PdfViewerAnnotTools QToolButton {{
        text-align: left;
        padding: 5px 8px;
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        color: {text_secondary};
        background-color: transparent;
    }}

    QWidget#PdfViewerAnnotTools QToolButton:hover {{
        color: {text_primary};
        background-color: {bg_card_hover};
    }}

    QWidget#PdfViewerAnnotTools QToolButton:pressed {{
        color: {text_primary};
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QWidget#PdfViewerAnnotTools QToolButton:checked {{
        color: {text_primary};
        background-color: {bg_card};
        border: 1px solid {ACCENT};
    }}

    QWidget#PdfViewerAnnotTools QToolButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QToolButton#PdfViewerAnnotCollapse,
    QToolButton#PdfViewerAnnotExpand {{
        color: {text_muted};
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px;
        background-color: transparent;
    }}

    QToolButton#PdfViewerAnnotCollapse:hover,
    QToolButton#PdfViewerAnnotExpand:hover {{
        color: {text_primary};
        background-color: {bg_card_hover};
    }}

    QToolButton#PdfViewerAnnotCollapse:pressed,
    QToolButton#PdfViewerAnnotExpand:pressed {{
        color: {text_primary};
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QToolButton#PdfViewerAnnotCollapse:focus,
    QToolButton#PdfViewerAnnotExpand:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QFrame#PdfViewerRedactConfirm {{
        background-color: {bg_surface};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QToolButton#PdfViewerRedactConfirmBtn,
    QToolButton#PdfViewerRedactCancelBtn {{
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px;
        background-color: transparent;
    }}

    QToolButton#PdfViewerRedactConfirmBtn:hover,
    QToolButton#PdfViewerRedactCancelBtn:hover {{
        background-color: {bg_card_hover};
    }}

    QToolButton#PdfViewerRedactConfirmBtn:pressed,
    QToolButton#PdfViewerRedactCancelBtn:pressed {{
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QToolButton#PdfViewerRedactConfirmBtn:focus,
    QToolButton#PdfViewerRedactCancelBtn:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QFrame#FreeTextFormatBar {{
        background-color: {bg_surface};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QFrame#FreeTextFormatBar QLineEdit#FreeTextFormatText {{
        min-height: 24px;
        padding: 2px 6px;
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        background-color: {bg_card};
        color: {text_primary};
    }}

    QFrame#FreeTextFormatBar QLineEdit#FreeTextFormatText:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QFrame#FreeTextFormatBar QComboBox#FreeTextFormatFont,
    QFrame#FreeTextFormatBar QDoubleSpinBox#FreeTextFormatSize {{
        min-height: 24px;
        padding: 2px 4px;
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        background-color: {bg_card};
        color: {text_primary};
    }}

    QFrame#FreeTextFormatBar QComboBox#FreeTextFormatFont:focus,
    QFrame#FreeTextFormatBar QDoubleSpinBox#FreeTextFormatSize:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QToolButton#FreeTextFormatBold,
    QToolButton#FreeTextFormatItalic,
    QToolButton#FreeTextFormatColor,
    QToolButton#FreeTextFormatDelete {{
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px 6px;
        background-color: transparent;
        color: {text_primary};
        min-width: 24px;
    }}

    QToolButton#FreeTextFormatBold {{
        font-weight: 700;
    }}

    QToolButton#FreeTextFormatItalic {{
        font-style: italic;
    }}

    QToolButton#FreeTextFormatBold:hover,
    QToolButton#FreeTextFormatItalic:hover,
    QToolButton#FreeTextFormatColor:hover,
    QToolButton#FreeTextFormatDelete:hover {{
        background-color: {bg_card_hover};
    }}

    QToolButton#FreeTextFormatBold:pressed,
    QToolButton#FreeTextFormatItalic:pressed,
    QToolButton#FreeTextFormatColor:pressed,
    QToolButton#FreeTextFormatDelete:pressed {{
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QToolButton#FreeTextFormatBold:checked,
    QToolButton#FreeTextFormatItalic:checked {{
        background-color: {bg_card};
        border: 1px solid {ACCENT};
        color: {ACCENT};
    }}

    QToolButton#FreeTextFormatBold:focus,
    QToolButton#FreeTextFormatItalic:focus,
    QToolButton#FreeTextFormatColor:focus,
    QToolButton#FreeTextFormatDelete:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QTabWidget#PdfViewerSide {{
        background-color: {bg_surface};
        color: {text_primary};
    }}

    QTabWidget#PdfViewerSide::pane {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-top: none;
        padding: 4px;
    }}

    QTabWidget#PdfViewerSide > QTabBar {{
        background-color: {bg_surface};
        border-bottom: 1px solid {border_subtle};
    }}

    QTabWidget#PdfViewerSide > QTabBar::tab {{
        background-color: transparent;
        color: {text_muted};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 8px 12px 7px 12px;
        margin-right: 2px;
        font-weight: 500;
    }}

    QTabWidget#PdfViewerSide > QTabBar::tab:selected {{
        color: {text_primary};
        background-color: {bg_surface};
        border-bottom: 2px solid {ACCENT};
        font-weight: 600;
    }}

    QTabWidget#PdfViewerSide > QTabBar::tab:hover:!selected {{
        color: {text_secondary};
        background-color: {bg_card_hover};
    }}

    QLabel#PdfViewerHint {{
        color: {text_secondary};
        font-size: 11px;
        font-family: {FONT_MONO};
        padding: 10px 16px;
        background-color: {bg_preview_footer};
        border-top: 1px solid {border_subtle};
    }}

    QLabel#PdfViewerPageLabel,
    QLabel#PdfViewerHitLabel {{
        color: {text_secondary};
        font-size: 12px;
        padding: 0 8px;
    }}

    QWidget#BusyOverlay {{
        background-color: {busy_overlay_bg};
    }}

    QWidget#BusyOverlayPanel {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#BusyOverlayMessage {{
        color: {text_primary};
        font-size: 14px;
        font-weight: 600;
        background-color: transparent;
        border: none;
    }}

    QPushButton#BusyOverlayCancel {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 600;
        padding: 6px 16px;
        background-color: {bg_card};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QPushButton#BusyOverlayCancel:hover {{
        background-color: {bg_card_hover};
    }}

    QPushButton#BusyOverlayCancel:pressed {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}

    QWidget#ToastOverlay {{
        background-color: transparent;
    }}

    QWidget#ToastOverlayCard {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px 8px 4px 4px;
    }}

    QLabel#ToastOverlayMessage {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 600;
        padding: 8px 16px;
        background-color: transparent;
        border: none;
    }}

    QLabel#ToastOverlayMessage[kind="success"] {{
        color: {status_success};
    }}

    QLabel#ToastOverlayMessage[kind="error"] {{
        color: {close_tab};
    }}

    QLabel#ToastOverlayMessage[kind="warning"] {{
        color: {status_warning};
    }}

    QLabel#ToastOverlayMessage[kind="info"] {{
        color: {text_secondary};
    }}

    QPushButton#ToastOverlayUndo {{
        color: {text_primary};
        background-color: {bg_card};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 12px;
        font-weight: 600;
    }}

    QPushButton#ToastOverlayUndo:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QPushButton#ToastOverlayUndo:pressed {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}

    QWidget#TipsOverlay {{
        background-color: {busy_overlay_bg};
    }}

    QWidget#TipsOverlayCard {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#TipsOverlayTitle {{
        color: {text_primary};
        font-size: 18px;
        font-weight: 700;
    }}

    QLabel#TipsOverlayIntro {{
        color: {text_secondary};
        font-size: 13px;
    }}

    QLabel#TipsOverlayTip {{
        color: {text_primary};
        font-size: 13px;
    }}

    QLabel#ShortcutCategory {{
        color: {text_primary};
        font-size: 14px;
        font-weight: 700;
        padding-top: 4px;
    }}

    QLabel#ShortcutAction {{
        color: {text_secondary};
        font-size: 13px;
    }}

    QLabel#ShortcutKeys {{
        color: {text_primary};
        font-size: 12px;
        font-family: {FONT_MONO};
    }}

    QWidget#MergeListPane {{
        background-color: {bg_grid};
    }}

    QWidget#MergeEmptyState {{
        background-color: {bg_grid};
    }}

    QLabel#MergeEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 {SPACE_3}px 0;
    }}

    QLabel#MergeEmptyTitle {{
        color: {text_secondary};
        font-size: 15px;
        font-weight: 600;
        letter-spacing: -0.2px;
    }}

    QLabel#MergeEmptyHint {{
        color: {text_muted};
        font-size: 13px;
        font-weight: 400;
    }}

    QScrollArea#MergeFileGrid {{
        background-color: {bg_grid};
        border: none;
    }}

    QWidget#MergeFileGridContainer {{
        background-color: {bg_grid};
    }}

    QWidget#ConvertEmptyState {{
        background-color: {bg_grid};
    }}

    QLabel#ConvertEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 {SPACE_3}px 0;
    }}

    QLabel#ConvertEmptyTitle {{
        color: {text_secondary};
        font-size: 15px;
        font-weight: 600;
        letter-spacing: -0.2px;
    }}

    QLabel#ConvertEmptyHint {{
        color: {text_muted};
        font-size: 13px;
        font-weight: 400;
    }}

    QScrollArea#ConvertFileGrid {{
        background-color: {bg_grid};
        border: none;
    }}

    QWidget#ConvertFileGridContainer {{
        background-color: {bg_grid};
    }}

    QLabel#ConvertPreviewImage {{
        background-color: {VIEWER_PAGE_BG};
    }}

    QFrame#DropIndicator {{
        background-color: {ACCENT};
        border: none;
        border-radius: 2px;
    }}

    QLabel#ComparePaneTitle,
    QLabel#CompareSummary {{
        color: {text_secondary};
    }}

    QLabel#CompareModeLabel {{
        color: {ACCENT};
        font-weight: 600;
    }}

    QLabel#ToolsErrorHint {{
        color: {close_tab};
        font-size: 12px;
    }}

    QWidget#ToolsWindow {{
        background-color: {bg_base};
    }}

    QWidget#ToolsCatalogue {{
        background-color: {bg_base};
    }}

    QScrollArea#ToolsScroll {{
        background-color: {bg_base};
        border: none;
    }}

    QScrollArea#ToolsScroll > QWidget {{
        background-color: {bg_base};
    }}

    QLineEdit#ToolsSearch {{
        min-height: 32px;
    }}

    QLabel#ToolsCategoryHeading,
    QToolButton#ToolsCategoryHeading {{
        color: {text_secondary};
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.4px;
        border: none;
        border-bottom: 1px solid {border_subtle};
        background: transparent;
        padding: 0 0 6px 0;
        text-align: left;
    }}

    QToolButton#ToolsCategoryHeading:hover {{
        color: {text_primary};
    }}

    QLabel#ToolsMatchCount {{
        color: {text_muted};
        font-size: 12px;
    }}

    QToolButton#ToolsDensityToggle,
    QToolButton#ToolsUpcomingToggle {{
        color: {text_muted};
        font-size: 12px;
        border: none;
        background: transparent;
        padding: 2px 4px;
    }}

    QToolButton#ToolsDensityToggle:checked,
    QToolButton#ToolsUpcomingToggle:checked {{
        color: {ACCENT};
    }}

    QToolButton#ToolsDensityToggle:hover,
    QToolButton#ToolsUpcomingToggle:hover {{
        color: {text_secondary};
    }}

    QLabel#ToolsEmptyGlyph {{
        background: transparent;
        border: none;
        padding: 0;
    }}

    QLabel#ToolsEmptyState {{
        color: {text_muted};
        font-size: 13px;
        padding: 0;
    }}

    QWidget#ToolShellWindow {{
        background-color: {bg_base};
    }}

    QLabel#ToolShellTitle {{
        color: {text_primary};
        font-size: 18px;
        font-weight: 600;
        letter-spacing: -0.2px;
    }}

    QLabel#ToolShellDescription {{
        color: {text_secondary};
        font-size: 13px;
    }}

    /* Solid fill — transparent scroll + unthemed viewport reads charcoal under
       light chrome (same class of bug as pre-fix Watermark options). */
    QScrollArea#ToolShellOptionsScroll {{
        background-color: {bg_base};
        border: none;
    }}

    QScrollArea#ToolShellOptionsScroll > QWidget {{
        background-color: {bg_base};
    }}

    QWidget#ToolShellOptions {{
        background-color: {bg_base};
    }}

    /* R6: drop zone ghost/outline — same quiet language as #ToolbarSecondary. */
    QFrame#ToolShellDropZone {{
        background-color: transparent;
        border: 1px dashed {border_default};
        border-radius: {RADIUS_CARD}px;
    }}

    QFrame#ToolShellDropZone[dropActive="true"] {{
        border-color: {ACCENT};
        border-style: dashed;
        background-color: {bg_card_hover};
    }}

    QFrame#ToolShellDropZone:focus {{
        border: {focus_width}px dashed {ACCENT};
    }}

    QLabel#ToolShellDropPrompt {{
        color: {text_secondary};
        font-size: 14px;
        font-weight: 500;
    }}

    QLabel#ToolShellDropFiles {{
        color: {text_primary};
        font-size: 13px;
    }}

    QLabel#ToolShellDropPrivacy {{
        color: {text_muted};
        font-size: 12px;
    }}

    /* R6: result chrome hairline; action buttons mirror #ToolbarSecondary. */
    QWidget#ResultActionsBar {{
        background-color: transparent;
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#ResultActionsLabel {{
        color: {text_secondary};
        font-size: 13px;
    }}

    QPushButton#ResultActionsPreview,
    QPushButton#ResultActionsOpen,
    QPushButton#ResultActionsFolder {{
        background-color: transparent;
        color: {text_secondary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        font-weight: 600;
        padding: 6px 12px;
    }}

    QPushButton#ResultActionsPreview:hover,
    QPushButton#ResultActionsOpen:hover,
    QPushButton#ResultActionsFolder:hover {{
        background-color: {bg_card_hover};
        color: {text_primary};
        border-color: {border_hover};
    }}

    QPushButton#ResultActionsPreview:pressed,
    QPushButton#ResultActionsOpen:pressed,
    QPushButton#ResultActionsFolder:pressed {{
        background-color: {bg_pressed};
        color: {text_primary};
    }}

    QPushButton#ResultActionsPreview:focus,
    QPushButton#ResultActionsOpen:focus,
    QPushButton#ResultActionsFolder:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QPushButton#ResultActionsPreview:disabled,
    QPushButton#ResultActionsOpen:disabled,
    QPushButton#ResultActionsFolder:disabled {{
        color: {text_muted};
        border-color: {border_subtle};
        background-color: transparent;
    }}

    QLabel#ToolsHint {{
        color: {text_muted};
        font-size: 12px;
    }}

    /* Watermark split — Bento-style preview + options cards. */
    QFrame#WatermarkPreviewCard,
    QFrame#WatermarkOptionsCard {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CARD}px;
    }}

    QLabel#WatermarkPreviewTitle {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 600;
    }}

    QLabel#WatermarkZoomLabel {{
        color: {text_secondary};
        font-size: 12px;
        font-family: {FONT_MONO};
        min-width: 40px;
    }}

    QPushButton#WatermarkZoomButton {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: 0;
        font-weight: 600;
        min-width: 28px;
        max-width: 28px;
        min-height: 28px;
        max-height: 28px;
    }}

    QPushButton#WatermarkZoomButton:hover:enabled {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QPushButton#WatermarkZoomButton:pressed:enabled {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}

    QPushButton#WatermarkZoomButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QWidget#WatermarkKindToggle QToolButton {{
        padding: 6px 16px;
        min-width: 64px;
    }}

    /* Create PDF output mode — checkable peers beside toolbar actions. */
    QWidget#OutputModeHost QToolButton {{
        padding: 6px 12px;
    }}

    QScrollArea#WatermarkPreviewScroll {{
        background-color: {bg_surface};
        border: none;
    }}

    QScrollArea#WatermarkOptionsScroll {{
        background-color: transparent;
        border: none;
    }}

    QScrollArea#WatermarkPreviewScroll > QWidget {{
        background-color: {bg_surface};
    }}

    QScrollArea#WatermarkOptionsScroll > QWidget,
    QWidget#WatermarkOptionsForm {{
        background-color: {bg_surface};
    }}

    QWidget#WatermarkPreviewCanvas {{
        background-color: {bg_surface};
    }}

    QSlider#WatermarkSlider::groove:horizontal {{
        height: 4px;
        background: {border_subtle};
        border-radius: 2px;
    }}

    QSlider#WatermarkSlider::handle:horizontal {{
        background: {ACCENT};
        border: none;
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}

    QSlider#WatermarkSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}

    QSlider#WatermarkSlider:focus {{
        outline: none;
    }}

    /* Card / tile chrome — dynamic properties + :hover/:focus; no per-state setStyleSheet. */
    QFrame#PageCard,
    QFrame#MergeFileCard,
    QFrame#ConvertFileCard {{
        background-color: {bg_card};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#PageCard:hover,
    QFrame#MergeFileCard:hover,
    QFrame#ConvertFileCard:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}
    QFrame#PageCard[focused="true"],
    QFrame#MergeFileCard[focused="true"],
    QFrame#ConvertFileCard[focused="true"] {{
        border: {focus_width}px solid {ACCENT};
    }}
    QFrame#PageCard[selected="true"],
    QFrame#MergeFileCard[selected="true"],
    QFrame#ConvertFileCard[selected="true"] {{
        border: {selected_width}px solid {ACCENT};
    }}
    QFrame#PageCard[selected="true"]:hover,
    QFrame#MergeFileCard[selected="true"]:hover,
    QFrame#ConvertFileCard[selected="true"]:hover {{
        border-color: {ACCENT_HOVER};
    }}
    QLabel#PageCardThumbnail {{
        background-color: {bg_thumb_empty};
        border-radius: {RADIUS_BADGE}px;
    }}
    QLabel#PageCardLabel {{
        color: {text_secondary};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}
    QFrame#PageCard[selected="true"] QLabel#PageCardLabel {{
        color: {text_primary};
    }}
    QLabel#PageCardPageOverlay {{
        color: {TEXT_ON_ACCENT};
        background-color: {page_chip_bg};
        font-size: 11px;
        font-weight: 600;
        padding: {SPACE_1}px {SPACE_2}px;
        border-radius: {SPACE_1}px;
    }}
    QLabel#PageCardRotationOverlay {{
        color: {TEXT_ON_ACCENT};
        background-color: {page_chip_bg};
        font-family: {FONT_MONO};
        font-size: 10px;
        font-weight: 600;
        padding: {SPACE_1}px {SPACE_1}px;
        border-radius: {SPACE_1}px;
    }}

    QLabel#PreferencesSection {{
        color: {text_muted};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
        padding-top: {SPACE_1}px;
    }}

    QFrame#PreferencesDivider {{
        background-color: {border_subtle};
        border: none;
        max-height: 1px;
        margin: {SPACE_2}px 0;
    }}
    QLabel#MergeFileCardThumbnail,
    QLabel#ConvertFileCardThumbnail {{
        background-color: transparent;
        border: none;
    }}
    QLabel#MergeFileCardTitle,
    QLabel#ConvertFileCardTitle {{
        color: {text_primary};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#MergeFileCardSubtitle,
    QLabel#ConvertFileCardSubtitle {{
        color: {text_muted};
        font-size: 11px;
        font-weight: 500;
    }}
    QFrame#MergeFileCard[selected="true"] QLabel#MergeFileCardSubtitle,
    QFrame#ConvertFileCard[selected="true"] QLabel#ConvertFileCardSubtitle {{
        color: {text_secondary};
    }}

    /* R6: ToolTiles — quieter rest/hover; keep HC-aware focus rings. */
    QFrame#ToolTile {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#ToolTile:hover {{
        background-color: {bg_card};
        border-color: {border_subtle};
    }}
    QFrame#ToolTile[pressed="true"] {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}
    QFrame#ToolTile[blocked="true"],
    QFrame#ToolTile[comingSoon="true"] {{
        background-color: transparent;
        border-color: transparent;
    }}
    QFrame#ToolTile[blocked="true"]:hover,
    QFrame#ToolTile[comingSoon="true"]:hover,
    QFrame#ToolTile[blocked="true"][pressed="true"],
    QFrame#ToolTile[comingSoon="true"][pressed="true"] {{
        background-color: transparent;
        border-color: transparent;
    }}
    QFrame#ToolTile:focus {{
        background-color: {bg_card};
        border: {focus_width}px solid {ACCENT};
    }}
    QFrame#ToolTile[blocked="true"]:focus,
    QFrame#ToolTile[comingSoon="true"]:focus {{
        background-color: transparent;
        border: {focus_width}px solid {ACCENT};
    }}
    QFrame#ToolTile[compact="true"] {{
        border-radius: {max(6, RADIUS_CARD - 2)}px;
    }}
    QLabel#ToolTileTitle {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 600;
        letter-spacing: -0.1px;
    }}
    QFrame#ToolTile[blocked="true"] QLabel#ToolTileTitle,
    QFrame#ToolTile[comingSoon="true"] QLabel#ToolTileTitle {{
        color: {text_muted};
    }}
    QFrame#ToolTile[compact="true"] QLabel#ToolTileTitle {{
        font-size: 12px;
    }}
    QLabel#ToolTileSubtitle {{
        color: {text_muted};
        font-size: 11px;
        font-weight: 400;
    }}
    QFrame#ToolTile[compact="true"] QLabel#ToolTileSubtitle {{
        font-size: 10px;
    }}
    """


def token_qcolor(hex_color: str, alpha: int = 255) -> "QColor":
    """Theme hex (#RRGGBB) → QColor, optional alpha for overlays."""
    from PyQt6.QtGui import QColor

    color = QColor(hex_color)
    if alpha < 255:
        color.setAlpha(max(0, min(255, alpha)))
    return color


def accent_qcolor(*, alpha: int = 255) -> "QColor":
    """Accent color for programmatic painting (drag badge, etc.)."""
    return token_qcolor(ACCENT, alpha)


def on_accent_qcolor() -> "QColor":
    """Ink color for text/icons drawn on top of the accent background."""
    return token_qcolor(TEXT_ON_ACCENT)


def shadow_qcolor(*, alpha: int = 55) -> "QColor":
    """Tinted drop-shadow color (pairs with light/dark chrome; not QSS)."""
    from PyQt6.QtGui import QColor

    from pagedrop.ui.settings import light_theme

    if light_theme():
        r, g, b = SHADOW_RGB_LIGHT
        return QColor(r, g, b, min(alpha, SHADOW_ALPHA_CAP_LIGHT))
    r, g, b = SHADOW_RGB
    return QColor(r, g, b, alpha)


def border_hover_qcolor() -> "QColor":
    """Theme-aware hover/stack border for programmatic paint (not QSS).

    Do not use ``token_qcolor(BORDER_HOVER)`` alone — that hex is dark-only and
    stays stale after a light/dark toggle. Light uses ``BORDER_HOVER_LIGHT``,
    the same token as ``app_stylesheet(light=True)``.
    """
    from pagedrop.ui.settings import light_theme

    return token_qcolor(BORDER_HOVER_LIGHT if light_theme() else BORDER_HOVER)


def chrome_card_qcolor() -> "QColor":
    """Card/surface fill for programmatic paint (pairs with light/dark QSS)."""
    from pagedrop.ui.settings import light_theme

    return token_qcolor(BG_CARD_LIGHT if light_theme() else BG_CARD)


def chrome_text_muted_qcolor() -> "QColor":
    """Muted chrome ink for programmatic paint (pairs with light/dark QSS)."""
    from pagedrop.ui.settings import light_theme

    return token_qcolor(TEXT_MUTED_LIGHT if light_theme() else TEXT_MUTED)


def status_success_hex() -> str:
    """Success ink for toast/list text — darkened under light chrome for AA."""
    from pagedrop.ui.settings import light_theme

    return STATUS_SUCCESS_LIGHT if light_theme() else STATUS_SUCCESS


def status_warning_hex() -> str:
    """Warning ink for toast/list text — darkened under light chrome for AA."""
    from pagedrop.ui.settings import light_theme

    return STATUS_WARNING_LIGHT if light_theme() else STATUS_WARNING


def close_tab_hex() -> str:
    """Destructive / close-tab red (pairs with light/dark QSS)."""
    from pagedrop.ui.settings import light_theme

    return CLOSE_TAB_LIGHT if light_theme() else CLOSE_TAB


def tab_close_icon(*, color: str | None = None) -> "QIcon":
    """Red × icon for tab close buttons (Phosphor ``x``, destructive tint)."""
    from pagedrop.ui import icons

    ink = color if color is not None else close_tab_hex()
    return icons.icon("x", color=ink)
