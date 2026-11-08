"""PageDrop visual design tokens and Qt Style Sheets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtGui import QColor, QFont, QIcon
    from PyQt6.QtWidgets import QApplication

@dataclass(frozen=True)
class Theme:
    """One complete colour set; every chrome colour is read from here."""

    chrome: str
    raised: str
    canvas: str
    bar_top: str
    bar_tabs: str
    line: str
    line_strong: str
    text: str
    text_muted: str
    on_bar: str
    on_bar_muted: str
    ink: str
    ink_hover: str
    ink_pressed: str
    on_ink: str
    ink_tint: str
    focus: str
    success: str
    warning: str
    danger: str
    index_clay: str
    index_teal: str
    index_ochre: str
    index_plum: str
    index_moss: str
    index_slate: str
    on_index: str


LIGHT = Theme(
    chrome="#FAF9F7",
    raised="#FFFFFF",
    canvas="#E9E7E2",
    bar_top="#F0EEE9",
    bar_tabs="#E6E3DC",
    line="#D8D5CE",
    line_strong="#7F7C74",
    text="#1E2226",
    text_muted="#4C5258",
    on_bar="#22262A",
    on_bar_muted="#555B61",
    ink="#1F4E79",
    ink_hover="#17406A",
    ink_pressed="#12345A",
    on_ink="#FFFFFF",
    ink_tint="#DDE7F1",
    focus="#1E2226",
    success="#1A743A",
    warning="#845E00",
    danger="#B3261E",
    index_clay="#B4432F",
    index_teal="#1F6F6B",
    index_ochre="#8A6200",
    index_plum="#6B4A8E",
    index_moss="#3F6B2F",
    index_slate="#5A6470",
    on_index="#FFFFFF",
)

DARK = Theme(
    chrome="#222528",
    raised="#2A2E31",
    canvas="#16181A",
    bar_top="#1A1C1E",
    bar_tabs="#212427",
    line="#393D41",
    line_strong="#71777C",
    text="#EDEEEF",
    text_muted="#B9BDC1",
    on_bar="#ECEDEE",
    on_bar_muted="#A7ACB0",
    ink="#82B4E0",
    ink_hover="#9AC4E8",
    ink_pressed="#6FA3D2",
    on_ink="#0B2236",
    ink_tint="#1F3347",
    focus="#EDEEEF",
    success="#62CC8E",
    warning="#E4BA5A",
    danger="#F2A29A",
    index_clay="#EE8F7C",
    index_teal="#63C9C2",
    index_ochre="#E4BA5A",
    index_plum="#C3A6E6",
    index_moss="#A5D08A",
    index_slate="#AEB8C2",
    on_index="#21100C",
)


def current_theme() -> Theme:
    """The chrome theme the user (or the OS) currently selects."""
    from pagedrop.ui.settings import light_theme

    return LIGHT if light_theme() else DARK


def rgba(hex_color: str, alpha: int) -> str:
    """QSS ``rgba()`` for a theme hex plus an 0-255 alpha."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def blend(foreground: str, background: str, weight: float) -> str:
    """Solid ``#RRGGBB`` of ``foreground`` over ``background`` at ``weight``."""
    f = foreground.lstrip("#")
    b = background.lstrip("#")
    mixed = (
        round(int(f[i : i + 2], 16) * weight + int(b[i : i + 2], 16) * (1 - weight))
        for i in (0, 2, 4)
    )
    return "#" + "".join(f"{c:02X}" for c in mixed)


# Legacy names stay as aliases: dark names read DARK, ``*_LIGHT`` names read LIGHT.
BG_BASE = BG_SURFACE = BG_PREVIEW_FOOTER = DARK.chrome
BG_GRID = DARK.canvas
BG_CARD = DARK.raised
BG_CARD_HOVER = DARK.ink_tint
BG_TOOLBAR = BG_STATUS = DARK.bar_top
BG_TAB_BAR = DARK.bar_tabs

# Semantic surface roles. Keep these named by purpose so document-oriented
# widgets do not need to infer a colour from generic application-card tokens.
SURFACE_QUIET_CHROME = BG_SURFACE
SURFACE_DOCUMENT_CANVAS = BG_GRID
SURFACE_RAISED = BG_CARD

BORDER_SUBTLE = DARK.line
BORDER_DEFAULT = BORDER_HOVER = DARK.line_strong
BORDER_HOVER_LIGHT = LIGHT.line_strong
FOCUS_RING = DARK.focus
FOCUS_RING_LIGHT = LIGHT.focus

ACCENT = PRIMARY = DARK.ink
ACCENT_HOVER = DARK.ink_hover
ACCENT_PRESSED = DARK.ink_pressed

TEXT_PRIMARY = DARK.text
TEXT_SECONDARY = TEXT_MUTED = DARK.text_muted
# Ink on accent / filled interactive chrome (labels, selection text, focus rings)
TEXT_ON_ACCENT = ON_PRIMARY = DARK.on_ink

# Shared semantic roles for widget code.
BACKGROUND = BG_BASE
FOREGROUND = TEXT_PRIMARY
MUTED_FOREGROUND = TEXT_MUTED
BORDER = BORDER_DEFAULT
INPUT = BG_CARD
DOCUMENT_CANVAS = SURFACE_DOCUMENT_CANVAS
RAISED_SURFACE = SURFACE_RAISED

TEXT_PRIMARY_LIGHT = LIGHT.text
TEXT_SECONDARY_LIGHT = TEXT_MUTED_LIGHT = LIGHT.text_muted
BG_CARD_LIGHT = LIGHT.raised
BG_BASE_LIGHT = LIGHT.chrome
BG_GRID_LIGHT = LIGHT.canvas
SURFACE_QUIET_CHROME_LIGHT = LIGHT.chrome
SURFACE_DOCUMENT_CANVAS_LIGHT = BG_GRID_LIGHT
SURFACE_RAISED_LIGHT = BG_CARD_LIGHT

BACKGROUND_LIGHT = BG_BASE_LIGHT
FOREGROUND_LIGHT = TEXT_PRIMARY_LIGHT
MUTED_FOREGROUND_LIGHT = TEXT_MUTED_LIGHT
BORDER_LIGHT = LIGHT.line
INPUT_LIGHT = BG_CARD_LIGHT
DOCUMENT_CANVAS_LIGHT = SURFACE_DOCUMENT_CANVAS_LIGHT
RAISED_SURFACE_LIGHT = SURFACE_RAISED_LIGHT

