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

ACCENT = "#2F9BE6"
ACCENT_HOVER = "#4AADED"
ACCENT_PRESSED = "#1F7FCC"

TEXT_PRIMARY = "#F2F2F4"
TEXT_SECONDARY = "#A8A8B3"
TEXT_MUTED = "#82828E"

CLOSE_TAB = "#E85D5D"
CLOSE_TAB_HOVER_BG = "#3D2228"

# Tinted shadow (cool blue, not pure black)
SHADOW_RGB = (14, 22, 38)

RADIUS_CARD = 10
RADIUS_CONTROL = 8
RADIUS_BADGE = 6

FONT_UI = '"Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'

CARD_PADDING = 16
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


def app_stylesheet(*, high_contrast: bool = False, light: bool = False) -> str:
    # Light / HC overrides under distinct locals so we never mutate module tokens.
    if light:
        bg_base = "#F2F3F5"
        bg_surface = "#FFFFFF"
        bg_grid = "#EBEDF0"
        bg_card = "#FFFFFF"
        bg_card_hover = "#E4E6EB"
        bg_toolbar = "#FFFFFF"
        bg_status = "#FFFFFF"
        bg_tab_bar = "#F2F3F5"
        bg_preview_footer = "#FFFFFF"
        border_subtle_tok = "#D5D7DE"
        border_default_tok = "#B4B7C0"
        border_hover = "#8A8E99"
        text_primary = "#1A1A1F"
        text_secondary = "#4A4A55"
        text_muted_tok = "#6B6E78"
        close_tab = "#D14343"
        close_tab_hover_bg = "#F5D6D6"
        busy_overlay_bg = "rgba(242, 243, 245, 200)"
    else:
        bg_base = BG_BASE
        bg_surface = BG_SURFACE
        bg_grid = BG_GRID
        bg_card = BG_CARD
        bg_card_hover = BG_CARD_HOVER
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
        busy_overlay_bg = "rgba(19, 19, 22, 180)"

    text_muted = text_secondary if high_contrast else text_muted_tok
    border_default = border_hover if high_contrast else border_default_tok
    border_subtle = border_default_tok if high_contrast else border_subtle_tok
    focus_width = 3 if high_contrast else 2
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
        selection-color: #FFFFFF;
    }}

    QLineEdit:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QListWidget {{
        background-color: {bg_surface};
        color: {text_primary};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        outline: none;
        padding: 4px;
    }}

    QListWidget::item {{
        padding: 8px 10px;
        border-radius: 6px;
        color: {text_primary};
    }}

    QListWidget::item:selected {{
        background-color: {ACCENT};
        color: #FFFFFF;
    }}

    QListWidget::item:hover:!selected {{
        background-color: {bg_card_hover};
    }}

    QLabel#CommandPaletteHint {{
        color: {text_muted};
        font-size: 11px;
        font-family: {FONT_MONO};
    }}

    QToolBar {{
        background-color: {bg_toolbar};
        border: none;
        border-bottom: 1px solid {border_subtle};
        spacing: 8px;
        padding: 8px 12px;
    }}

    QToolBar QToolButton {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 14px;
        font-weight: 600;
    }}

    QToolBar QToolButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QToolBar QToolButton:pressed {{
        background-color: {bg_base};
    }}

    QToolBar QToolButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QToolBar QToolButton#ToolbarPrimary {{
        background-color: {ACCENT};
        color: #FFFFFF;
        border: 1px solid {ACCENT_PRESSED};
        font-weight: 600;
    }}

    QToolBar QToolButton#ToolbarPrimary:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    QToolBar QToolButton#ToolbarPrimary:pressed {{
        background-color: {ACCENT_PRESSED};
        border-color: {ACCENT_PRESSED};
    }}

    QToolBar QToolButton#ToolbarPrimary:focus {{
        border: {focus_width}px solid #FFFFFF;
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
        background-color: {bg_base};
    }}

    QToolButton#NewTabButton:focus {{
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
        background-color: {bg_card};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#ZoomCaption {{
        color: {text_muted};
        font-size: 11px;
        font-weight: 600;
        padding: 0 2px 0 0;
    }}

    QPushButton#ZoomButton {{
        background-color: {bg_surface};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: 6px;
        font-size: 15px;
        font-weight: 600;
        padding: 0;
    }}

    QPushButton#ZoomButton:hover:enabled {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
        color: {text_primary};
    }}

    QPushButton#ZoomButton:pressed:enabled {{
        background-color: {bg_base};
    }}

    QPushButton#ZoomButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QPushButton#ZoomButton:disabled {{
        color: {text_muted};
        border-color: {border_subtle};
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
        background: #FFFFFF;
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
        border: 2px solid #FFFFFF;
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

    QWidget#EmptyStatePanel {{
        background-color: transparent;
    }}

    QLabel#GridEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 12px 0;
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

    QLabel#GridEmptyKbd {{
        color: {text_muted};
        font-family: {FONT_MONO};
        font-size: 11px;
        padding: 8px 0 0 0;
    }}

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
        padding: 8px 14px 7px 14px;
        margin-right: 2px;
        min-width: 80px;
        max-width: 220px;
        font-weight: 500;
    }}

    QTabWidget#TabManager > QTabBar::tab:selected {{
        color: {text_primary};
        background-color: {bg_surface};
        border-bottom: 2px solid {ACCENT};
        font-weight: 600;
    }}

    QTabWidget#TabManager > QTabBar::tab:hover:!selected {{
        color: {text_secondary};
        background-color: {bg_card};
    }}

    QTabWidget#TabManager > QTabBar::tab:selected:hover {{
        color: {text_primary};
    }}

    QTabWidget#TabManager QTabBar QAbstractButton {{
        background-color: transparent;
        border: none;
        border-radius: 4px;
        padding: 2px;
        min-width: 18px;
        max-width: 18px;
        min-height: 18px;
        max-height: 18px;
    }}

    QTabWidget#TabManager QTabBar QAbstractButton:hover {{
        background-color: {close_tab_hover_bg};
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

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
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
        color: #FFFFFF;
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
        background-color: #FAFAFA;
        padding: 8px;
    }}

    QWidget#PreviewFooter {{
        background-color: {bg_preview_footer};
        border-top: 1px solid {border_subtle};
    }}

    QLabel#PagePreviewHint {{
        color: {text_muted};
        font-size: 11px;
        font-family: {FONT_MONO};
        padding: 10px 16px;
    }}

    QWidget#BusyOverlay {{
        background-color: {busy_overlay_bg};
    }}

    QLabel#BusyOverlayMessage {{
        color: {text_primary};
        font-size: 14px;
        font-weight: 600;
        padding: 16px 24px;
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QWidget#ToastOverlay {{
        background-color: transparent;
    }}

    QLabel#ToastOverlayMessage {{
        color: {text_primary};
        font-size: 13px;
        font-weight: 600;
        padding: 12px 20px;
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
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
        padding: 0 0 12px 0;
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
        padding: 0 0 12px 0;
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
        background-color: #FAFAFA;
    }}

    QFrame#DropIndicator {{
        background-color: {ACCENT};
        border-radius: 2px;
    }}
    """


def accent_qcolor() -> "QColor":
    """Accent color for programmatic painting (drag badge, etc.)."""
    from PyQt6.QtGui import QColor

    return QColor(ACCENT)


def shadow_qcolor(*, alpha: int = 55) -> "QColor":
    """Tinted drop-shadow color."""
    from PyQt6.QtGui import QColor

    from pagedrop.ui.settings import light_theme

    if light_theme():
        return QColor(30, 40, 60, min(alpha, 40))
    r, g, b = SHADOW_RGB
    return QColor(r, g, b, alpha)


def _card_surface_colors() -> dict[str, str]:
    """Surface / text / border tokens for per-card stylesheets."""
    from pagedrop.ui.settings import light_theme

    if light_theme():
        return {
            "BG_CARD": "#FFFFFF",
            "BG_CARD_HOVER": "#E4E6EB",
            "BORDER_DEFAULT": "#B4B7C0",
            "BORDER_HOVER": "#8A8E99",
            "TEXT_PRIMARY": "#1A1A1F",
            "TEXT_SECONDARY": "#4A4A55",
            "TEXT_MUTED": "#6B6E78",
        }
    return {
        "BG_CARD": BG_CARD,
        "BG_CARD_HOVER": BG_CARD_HOVER,
        "BORDER_DEFAULT": BORDER_DEFAULT,
        "BORDER_HOVER": BORDER_HOVER,
        "TEXT_PRIMARY": TEXT_PRIMARY,
        "TEXT_SECONDARY": TEXT_SECONDARY,
        "TEXT_MUTED": TEXT_MUTED,
    }


def tab_close_icon(*, color: str = CLOSE_TAB) -> "QIcon":
    """Red × icon for tab close buttons."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

    size = 16
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    inset = 4
    painter.drawLine(inset, inset, size - inset, size - inset)
    painter.drawLine(size - inset, inset, inset, size - inset)
    painter.end()

    return QIcon(pixmap)


