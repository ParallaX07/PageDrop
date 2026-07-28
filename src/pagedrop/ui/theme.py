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

# Semantic status (compare diffs, validation errors)
STATUS_SUCCESS = "#4CAF6E"
STATUS_WARNING = "#F0B43C"

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

RADIUS_CARD = 12
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
        # Cool off-white base; white cards; light borders (Bento light translation).
        bg_base = "#F7F8FA"
        bg_surface = "#FFFFFF"
        bg_grid = "#F0F1F4"
        bg_card = "#FFFFFF"
        bg_card_hover = "#EEF0F4"
        bg_thumb_empty = "#E2E4EA"
        bg_toolbar = "#FFFFFF"
        bg_status = "#FFFFFF"
        bg_tab_bar = "#F7F8FA"
        bg_preview_footer = "#FFFFFF"
        border_subtle_tok = "#E5E7EB"
        border_default_tok = "#D1D5DB"
        border_hover = "#9CA3AF"
        text_primary = "#1A1A1F"
        text_secondary = "#4A4A55"
        text_muted_tok = "#5A5D68"
        close_tab = "#D14343"
        close_tab_hover_bg = "#F5D6D6"
        busy_overlay_bg = "rgba(247, 248, 250, 200)"
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
        color: #FFFFFF;
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
        background-color: {bg_base};
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
        selection-color: #FFFFFF;
    }}

    QSpinBox {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 8px;
    }}

    QSpinBox:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QToolBar {{
        background-color: {bg_toolbar};
        border: none;
        border-bottom: 1px solid {border_subtle};
        spacing: 8px;
        padding: 8px 12px;
    }}

    /* Viewer chrome uses QToolButton outside QToolBar; keep both in sync. */
    QToolButton,
    QToolBar QToolButton {{
        background-color: {bg_card};
        color: {text_primary};
        border: 1px solid {border_default};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 14px;
        font-weight: 600;
    }}

    QToolButton:hover,
    QToolBar QToolButton:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}

    QToolButton:pressed,
    QToolBar QToolButton:pressed {{
        background-color: {bg_base};
    }}

    QToolButton:focus,
    QToolBar QToolButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QToolButton:checked {{
        background-color: {ACCENT};
        color: #FFFFFF;
        border: 1px solid {ACCENT_PRESSED};
    }}

    QToolButton:checked:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    QToolButton:disabled,
    QToolBar QToolButton:disabled {{
        color: {text_muted};
        border-color: {border_subtle};
    }}

    QPushButton#ToolbarPrimary,
    QToolBar QToolButton#ToolbarPrimary {{
        background-color: {ACCENT};
        color: #FFFFFF;
        border: 1px solid {ACCENT_PRESSED};
        font-weight: 600;
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
        border: {focus_width}px solid #FFFFFF;
    }}

    QPushButton#ToolbarPrimary:disabled {{
        background-color: {bg_card_hover};
        color: {text_muted};
        border-color: {border_subtle};
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
        background-color: {bg_base};
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

    QLabel#GridEmptyKbd,
    QLabel#MergeEmptyKbd,
    QLabel#ConvertEmptyKbd {{
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
        border: none;
        border-radius: {RADIUS_CONTROL}px;
        color: {text_secondary};
        background-color: transparent;
    }}

    QWidget#PdfViewerAnnotTools QToolButton:hover {{
        color: {text_primary};
        background-color: {bg_card_hover};
    }}

    QWidget#PdfViewerAnnotTools QToolButton:checked {{
        color: {text_primary};
        background-color: {bg_card};
        border: 1px solid {ACCENT};
    }}

    QToolButton#PdfViewerAnnotCollapse,
    QToolButton#PdfViewerAnnotExpand {{
        color: {text_muted};
        border: none;
        padding: 4px;
        background-color: transparent;
    }}

    QToolButton#PdfViewerAnnotCollapse:hover,
    QToolButton#PdfViewerAnnotExpand:hover {{
        color: {text_primary};
        background-color: {bg_card_hover};
        border-radius: {RADIUS_CONTROL}px;
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
        color: {ACCENT};
    }}

    QLabel#ToastOverlayMessage[kind="error"] {{
        color: {close_tab};
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

    QWidget#ToolsCentral {{
        background-color: {bg_base};
    }}

    QWidget#ToolsCatalogue {{
        background-color: {bg_base};
    }}

    QScrollArea#ToolsScroll {{
        background-color: {bg_base};
        border: none;
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

    QLabel#ToolsEmptyState {{
        color: {text_muted};
        font-size: 13px;
        padding: 24px;
    }}

    QWidget#ToolShellCentral {{
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

    QScrollArea#ToolShellOptionsScroll {{
        background-color: transparent;
        border: none;
    }}

    QWidget#ToolShellOptions {{
        background-color: transparent;
    }}

    QFrame#ToolShellDropZone {{
        background-color: {bg_surface};
        border: 1px dashed {border_default};
        border-radius: {RADIUS_CARD}px;
    }}

    QFrame#ToolShellDropZone[dropActive="true"] {{
        border-color: {ACCENT};
        background-color: {bg_card};
    }}

    QFrame#ToolShellDropZone:focus {{
        border-color: {ACCENT};
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

    QWidget#ResultActionsBar {{
        background-color: {bg_surface};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CONTROL}px;
    }}

    QLabel#ResultActionsLabel {{
        color: {text_secondary};
        font-size: 13px;
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

    QPushButton#WatermarkZoomButton:focus {{
        border: {focus_width}px solid {ACCENT};
    }}

    QWidget#WatermarkKindToggle QToolButton {{
        padding: 6px 16px;
        min-width: 64px;
    }}

    QScrollArea#WatermarkPreviewScroll {{
        background-color: transparent;
        border: none;
    }}

    QScrollArea#WatermarkOptionsScroll {{
        background-color: transparent;
        border: none;
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
        border: 1px solid {border_default};
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
        border: 2px solid {ACCENT};
    }}
    QFrame#PageCard[selected="true"],
    QFrame#MergeFileCard[selected="true"],
    QFrame#ConvertFileCard[selected="true"] {{
        border: 3px solid {ACCENT};
    }}
    QFrame#PageCard[selected="true"]:hover,
    QFrame#MergeFileCard[selected="true"]:hover,
    QFrame#ConvertFileCard[selected="true"]:hover {{
        border-color: {ACCENT_HOVER};
    }}
    QLabel#PageCardThumbnail {{
        background-color: {bg_thumb_empty};
        border-radius: 6px;
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

    QFrame#ToolTile {{
        background-color: {bg_card};
        border: 1px solid {border_subtle};
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#ToolTile:hover {{
        background-color: {bg_card_hover};
        border-color: {border_hover};
    }}
    QFrame#ToolTile[blocked="true"]:hover {{
        background-color: {bg_card};
        border-color: {border_subtle};
    }}
    QFrame#ToolTile:focus {{
        background-color: {bg_card_hover};
        border: 2px solid {ACCENT};
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


def shadow_qcolor(*, alpha: int = 55) -> "QColor":
    """Tinted drop-shadow color."""
    from PyQt6.QtGui import QColor

    from pagedrop.ui.settings import light_theme

    if light_theme():
        return QColor(30, 40, 60, min(alpha, 40))
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