CLOSE_TAB = DARK.danger
CLOSE_TAB_LIGHT = LIGHT.danger

# Semantic status (compare diffs, validation errors, toast kinds)
STATUS_SUCCESS = DARK.success
STATUS_WARNING = DARK.warning
STATUS_SUCCESS_LIGHT = LIGHT.success
STATUS_WARNING_LIGHT = LIGHT.warning

# Page plane: the page stays white and its marks stay dark in both themes.
SURFACE_PAPER = "#FFFFFF"
VIEWER_PAGE_BG = SURFACE_PAPER
PAGE_INK = "#141414"
# Selection / handle marks drawn on the page: light-theme ink in both themes,
# since the page behind them is always white.
PAGE_ACCENT = LIGHT.ink
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

# The shared metrics are minimums, never fixed heights, so translated or
# enlarged labels can grow. Keep the legacy radius names as aliases for the
# existing component stylesheet.
COMPACT_CONTROL_HEIGHT = 32
FORM_CONTROL_HEIGHT = 36
ICON_SIZE_SMALL = 16
ICON_SIZE = 18
# Marks are drawn at their own size inside the 16px indicator, not scaled to fill it.
INDICATOR_CHECK_SIZE = 12
INDICATOR_DOT_SIZE = 8
INDICATOR_ARROW_SIZE = 10
FORM_BUTTON_WIDTH = 24
RADIUS_CONTROL = 4
RADIUS_SURFACE = 6
RADIUS_CARD = RADIUS_SURFACE
RADIUS_BADGE = 3

# Bundled Public Sans leads; later families cover scripts it lacks (CJK, etc.).
FONT_UI_FAMILIES = ("Public Sans", "Segoe UI", "Noto Sans")
FONT_UI = ", ".join(f'"{name}"' for name in FONT_UI_FAMILIES) + ", sans-serif"

# Spacing scale (4px steps) — toolbar / grid / empty-state rhythm
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32
SPACE_7 = 48

COMPACT_CONTROL_VERTICAL_PADDING = 5
FORM_CONTROL_VERTICAL_PADDING = 7
# Qt styles ``min-height`` as the content area; this preserves the visible
# 36 px single-line form-control target after padding and borders.
FORM_CONTROL_CONTENT_HEIGHT = FORM_CONTROL_HEIGHT - (
    2 * FORM_CONTROL_VERTICAL_PADDING + 2
)

CARD_PADDING = SPACE_4
DEFAULT_THUMBNAIL_WIDTH = 160
MIN_THUMBNAIL_WIDTH = 80
MAX_THUMBNAIL_WIDTH = 480
ZOOM_WHEEL_STEP = 16
# Below-card labels are easy to miss once thumbnails get large.
PAGE_NUMBER_OVERLAY_MIN_WIDTH = DEFAULT_THUMBNAIL_WIDTH + ZOOM_WHEEL_STEP * 5
MIN_PREVIEW_RENDER_WIDTH = 400
CARD_WIDTH = DEFAULT_THUMBNAIL_WIDTH + CARD_PADDING

def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance for a #RRGGBB color."""
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _indicator_image(name: str, color: str, size: int, canvas: int | None = None) -> str:
    """QSS ``image:`` rule for a tinted indicator, or nothing if it cannot be rendered."""
    from pagedrop.ui import icons

    path = icons.indicator_path(name, color=color, size=size, canvas=canvas)
    return f'image: url("{path}");' if path else ""


