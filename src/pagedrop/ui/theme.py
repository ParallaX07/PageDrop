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


def app_stylesheet(*, high_contrast: bool = False) -> str:
    # HC overrides under distinct locals so we never shadow module token names.
    text_muted = TEXT_SECONDARY if high_contrast else TEXT_MUTED
    border_default = BORDER_HOVER if high_contrast else BORDER_DEFAULT
    border_subtle = BORDER_DEFAULT if high_contrast else BORDER_SUBTLE
    focus_width = 3 if high_contrast else 2
    return f"""
    * {{
        font-family: {FONT_UI};
        font-size: 13px;
        color: {TEXT_PRIMARY};
    }}

    QMainWindow {{
        background-color: {BG_BASE};
    }}

    QToolTip {{
        background-color: {BG_CARD};
        color: {TEXT_PRIMARY};
        border: 1px solid {border_default};
        padding: 4px 8px;
    }}

    QMenuBar {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border-bottom: 1px solid {border_subtle};
        padding: 2px 0;
    }}

    QMenuBar::item {{
        background: transparent;
        padding: 6px 12px;
        border-radius: {RADIUS_CONTROL}px;
        border: {focus_width}px solid transparent;
    }}

    QMenuBar::item:selected,
    QMenuBar::item:focus {{
        background-color: {BG_CARD_HOVER};
        border-color: {ACCENT};
    }}

    QMenu {{
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
        padding: 4px;
    }}

    QMenu::item {{
        padding: 8px 28px 8px 16px;
        border-radius: 6px;
        border: {focus_width}px solid transparent;
    }}

    QMenu::item:selected,
    QMenu::item:focus {{
        background-color: {BG_CARD_HOVER};
        border-color: {ACCENT};
    }}

    QMenu::separator {{
        height: 1px;
        background: {border_subtle};
        margin: 4px 8px;
    }}

    QToolBar {{
        background-color: {BG_TOOLBAR};
        border: none;
        border-bottom: 1px solid {border_subtle};
        spacing: 8px;
        padding: 8px 12px;
    }}

    QToolBar QToolButton {{
        background-color: {BG_CARD};
        color: {TEXT_PRIMARY};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 14px;
        font-weight: 600;
    }}

    QToolBar QToolButton:hover {{
        background-color: {BG_CARD_HOVER};
        border-color: {BORDER_HOVER};
    }}

    QToolBar QToolButton:pressed {{
        background-color: {BG_BASE};
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
        color: {TEXT_SECONDARY};
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
        background-color: {BG_CARD_HOVER};
        color: {TEXT_PRIMARY};
        border-color: {BORDER_HOVER};
    }}

    QToolButton#NewTabButton:pressed {{
        background-color: {BG_BASE};
    }}

    QToolButton#NewTabButton:focus {{
        border: {focus_width}px solid {ACCENT};
        color: {TEXT_PRIMARY};
    }}

    QLabel#ToolbarFilename {{
        color: {TEXT_SECONDARY};
        font-weight: 500;
        padding: 0 4px;
    }}

    QLabel#ToolbarFilename[active="true"] {{
        color: {TEXT_PRIMARY};
    }}

    QWidget#ZoomControls {{
        background-color: {BG_CARD};
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
        background-color: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid {border_default};
        border-radius: 6px;
        font-size: 15px;
        font-weight: 600;
        padding: 0;
    }}

    QPushButton#ZoomButton:hover:enabled {{
        background-color: {BG_CARD_HOVER};
        border-color: {BORDER_HOVER};
        color: {TEXT_PRIMARY};
    }}

    QPushButton#ZoomButton:pressed:enabled {{
        background-color: {BG_BASE};
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
        background: {BG_BASE};
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
        background: {BG_BASE};
        border: 1px solid {border_subtle};
        height: 4px;
        border-radius: 2px;
    }}

    QSlider#ZoomSlider::handle:horizontal {{
        background: {TEXT_PRIMARY};
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
        background: {BG_SURFACE};
        border-color: {border_subtle};
    }}

    QSlider#ZoomSlider:disabled::handle:horizontal {{
        background: {border_default};
        border-color: {border_subtle};
    }}

    QLabel#ZoomValueLabel {{
        color: {TEXT_SECONDARY};
        font-family: {FONT_MONO};
        font-size: 11px;
        font-weight: 600;
    }}

    QStatusBar {{
        background-color: {BG_STATUS};
        color: {TEXT_SECONDARY};
        border-top: 1px solid {border_subtle};
    }}

    QStatusBar QLabel {{
        color: {TEXT_SECONDARY};
    }}

    QProgressBar {{
        background-color: {BG_CARD};
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
        background-color: {BG_GRID};
        border: none;
    }}

    QWidget#ThumbnailContainer {{
        background-color: {BG_GRID};
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
        color: {TEXT_SECONDARY};
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
        background-color: {BG_BASE};
        top: -1px;
    }}

    QTabWidget#TabManager > QTabBar {{
        background-color: {BG_TAB_BAR};
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
        color: {TEXT_PRIMARY};
        background-color: {BG_SURFACE};
        border-bottom: 2px solid {ACCENT};
        font-weight: 600;
    }}

    QTabWidget#TabManager > QTabBar::tab:hover:!selected {{
        color: {TEXT_SECONDARY};
        background-color: {BG_CARD};
    }}

    QTabWidget#TabManager > QTabBar::tab:selected:hover {{
        color: {TEXT_PRIMARY};
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
        background-color: {CLOSE_TAB_HOVER_BG};
    }}

    QTabWidget#TabManager QTabBar QAbstractButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QScrollBar:vertical {{
        background: {BG_GRID};
        width: 10px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background: {border_default};
        border-radius: 5px;
        min-height: 32px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {BORDER_HOVER};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar:horizontal {{
        background: {BG_GRID};
        height: 10px;
        margin: 0;
    }}

    QScrollBar::handle:horizontal {{
        background: {border_default};
        border-radius: 5px;
        min-width: 32px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {BORDER_HOVER};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    QMessageBox {{
        background-color: {BG_SURFACE};
    }}

    QMessageBox QLabel {{
        color: {TEXT_PRIMARY};
    }}

    QMessageBox QPushButton {{
        background-color: {BG_CARD};
        color: {TEXT_PRIMARY};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 20px;
    }}

    QMessageBox QPushButton:hover {{
        background-color: {BG_CARD_HOVER};
        border-color: {BORDER_HOVER};
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
        background-color: {BG_GRID};
        border: none;
    }}

    QWidget#PagePreview {{
        background-color: {BG_BASE};
    }}

    QLabel#PagePreviewImage {{
        background-color: #FAFAFA;
        padding: 8px;
    }}

    QWidget#PreviewFooter {{
        background-color: {BG_PREVIEW_FOOTER};
        border-top: 1px solid {border_subtle};
    }}

    QLabel#PagePreviewHint {{
        color: {text_muted};
        font-size: 11px;
        font-family: {FONT_MONO};
        padding: 10px 16px;
    }}

    QWidget#BusyOverlay {{
        background-color: rgba(19, 19, 22, 180);
    }}

    QLabel#BusyOverlayMessage {{
        color: {TEXT_PRIMARY};
        font-size: 14px;
        font-weight: 600;
        padding: 16px 24px;
        background-color: {BG_SURFACE};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QWidget#MergeListPane {{
        background-color: {BG_GRID};
    }}

    QWidget#MergeEmptyState {{
        background-color: {BG_GRID};
    }}

    QLabel#MergeEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 12px 0;
    }}

    QLabel#MergeEmptyTitle {{
        color: {TEXT_SECONDARY};
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
        background-color: {BG_GRID};
        border: none;
    }}

    QWidget#MergeFileGridContainer {{
        background-color: {BG_GRID};
    }}

    QWidget#ConvertEmptyState {{
        background-color: {BG_GRID};
    }}

    QLabel#ConvertEmptyLogo {{
        background: transparent;
        border: none;
        padding: 0 0 12px 0;
    }}

    QLabel#ConvertEmptyTitle {{
        color: {TEXT_SECONDARY};
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
        background-color: {BG_GRID};
        border: none;
    }}

    QWidget#ConvertFileGridContainer {{
        background-color: {BG_GRID};
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

    r, g, b = SHADOW_RGB
    return QColor(r, g, b, alpha)


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
    border_color = ACCENT if selected else BORDER_DEFAULT
    if selected and hovered:
        border_color = ACCENT_HOVER
    elif hovered:
        border_color = BORDER_HOVER
    elif focused:
        border_color = ACCENT

    border_width = 3 if selected else (2 if focused else 1)
    background = BG_CARD_HOVER if hovered else BG_CARD
    label_color = TEXT_PRIMARY if selected else TEXT_SECONDARY

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
    """


def merge_file_card_stylesheet(
    *, selected: bool, hovered: bool, focused: bool = False
) -> str:
    border_color = ACCENT if selected else BORDER_DEFAULT
    if selected and hovered:
        border_color = ACCENT_HOVER
    elif hovered:
        border_color = BORDER_HOVER
    elif focused:
        border_color = ACCENT

    border_width = 3 if selected else (2 if focused else 1)
    background = BG_CARD_HOVER if hovered else BG_CARD
    title_color = TEXT_PRIMARY if selected else TEXT_PRIMARY
    subtitle_color = TEXT_MUTED if not selected else TEXT_SECONDARY

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
    border_color = ACCENT if selected else BORDER_DEFAULT
    if selected and hovered:
        border_color = ACCENT_HOVER
    elif hovered:
        border_color = BORDER_HOVER
    elif focused:
        border_color = ACCENT

    border_width = 3 if selected else (2 if focused else 1)
    background = BG_CARD_HOVER if hovered else BG_CARD
    title_color = TEXT_PRIMARY if selected else TEXT_PRIMARY
    subtitle_color = TEXT_MUTED if not selected else TEXT_SECONDARY

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