def page_card_stylesheet(*, selected: bool, hovered: bool, focused: bool = False) -> str:
    c = _card_surface_colors()
    border_color = ACCENT if selected else c["BORDER_DEFAULT"]
    if selected and hovered:
        border_color = ACCENT_HOVER
    elif hovered:
        border_color = c["BORDER_HOVER"]
    elif focused:
        border_color = ACCENT

    border_width = 3 if selected else (2 if focused else 1)
    background = c["BG_CARD_HOVER"] if hovered else c["BG_CARD"]
    label_color = c["TEXT_PRIMARY"] if selected else c["TEXT_SECONDARY"]

    return f"""
    QFrame#PageCard {{
        background-color: {background};
        border: {border_width}px solid {border_color};
        border-radius: {RADIUS_CARD}px;
    }}
    QLabel#PageCardThumbnail {{
        background-color: #FAFAFA;
        border-radius: 6px;
    }}
    QLabel#PageCardLabel {{
        color: {label_color};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}
    QLabel#PageCardPageOverlay {{
        color: #FFFFFF;
        background-color: rgba(19, 19, 22, 160);
        font-size: 11px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
    }}
    QLabel#PageCardRotationOverlay {{
        color: #FFFFFF;
        background-color: rgba(19, 19, 22, 160);
        font-family: {FONT_MONO};
        font-size: 10px;
        font-weight: 600;
        padding: 2px 5px;
        border-radius: 4px;
    }}
    """