def app_stylesheet(*, high_contrast: bool = False, light: bool = False) -> str:
    # High contrast is an overlay on either theme: all text in ``text`` and
    # surface edges drawn in ``text``, with a thicker focus ring.
    t = LIGHT if light else DARK
    bg_base = bg_surface = bg_preview_footer = t.chrome
    bg_float = bg_card = t.raised
    bg_grid = t.canvas
    bg_card_hover = t.ink_tint
    bg_pressed = bg_thumb_empty = t.line
    bg_toolbar = bg_status = bg_bar = t.bar_top
    bg_tab_bar = t.bar_tabs
    text_primary = t.text
    on_bar = t.text if high_contrast else t.on_bar
    text_muted = t.text if high_contrast else t.text_muted
    on_bar_muted = t.text if high_contrast else t.on_bar_muted
    border_subtle = t.text if high_contrast else t.line
    border_default = border_hover = t.text if high_contrast else t.line_strong
    ink, ink_hover, ink_pressed, on_ink = t.ink, t.ink_hover, t.ink_pressed, t.on_ink
    focus_ring = t.focus
    # Ring for a focused item on an ink fill; the focus colour cannot contrast
    # with it, so use the ink label colour.
    selected_focus_ring = on_ink
    close_tab = t.danger
    close_pressed_bg = blend(t.danger, t.text, 0.8)
    # QSS has no opacity: disabled controls are drawn as the enabled colours
    # blended half-way into the chrome they sit on.
    disabled_text = text_muted if high_contrast else blend(t.text, t.chrome, 0.5)
    primary_disabled_bg = blend(ink, t.chrome, 0.5)
    primary_disabled_text = blend(on_ink, t.chrome, 0.5)
    close_hover_bg = blend(t.danger, bg_bar, 0.14)
    close_tab_hover_bg = blend(t.danger, bg_tab_bar, 0.14)
    close_tab_pressed_bg = blend(t.danger, bg_tab_bar, 0.26)
    status_success = t.success
    status_warning = t.warning
    busy_overlay_bg = rgba(t.chrome, 200 if light else 180)
    # Chips sit on page-paper thumbs (always light): a page-ink pill in both themes.
    page_chip_bg = rgba(PAGE_INK, 170 if light else 160)
    focus_width = 3 if high_contrast else 2
    mark_disabled = blend(text_muted, bg_card, 0.5)
    check_mark = _indicator_image("check-bold", on_ink, INDICATOR_CHECK_SIZE, ICON_SIZE_SMALL)
    check_mark_off = _indicator_image("check-bold", mark_disabled, INDICATOR_CHECK_SIZE, ICON_SIZE_SMALL)
    dot_mark = _indicator_image("circle-fill", on_ink, INDICATOR_DOT_SIZE, ICON_SIZE_SMALL)
    dot_mark_off = _indicator_image("circle-fill", mark_disabled, INDICATOR_DOT_SIZE, ICON_SIZE_SMALL)
    arrow_down = _indicator_image("caret-down-bold", text_muted, INDICATOR_ARROW_SIZE)
    arrow_down_off = _indicator_image("caret-down-bold", mark_disabled, INDICATOR_ARROW_SIZE)
    arrow_up = _indicator_image("caret-up-bold", text_muted, INDICATOR_ARROW_SIZE)
    arrow_up_off = _indicator_image("caret-up-bold", mark_disabled, INDICATOR_ARROW_SIZE)
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
        border-radius: {RADIUS_CONTROL}px;
        padding: {SPACE_1}px {SPACE_2}px;
    }}

    QWidget#WindowTitleBar {{
        background-color: {bg_bar};
        border-bottom: 1px solid {border_subtle};
    }}

    QMenuBar {{
        background-color: {bg_bar};
        color: {on_bar};
        padding: 2px 0;
    }}

    QMenuBar::item {{
        background: transparent;
        padding: {COMPACT_CONTROL_VERTICAL_PADDING}px {SPACE_3}px;
        border-radius: {RADIUS_CONTROL}px;
        border: {focus_width}px solid transparent;
    }}

    /* no ::item:focus — Qt marks every menubar item focused at once */
    QMenuBar::item:selected {{
        background-color: {bg_card_hover};
        border-color: {focus_ring};
    }}

    QWidget#WindowControls {{
        background: transparent;
    }}

    QLabel#WindowTitle {{
        color: {on_bar_muted};
        font-weight: 500;
        padding: 0 8px;
    }}

    QToolButton#WindowMinimize,
    QToolButton#WindowMaximize,
    QToolButton#WindowClose {{
        min-width: 30px;
        max-width: 30px;
        min-height: 26px;
        max-height: 26px;
        padding: 0;
        border: {focus_width}px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        background: transparent;
        color: {on_bar};
    }}

    QToolButton#WindowMinimize:focus,
    QToolButton#WindowMaximize:focus,
    QToolButton#WindowClose:focus {{
        border-color: {focus_ring};
    }}

    QToolButton#WindowMinimize:hover,
    QToolButton#WindowMaximize:hover,
    QToolButton#WindowMaximize[nativeHover="true"] {{
        background-color: {bg_card_hover};
    }}

    QToolButton#WindowClose:hover {{
        background-color: {close_hover_bg};
        color: {close_tab};
    }}

    QMenu {{
        background-color: {bg_float};
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_SURFACE}px;
        padding: {SPACE_1}px;
    }}

    QMenu::item {{
        padding: {SPACE_2}px 28px {SPACE_2}px {SPACE_4}px;
        border-radius: {RADIUS_CONTROL}px;
        border: {focus_width}px solid transparent;
    }}

    QMenu::item:selected {{
        background-color: {bg_card_hover};
        border-color: {focus_ring};
    }}

    QMenu::separator {{
        height: 1px;
        background: {border_subtle};
        margin: {SPACE_1}px {SPACE_2}px;
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
        padding: {FORM_CONTROL_VERTICAL_PADDING}px {SPACE_2}px;
        min-height: {FORM_CONTROL_CONTENT_HEIGHT}px;
        selection-background-color: {ink};
        selection-color: {on_ink};
    }}

    QLineEdit:focus {{
        border: {focus_width}px solid {focus_ring};
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

    /* The transparent border is paid for out of the padding, so the focus
       ring never changes an item's size. */
    QListWidget::item,
    QTreeWidget::item {{
        padding: {8 - focus_width}px {10 - focus_width}px;
        border: {focus_width}px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        color: {text_primary};
    }}

    QListWidget::item:selected,
    QTreeWidget::item:selected {{
        background-color: {ink};
        color: {on_ink};
    }}

    QListWidget::item:focus,
    QTreeWidget::item:focus {{
        border-color: {focus_ring};
    }}

    /* Selected items fill with ACCENT, which the ring cannot contrast with. */
    QListWidget::item:selected:focus,
    QTreeWidget::item:selected:focus {{
        border-color: {selected_focus_ring};
    }}

    QListWidget::item:hover:!selected,
    QTreeWidget::item:hover:!selected {{
        background-color: {bg_card_hover};
    }}

    QLabel#CommandPaletteHint {{
        color: {text_muted};
        font-size: 12px;
    }}

    QPushButton {{
        background-color: transparent;
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 14px;
        font-weight: 500;
    }}

    QPushButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QPushButton:pressed {{
        background-color: {bg_pressed};
    }}

    QPushButton:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QPushButton:disabled {{
        background-color: transparent;
        color: {disabled_text};
        border-color: {border_subtle};
    }}

    QCheckBox,
    QRadioButton {{
        color: {text_primary};
        spacing: {SPACE_2}px;
        border: none;
        background-color: transparent;
        outline: none;
    }}

    QCheckBox::indicator,
    QRadioButton::indicator {{
        width: {ICON_SIZE_SMALL}px;
        height: {ICON_SIZE_SMALL}px;
        border: 1px solid {border_default};
        background-color: {bg_card};
    }}

    QCheckBox::indicator {{
        border-radius: {RADIUS_BADGE}px;
    }}

    QRadioButton::indicator {{
        border-radius: 8px;
    }}

    QCheckBox::indicator:hover,
    QRadioButton::indicator:hover {{
        background-color: {bg_card_hover};
    }}

    QCheckBox::indicator:pressed,
    QRadioButton::indicator:pressed {{
        background-color: {bg_pressed};
    }}

    QCheckBox::indicator:disabled,
    QRadioButton::indicator:disabled {{
        background-color: {bg_card};
        border-color: {border_subtle};
    }}

    QCheckBox::indicator:checked,
    QRadioButton::indicator:checked {{
        background-color: {ink};
        border-color: {ink_pressed};
    }}

    QCheckBox::indicator:checked {{
        {check_mark}
    }}

    QRadioButton::indicator:checked {{
        {dot_mark}
    }}

    QCheckBox::indicator:checked:hover,
    QRadioButton::indicator:checked:hover {{
        background-color: {ink_hover};
    }}

    QCheckBox::indicator:checked:pressed,
    QRadioButton::indicator:checked:pressed {{
        background-color: {ink_pressed};
    }}

    QCheckBox::indicator:checked:disabled,
    QRadioButton::indicator:checked:disabled {{
        background-color: {bg_card};
        border-color: {border_subtle};
    }}

    QCheckBox::indicator:checked:disabled {{
        {check_mark_off}
    }}

    QRadioButton::indicator:checked:disabled {{
        {dot_mark_off}
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
        border: {focus_width}px solid {focus_ring};
    }}

    QComboBox {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px {SPACE_2}px;
        min-height: {FORM_CONTROL_CONTENT_HEIGHT}px;
    }}

    QComboBox:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        border: none;
        width: {FORM_BUTTON_WIDTH}px;
    }}

    QComboBox::down-arrow {{
        {arrow_down}
    }}

    QComboBox::down-arrow:disabled {{
        {arrow_down_off}
    }}

    QComboBox QAbstractItemView {{
        background-color: {bg_surface};
        color: {text_primary};
        border: 1px solid {border_subtle};
        selection-background-color: {ink};
        selection-color: {on_ink};
    }}

    QSpinBox,
    QDoubleSpinBox {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 8px;
        selection-background-color: {ink};
        selection-color: {on_ink};
    }}

    QSpinBox:focus,
    QDoubleSpinBox:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QSpinBox::up-button,
    QDoubleSpinBox::up-button {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: {FORM_BUTTON_WIDTH}px;
        border: none;
        border-top-right-radius: {RADIUS_CONTROL}px;
        background-color: transparent;
    }}

    QSpinBox::down-button,
    QDoubleSpinBox::down-button {{
        subcontrol-origin: padding;
        subcontrol-position: bottom right;
        width: {FORM_BUTTON_WIDTH}px;
        border: none;
        border-bottom-right-radius: {RADIUS_CONTROL}px;
        background-color: transparent;
    }}

    QSpinBox::up-button:hover,
    QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover,
    QDoubleSpinBox::down-button:hover {{
        background-color: {bg_card_hover};
    }}

    QSpinBox::up-button:pressed,
    QSpinBox::down-button:pressed,
    QDoubleSpinBox::up-button:pressed,
    QDoubleSpinBox::down-button:pressed {{
        background-color: {bg_pressed};
    }}

    QSpinBox::up-arrow,
    QDoubleSpinBox::up-arrow {{
        {arrow_up}
    }}

    QSpinBox::down-arrow,
    QDoubleSpinBox::down-arrow {{
        {arrow_down}
    }}

    QSpinBox::up-arrow:disabled,
    QSpinBox::up-arrow:off,
    QDoubleSpinBox::up-arrow:disabled,
    QDoubleSpinBox::up-arrow:off {{
        {arrow_up_off}
    }}

    QSpinBox::down-arrow:disabled,
    QSpinBox::down-arrow:off,
    QDoubleSpinBox::down-arrow:disabled,
    QDoubleSpinBox::down-arrow:off {{
        {arrow_down_off}
    }}

    QTextEdit {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 8px 10px;
        selection-background-color: {ink};
        selection-color: {on_ink};
    }}

    QPlainTextEdit,
    QTextBrowser {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 8px 10px;
        selection-background-color: {ink};
        selection-color: {on_ink};
    }}

    QPlainTextEdit:focus,
    QTextEdit:focus,
    QTextBrowser:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    /* Shared input states. Hover never overrides focus; a read-only
       QTextBrowser is a display surface, so it only gets the disabled look. */
    QLineEdit:hover:!focus:enabled,
    QComboBox:hover:!focus:enabled,
    QSpinBox:hover:!focus:enabled,
    QDoubleSpinBox:hover:!focus:enabled,
    QTextEdit:hover:!focus:enabled,
    QPlainTextEdit:hover:!focus:enabled {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QTextBrowser:hover:!focus:enabled {{
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QLineEdit:disabled,
    QComboBox:disabled,
    QSpinBox:disabled,
    QDoubleSpinBox:disabled,
    QTextEdit:disabled,
    QPlainTextEdit:disabled,
    QTextBrowser:disabled {{
        background-color: {bg_surface};
        color: {disabled_text};
        border: 1px solid {border_subtle};
    }}

    /* One dynamic error state, last so a focused field keeps its 2px focus
       width in the danger colour. */
    QLineEdit[error="true"],
    QComboBox[error="true"],
    QSpinBox[error="true"],
    QDoubleSpinBox[error="true"],
    QTextEdit[error="true"],
    QPlainTextEdit[error="true"],
    QLineEdit[error="true"]:hover:!focus:enabled,
    QComboBox[error="true"]:hover:!focus:enabled,
    QSpinBox[error="true"]:hover:!focus:enabled,
    QDoubleSpinBox[error="true"]:hover:!focus:enabled,
    QTextEdit[error="true"]:hover:!focus:enabled,
    QPlainTextEdit[error="true"]:hover:!focus:enabled {{
        border-color: {close_tab};
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
        color: {text_muted};
    }}

    /* Encrypt permissions — surface + card radius so it matches section language. */
    QGroupBox#EncryptPermissions {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CARD}px;
    }}

    QGroupBox#EncryptPermissions::title {{
        color: {text_muted};
    }}

    QToolBar {{
        background-color: {bg_toolbar};
        border: none;
        border-bottom: 1px solid {border_subtle};
        spacing: {SPACE_2}px;
        padding: {SPACE_2}px {SPACE_3}px;
    }}

    /* Ghost buttons: viewer chrome uses QToolButton outside QToolBar; keep both in sync. */
    QToolButton,
    QToolBar QToolButton {{
        background-color: transparent;
        color: {text_primary};
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        padding: {COMPACT_CONTROL_VERTICAL_PADDING}px {SPACE_2}px;
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
        border: {focus_width}px solid {focus_ring};
    }}

    /* Checked layout modes are a quiet state, not a second primary action. */
    QToolButton:checked {{
        background-color: {bg_card_hover};
        color: {text_primary};
        border: 1px solid {ink};
        font-weight: 500;
    }}

    QToolButton:checked:hover {{
        background-color: {bg_pressed};
        border-color: {ink_hover};
    }}

    QToolButton:checked:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QToolButton:disabled,
    QToolBar QToolButton:disabled {{
        color: {disabled_text};
        background-color: transparent;
        border-color: transparent;
    }}

    QPushButton#ToolbarPrimary,
    QPushButton#EmptyStateOpenButton,
    QToolBar QToolButton#ToolbarPrimary {{
        background-color: {ink};
        color: {on_ink};
        border: 1px solid {ink_pressed};
        font-weight: 600;
        padding: 6px 14px;
    }}

    QPushButton#ToolbarPrimary:hover,
    QPushButton#EmptyStateOpenButton:hover,
    QToolBar QToolButton#ToolbarPrimary:hover {{
        background-color: {ink_hover};
        border-color: {ink_hover};
    }}

    QPushButton#ToolbarPrimary:pressed,
    QPushButton#EmptyStateOpenButton:pressed,
    QToolBar QToolButton#ToolbarPrimary:pressed {{
        background-color: {ink_pressed};
        border-color: {ink_pressed};
    }}

    QPushButton#ToolbarPrimary:focus,
    QPushButton#EmptyStateOpenButton:focus,
    QToolBar QToolButton#ToolbarPrimary:focus {{
        border: {focus_width}px solid {on_ink};
    }}

    QPushButton#ToolbarPrimary:disabled,
    QPushButton#EmptyStateOpenButton:disabled,
    QToolBar QToolButton#ToolbarPrimary:disabled {{
        background-color: {primary_disabled_bg};
        color: {primary_disabled_text};
        border-color: {primary_disabled_bg};
    }}

    /* A finished output is the task's primary destination; rerun is quiet. */
    QPushButton#ToolbarPrimary[resultAvailable="true"],
    QToolBar QToolButton#ToolbarPrimary[resultAvailable="true"] {{
        background-color: transparent;
        color: {text_muted};
        border-color: {border_default};
    }}

    QPushButton#ToolbarPrimary[resultAvailable="true"]:hover,
    QToolBar QToolButton#ToolbarPrimary[resultAvailable="true"]:hover {{
        background-color: {bg_card_hover};
        color: {text_primary};
        border-color: {border_hover};
    }}

    QPushButton#ToolbarPrimary[resultAvailable="true"]:disabled,
    QToolBar QToolButton#ToolbarPrimary[resultAvailable="true"]:disabled {{
        background-color: transparent;
        color: {disabled_text};
        border-color: {border_subtle};
    }}

    /* Secondary: outlined, same look as the default QPushButton. */
    QPushButton#ToolbarSecondary,
    QToolBar QToolButton#ToolbarSecondary {{
        background-color: transparent;
        color: {text_primary};
        border: 1px solid {border_default};
        font-weight: 500;
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
        border: {focus_width}px solid {focus_ring};
    }}

    QPushButton#ToolbarSecondary:disabled,
    QToolBar QToolButton#ToolbarSecondary:disabled {{
        color: {disabled_text};
        border-color: {border_subtle};
        background-color: transparent;
    }}

    /* Destructive controls use text, role, and a distinct color treatment. */
    QPushButton[destructive="true"] {{
        color: {close_tab};
        border-color: {close_tab};
        background-color: transparent;
    }}

    QPushButton[destructive="true"]:hover {{
        color: {on_ink};
        border-color: {close_tab};
        background-color: {close_tab};
    }}

    QPushButton[destructive="true"]:pressed {{
        color: {on_ink};
        border-color: {close_pressed_bg};
        background-color: {close_pressed_bg};
    }}

    QPushButton[destructive="true"]:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QPushButton[destructive="true"]:disabled {{
        color: {disabled_text};
        border-color: {border_subtle};
        background-color: transparent;
    }}

    QToolButton#NewTabButton {{
        background-color: transparent;
        color: {text_muted};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        font-size: 15px;
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
        border: {focus_width}px solid {focus_ring};
        color: {text_primary};
    }}

    QToolButton#ChromeToggleButton {{
        background-color: transparent;
        color: {text_muted};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        font-size: 15px;
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
        border: {focus_width}px solid {focus_ring};
        color: {text_primary};
    }}

    QWidget#ZoomControls {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: {SPACE_1}px;
    }}

    QPushButton#ZoomButton {{
        background-color: transparent;
        color: {text_primary};
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
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
        border: {focus_width}px solid {focus_ring};
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
        background: {ink};
        border: 1px solid {ink_pressed};
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
        border: 2px solid {ink};
        width: 12px;
        height: 12px;
        margin: -5px 0;
        border-radius: 6px;
    }}

    QSlider#ZoomSlider::handle:horizontal:hover {{
        background: {on_ink};
        border-color: {ink_hover};
    }}

    QSlider#ZoomSlider:focus {{
        background: transparent;
    }}

    QSlider#ZoomSlider:focus::groove:horizontal {{
        border: {focus_width}px solid {focus_ring};
    }}

    QSlider#ZoomSlider:focus::handle:horizontal {{
        background: {ink};
        border: 2px solid {on_ink};
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
        color: {text_muted};
        font-size: 12px;
        font-weight: 400;
    }}

    QStatusBar {{
        background-color: {bg_status};
        color: {text_muted};
        border-top: 1px solid {border_subtle};
    }}

    QStatusBar QLabel {{
        color: {text_muted};
    }}

    /* R10e: tool-tab footers mirror QStatusBar so Tools/editor chrome feel related. */
    QLabel#ToolPageStatus {{
        background-color: {bg_status};
        color: {text_muted};
        border-top: 1px solid {border_subtle};
        padding: {SPACE_1}px {SPACE_3}px;
        min-height: {COMPACT_CONTROL_HEIGHT}px;
    }}

    QWidget#MoveUndoToast QLabel {{
        color: {text_muted};
        font-weight: 500;
    }}

    QPushButton#MoveUndoButton {{
        color: {text_primary};
        background-color: {bg_card};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 2px 10px;
        font-weight: 500;
    }}

    QPushButton#MoveUndoButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QPushButton#MoveUndoButton:pressed {{
        background-color: {bg_pressed};
        border-color: {border_default};
    }}

    QPushButton#MoveUndoButton:focus,
    QPushButton#BusyOverlayCancel:focus,
    QPushButton#ToastOverlayUndo:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QToolButton#ToolsCategoryHeading:focus,
    QToolButton#ToolsDensityToggle:focus,
    QToolButton#ToolsUpcomingToggle:focus {{
        border: {focus_width}px solid {focus_ring};
        border-radius: {RADIUS_CONTROL}px;
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
        background-color: {ink};
        border-radius: {RADIUS_BADGE}px;
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
        border-color: {ink};
        border-style: dashed;
        background-color: {bg_card_hover};
    }}

    QLabel#GridEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 {SPACE_3}px 0;
    }}

    QLabel#GridEmptyState {{
        color: {text_muted};
        font-size: 22px;
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

    QPushButton#EmptyStateOpenButton {{
        min-height: 30px;
        padding: 3px {SPACE_4}px;
    }}

    QLabel#GridEmptyKbd,
    QLabel#MergeEmptyKbd,
    QLabel#ConvertEmptyKbd {{
        color: {text_muted};
        font-size: 12px;
        padding: {SPACE_2}px 0 0 0;
    }}

    QLabel#GridEmptyKbd {{
        font-family: {FONT_UI};
        font-size: 12px;
        padding: 0;
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
        color: {on_bar_muted};
        border: none;
        border-bottom: 2px solid transparent;
        padding: {SPACE_2}px {SPACE_3}px {SPACE_2 - 1}px {SPACE_3}px;
        margin-right: 2px;
        min-width: 80px;
        max-width: 220px;
        font-weight: 500;
    }}

    QTabWidget#TabManager > QTabBar::tab:selected {{
        color: {on_bar};
        background-color: transparent;
        border-bottom: 2px solid {ink};
        font-weight: 500;
    }}

    QTabWidget#TabManager > QTabBar::tab:hover:!selected {{
        color: {on_bar_muted};
        background-color: transparent;
    }}

    QTabWidget#TabManager > QTabBar::tab:selected:hover {{
        color: {on_bar};
    }}

    QTabWidget#TabManager QTabBar QAbstractButton {{
        background-color: transparent;
        border: none;
        border-radius: {RADIUS_CONTROL}px;
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
        border: {focus_width}px solid {focus_ring};
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
        padding: 6px 20px;
    }}

    QMessageBox QPushButton:default {{
        background-color: {ink};
        border-color: {ink};
        color: {on_ink};
        font-weight: 600;
    }}

    QMessageBox QPushButton:default:hover {{
        background-color: {ink_hover};
        border-color: {ink_hover};
    }}

    QMessageBox QPushButton:default:pressed {{
        background-color: {ink_pressed};
        border-color: {ink_pressed};
    }}

    QMessageBox QPushButton:default:focus {{
        border: {focus_width}px solid {selected_focus_ring};
    }}

    /* A destructive default keeps the danger treatment, not the ink fill. */
    QMessageBox QPushButton[destructive="true"]:default {{
        background-color: transparent;
        border-color: {close_tab};
        color: {close_tab};
    }}

    QMessageBox QPushButton[destructive="true"]:default:hover {{
        background-color: {close_tab};
        border-color: {close_tab};
        color: {on_ink};
    }}

    QMessageBox QPushButton[destructive="true"]:default:pressed {{
        background-color: {close_pressed_bg};
        border-color: {close_pressed_bg};
        color: {on_ink};
    }}

    QMessageBox QPushButton[destructive="true"]:default:focus {{
        border: {focus_width}px solid {focus_ring};
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
        color: {text_muted};
        font-size: 12px;
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

    QFrame#PdfViewerToolbarGroup {{
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QFrame#PdfViewerAnnotRail {{
        background-color: {bg_surface};
        border-left: 1px solid {border_subtle};
    }}

    QLabel#PdfViewerAnnotRailTitle {{
        color: {text_muted};
        font-size: 13px;
        font-weight: 500;
        padding: 2px 4px;
    }}

    QWidget#PdfViewerAnnotTools QToolButton {{
        text-align: left;
        padding: 5px 8px;
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        color: {text_muted};
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
        border: 1px solid {ink};
    }}

    QWidget#PdfViewerAnnotTools QToolButton:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QToolButton#PdfViewerAnnotCollapse,
    QToolButton#PdfViewerAnnotExpand,
    QToolButton#PdfViewerSideCollapse,
    QToolButton#PdfViewerSideExpand {{
        color: {text_muted};
        border: 1px solid transparent;
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px;
        background-color: transparent;
    }}

    QToolButton#PdfViewerAnnotCollapse:hover,
    QToolButton#PdfViewerAnnotExpand:hover,
    QToolButton#PdfViewerSideCollapse:hover,
    QToolButton#PdfViewerSideExpand:hover {{
        color: {text_primary};
        background-color: {bg_card_hover};
    }}

    QToolButton#PdfViewerAnnotCollapse:pressed,
    QToolButton#PdfViewerAnnotExpand:pressed,
    QToolButton#PdfViewerSideCollapse:pressed,
    QToolButton#PdfViewerSideExpand:pressed {{
        color: {text_primary};
        background-color: {bg_card};
        border-color: {border_default};
    }}

    QToolButton#PdfViewerAnnotCollapse:focus,
    QToolButton#PdfViewerAnnotExpand:focus,
    QToolButton#PdfViewerSideCollapse:focus,
    QToolButton#PdfViewerSideExpand:focus {{
        border: {focus_width}px solid {focus_ring};
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
        border: {focus_width}px solid {focus_ring};
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
        border: {focus_width}px solid {focus_ring};
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
        border: {focus_width}px solid {focus_ring};
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
        /* The button shows the format it toggles, so it stays bold. */
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
        border: 1px solid {ink};
        color: {ink};
    }}

    QToolButton#FreeTextFormatBold:focus,
    QToolButton#FreeTextFormatItalic:focus,
    QToolButton#FreeTextFormatColor:focus,
    QToolButton#FreeTextFormatDelete:focus {{
        border: {focus_width}px solid {focus_ring};
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
        border-bottom: 2px solid {ink};
        font-weight: 500;
    }}

    QTabWidget#PdfViewerSide > QTabBar::tab:hover:!selected {{
        color: {text_muted};
        background-color: {bg_card_hover};
    }}

    QLabel#PdfViewerHint {{
        color: {text_muted};
        font-size: 12px;
        padding: 10px 16px;
        background-color: {bg_preview_footer};
        border-top: 1px solid {border_subtle};
    }}

    QLabel#PdfViewerPageLabel,
    QLabel#PdfViewerHitLabel {{
        color: {text_muted};
        font-size: 12px;
        padding: 0 8px;
    }}

    QWidget#BusyOverlay {{
        background-color: {busy_overlay_bg};
    }}

    QWidget#BusyOverlayPanel {{
        background-color: {bg_float};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#BusyOverlayMessage {{
        color: {text_primary};
        font-size: 15px;
        font-weight: 600;
        background-color: transparent;
        border: none;
    }}

    QPushButton#BusyOverlayCancel {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 500;
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
        background-color: {bg_float};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px 8px 4px 4px;
    }}

    QLabel#ToastOverlayMessage {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 500;
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
        color: {text_muted};
    }}

    QPushButton#ToastOverlayUndo {{
        color: {text_primary};
        background-color: {bg_card};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 12px;
        font-weight: 500;
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
        background-color: {bg_float};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#TipsOverlayTitle {{
        color: {text_primary};
        font-size: 18px;
        font-weight: 600;
    }}

    QLabel#TipsOverlayIntro {{
        color: {text_muted};
        font-size: 13px;
    }}

    QLabel#TipsOverlayTip {{
        color: {text_primary};
        font-size: 13px;
    }}

    QWidget#ContextHint {{
        background-color: {bg_float};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#ContextHintText {{
        color: {text_primary};
        font-size: 13px;
    }}

    QScrollArea#ShortcutsScroll,
    QScrollArea#ShortcutsScroll > QWidget > QWidget {{
        background-color: transparent;
        border: none;
    }}

    QLabel#ShortcutCategory {{
        color: {text_primary};
        font-size: 15px;
        font-weight: 600;
        padding-top: 4px;
    }}

    QLabel#ShortcutAction {{
        color: {text_muted};
        font-size: 13px;
    }}

    QLabel#ShortcutKeys {{
        color: {text_primary};
        font-size: 12px;
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
        color: {text_muted};
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
        color: {text_muted};
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
        background-color: {ink};
        border: none;
        border-radius: 2px;
    }}

    QLabel#ComparePaneTitle,
    QLabel#CompareSummary {{
        color: {text_muted};
    }}

    QLabel#CompareModeLabel {{
        color: {ink};
        font-weight: 500;
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

    QLabel#ToolsHeading {{
        color: {text_primary};
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.2px;
    }}

    QLabel#ToolsPurpose,
    QLabel#ToolsCategoryDescription {{
        color: {text_muted};
        font-size: 13px;
    }}

    QComboBox#ToolsCategoryJump {{
        min-height: 32px;
        min-width: 150px;
    }}

    QLabel#ToolsCategoryHeading,
    QToolButton#ToolsCategoryHeading {{
        color: {text_primary};
        font-size: 15px;
        font-weight: 600;
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
        font-weight: 400;
        border: none;
        background: transparent;
        padding: 2px 4px;
    }}

    QToolButton#ToolsDensityToggle:checked,
    QToolButton#ToolsUpcomingToggle:checked {{
        color: {ink};
    }}

    QToolButton#ToolsDensityToggle:hover,
    QToolButton#ToolsUpcomingToggle:hover {{
        color: {text_muted};
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

    QWidget#ToolWorkflowHeader {{
        background-color: {bg_base};
    }}

    QLabel#ToolWorkflowTitle {{
        color: {text_primary};
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.2px;
    }}

    QLabel#ToolWorkflowPurpose {{
        color: {text_muted};
        font-size: 13px;
    }}

    QLabel#ToolShellTitle {{
        color: {text_primary};
        font-size: 18px;
        font-weight: 600;
        letter-spacing: -0.2px;
    }}

    /* R19: ? nests beside the title as a filled chip (not far-right / transparent). */
    QToolButton#ToolShellHelp {{
        color: {text_primary};
        background-color: {bg_surface};
        border: 1px solid {border_default};
        border-radius: 12px;
        font-size: 13px;
        font-weight: 500;
        min-width: 22px;
        max-width: 22px;
        min-height: 22px;
        max-height: 22px;
        padding: 0;
    }}

    QToolButton#ToolShellHelp:hover {{
        color: {on_ink};
        background-color: {ink};
        border-color: {ink};
    }}

    QToolButton#ToolShellHelp:focus {{
        border: {focus_width}px solid {focus_ring};
    }}

    QFrame#ToolShellHelpPopup {{
        background-color: {bg_float};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#ToolShellHelpBody {{
        color: {text_muted};
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
        border-color: {ink};
        border-style: dashed;
        background-color: {bg_card_hover};
    }}

    QFrame#ToolShellDropZone:focus {{
        border: {focus_width}px dashed {focus_ring};
    }}

    QLabel#ToolShellDropPrompt {{
        color: {text_muted};
        font-size: 13px;
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
        color: {text_muted};
        font-size: 13px;
    }}

    QPushButton#ResultActionsPreview,
    QPushButton#ResultActionsOpen,
    QPushButton#ResultActionsFolder {{
        background-color: transparent;
        color: {text_muted};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        font-weight: 500;
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
        border: {focus_width}px solid {focus_ring};
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
        font-weight: 500;
    }}

    QLabel#WatermarkZoomLabel {{
        color: {text_muted};
        font-size: 12px;
        min-width: 40px;
    }}

    QPushButton#WatermarkZoomButton {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: 0;
        font-weight: 500;
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
        border: {focus_width}px solid {focus_ring};
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
        background: {ink};
        border: none;
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}

    QSlider#WatermarkSlider::sub-page:horizontal {{
        background: {ink};
        border-radius: 2px;
    }}

    QSlider#WatermarkSlider:focus {{
        outline: none;
    }}

    /* Card / tile chrome — dynamic properties + :hover/:focus; no per-state setStyleSheet. */
    QFrame#PageCard {{
        background-color: transparent;
        border: none;
        border-radius: 0;
    }}
    QFrame#MergeFileCard,
    QFrame#ConvertFileCard {{
        background-color: {bg_card};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#PageCard:hover {{
        background-color: transparent;
    }}
    QFrame#MergeFileCard:hover,
    QFrame#ConvertFileCard:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}
    QFrame#MergeFileCard[focused="true"],
    QFrame#ConvertFileCard[focused="true"] {{
        border: {focus_width}px solid {focus_ring};
    }}
    QFrame#MergeFileCard[selected="true"],
    QFrame#ConvertFileCard[selected="true"] {{
        border: {selected_width}px solid {ink};
    }}
    QFrame#MergeFileCard[selected="true"]:hover,
    QFrame#ConvertFileCard[selected="true"]:hover {{
        border-color: {ink_hover};
    }}
    QLabel#PageCardThumbnail {{
        background-color: {bg_thumb_empty};
        border: 1px solid {border_subtle};
        border-radius: 2px;
    }}
    QLabel#PageCardThumbnail[failed="true"] {{
        color: {text_muted};
    }}
    QFrame#PageCard:hover QLabel#PageCardThumbnail {{
        border-color: {border_hover};
        background-color: {bg_card_hover};
    }}
    QFrame#PageCard[selected="true"] QLabel#PageCardThumbnail {{
        border: {selected_width}px solid {ink};
    }}
    QLabel#PageCardLabel {{
        color: {text_muted};
        font-size: 12px;
        font-weight: 400;
        letter-spacing: 0.3px;
    }}
    QFrame#PageCard[selected="true"] QLabel#PageCardLabel {{
        color: {text_primary};
    }}
    QLabel#PageCardSelectionIndicator {{
        color: {on_ink};
        background-color: {ink};
        border: 1px solid {on_ink};
        border-radius: 8px;
        font-size: 12px;
        font-weight: 400;
        min-width: 16px;
        min-height: 16px;
        max-width: 16px;
        max-height: 16px;
        qproperty-alignment: AlignCenter;
    }}
    QLabel#PageCardFocusRing {{
        background-color: transparent;
        border: {focus_width}px dashed {focus_ring};
        border-radius: {RADIUS_BADGE}px;
    }}
    QLabel#PageCardPageOverlay {{
        color: {SURFACE_PAPER};
        background-color: {page_chip_bg};
        font-size: 12px;
        font-weight: 400;
        padding: {SPACE_1}px {SPACE_2}px;
        border-radius: {RADIUS_BADGE}px;
    }}
    QLabel#PageCardRotationOverlay {{
        color: {SURFACE_PAPER};
        background-color: {page_chip_bg};
        font-size: 12px;
        font-weight: 400;
        padding: {SPACE_1}px {SPACE_1}px;
        border-radius: {RADIUS_BADGE}px;
    }}

    QScrollArea#PreferencesScroll,
    QScrollArea#PreferencesScroll > QWidget#qt_scrollarea_viewport,
    QWidget#PreferencesContent {{
        background-color: {bg_surface};
    }}
    QLabel#PreferencesSection {{
        color: {text_muted};
        font-size: 13px;
        font-weight: 500;
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
        font-size: 13px;
        font-weight: 500;
    }}
    QLabel#MergeFileCardSubtitle,
    QLabel#ConvertFileCardSubtitle {{
        color: {text_muted};
        font-size: 12px;
        font-weight: 400;
    }}
    QFrame#MergeFileCard[selected="true"] QLabel#MergeFileCardSubtitle,
    QFrame#ConvertFileCard[selected="true"] QLabel#ConvertFileCardSubtitle {{
        color: {text_muted};
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
        border: {focus_width}px solid {focus_ring};
    }}
    QFrame#ToolTile[blocked="true"]:focus,
    QFrame#ToolTile[comingSoon="true"]:focus {{
        background-color: transparent;
        border: {focus_width}px solid {focus_ring};
    }}
    QFrame#ToolTile[compact="true"] {{
        border-radius: {RADIUS_CONTROL}px;
    }}
    QLabel#ToolTileTitle {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 500;
        letter-spacing: -0.1px;
    }}
    QFrame#ToolTile[blocked="true"] QLabel#ToolTileTitle,
    QFrame#ToolTile[comingSoon="true"] QLabel#ToolTileTitle {{
        color: {text_muted};
    }}
    QFrame#ToolTile[compact="true"] QLabel#ToolTileTitle {{
        font-size: 12px;
        font-weight: 400;
    }}
    QLabel#ToolTileSubtitle {{
        color: {text_muted};
        font-size: 12px;
        font-weight: 400;
    }}
    QLabel#ToolTileCapability {{
        color: {status_warning};
        font-size: 12px;
        font-weight: 400;
    }}
    QFrame#ToolTile[compact="true"] QLabel#ToolTileSubtitle {{
        font-size: 12px;
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
    """Ink colour for programmatic painting (drag badge, etc.)."""
    return token_qcolor(current_theme().ink, alpha)