def merge_file_card_stylesheet(
    *, selected: bool, hovered: bool, focused: bool = False
) -> str:
    c = _card_surface_colors()
    border_color = ACCENT if selected else c["BORDER_DEFAULT"]
    if selected and hovered:
        border_color = ACCENT_HOVER
    elif hovered:
        border_color = c["BORDER_HOVER"]
    elif focused:
        border_color = ACCENT

    border_width = 3 if selected else (2 if focused else 1)
    background = c["BG_CARD_HOVER"] if hovered else c["BG_CARD"]
    title_color = c["TEXT_PRIMARY"]
    subtitle_color = c["TEXT_MUTED"] if not selected else c["TEXT_SECONDARY"]

    return f"""
    QFrame#MergeFileCard {{
        background-color: {background};
        border: {border_width}px solid {border_color};
        border-radius: {RADIUS_CARD}px;
    }}
    QLabel#MergeFileCardThumbnail {{
        background-color: transparent;
        border: none;
    }}
    QLabel#MergeFileCardTitle {{
        color: {title_color};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#MergeFileCardSubtitle {{
        color: {subtitle_color};
        font-size: 11px;
        font-weight: 500;
    }}
    """


def convert_file_card_stylesheet(
    *, selected: bool, hovered: bool, focused: bool = False
) -> str:
    c = _card_surface_colors()
    border_color = ACCENT if selected else c["BORDER_DEFAULT"]
    if selected and hovered:
        border_color = ACCENT_HOVER
    elif hovered:
        border_color = c["BORDER_HOVER"]
    elif focused:
        border_color = ACCENT

    border_width = 3 if selected else (2 if focused else 1)
    background = c["BG_CARD_HOVER"] if hovered else c["BG_CARD"]
    title_color = c["TEXT_PRIMARY"]
    subtitle_color = c["TEXT_MUTED"] if not selected else c["TEXT_SECONDARY"]

    return f"""
    QFrame#ConvertFileCard {{
        background-color: {background};
        border: {border_width}px solid {border_color};
        border-radius: {RADIUS_CARD}px;
    }}
    QLabel#ConvertFileCardThumbnail {{
        background-color: transparent;
        border: none;
    }}
    QLabel#ConvertFileCardTitle {{
        color: {title_color};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#ConvertFileCardSubtitle {{
        color: {subtitle_color};
        font-size: 11px;
        font-weight: 500;
    }}
    """