def page_accent_qcolor(*, alpha: int = 255) -> "QColor":
    """Ink colour for marks painted on the white page (handles, selections)."""
    return token_qcolor(PAGE_ACCENT, alpha)


def focus_ring_hex() -> str:
    """Keyboard focus ring colour for the active chrome theme (inline styles, painters)."""
    return current_theme().focus


def on_accent_qcolor() -> "QColor":
    """Colour for text/icons drawn on top of the ink fill."""
    return token_qcolor(current_theme().on_ink)


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
    """Theme-aware hover/stack border for programmatic paint (not QSS)."""
    return token_qcolor(current_theme().line_strong)


def chrome_card_qcolor() -> "QColor":
    """Card/surface fill for programmatic paint (pairs with light/dark QSS)."""
    return token_qcolor(current_theme().raised)


def chrome_text_muted_qcolor() -> "QColor":
    """Muted chrome ink for programmatic paint (pairs with light/dark QSS)."""
    return token_qcolor(current_theme().text_muted)


def status_success_hex() -> str:
    """Success ink for toast/list text."""
    return current_theme().success


def status_warning_hex() -> str:
    """Warning ink for toast/list text."""
    return current_theme().warning


def close_tab_hex() -> str:
    """Destructive / close-tab red (pairs with light/dark QSS)."""
    return current_theme().danger


def tab_close_icon(*, color: str | None = None) -> "QIcon":
    """Red × icon for tab close buttons (Phosphor ``x``, destructive tint)."""
    from pagedrop.ui import icons

    ink = color if color is not None else close_tab_hex()
    return icons.icon("x", color=ink)


def apply_app_font(app: "QApplication") -> None:
    """Make the UI family stack the application font, keeping its point size.

    Families missing on this machine are skipped by Qt, so this is safe when
    the bundled font failed to register.
    """
    font = app.font()
    font.setFamilies(list(FONT_UI_FAMILIES))
    app.setFont(font)


def tabular_font(base: "QFont | None" = None) -> "QFont":
    """Font that draws digits at equal width so changing numbers do not jitter.

    Without a base it is a bare font, so a widget using it still takes family
    and size from the style sheet.
    """
    from PyQt6.QtGui import QFont

    font = QFont(base) if base is not None else QFont()
    font.setFeature(QFont.Tag("tnum"), 1)
    return font
