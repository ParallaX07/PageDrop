"""Platform contrast / motion preferences and app chrome application."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QGuiApplication, QPalette
from PyQt6.QtWidgets import QApplication

from pagedrop.ui import settings as app_settings
from pagedrop.ui.theme import app_stylesheet, relative_luminance

# WCAG relative-luminance contrast; system HC themes are typically well above this.
_PALETTE_HIGH_CONTRAST_RATIO = 7.0


def contrast_ratio(hex_fg: str, hex_bg: str) -> float:
    """WCAG 2.x contrast ratio between two #RRGGBB colors."""
    lighter = max(relative_luminance(hex_fg), relative_luminance(hex_bg))
    darker = min(relative_luminance(hex_fg), relative_luminance(hex_bg))
    return (lighter + 0.05) / (darker + 0.05)


def _qcolor_hex(color) -> str:
    return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"


def _accessibility_hints():
    style_hints = QGuiApplication.styleHints()
    getter = getattr(style_hints, "accessibility", None)
    if getter is None:
        return None
    return getter()


def prefers_high_contrast() -> bool:
    """True when the platform asks for high contrast (Qt ≥ 6.10) or palette implies it."""
    hints = _accessibility_hints()
    if hints is not None:
        pref = getattr(hints, "contrastPreference", None)
        if callable(pref):
            try:
                return pref() == Qt.ContrastPreference.HighContrast
            except AttributeError:
                pass
    return _palette_suggests_high_contrast()


def _palette_suggests_high_contrast() -> bool:
    pal = QGuiApplication.palette()
    fg = pal.color(QPalette.ColorRole.WindowText)
    bg = pal.color(QPalette.ColorRole.Window)
    return contrast_ratio(_qcolor_hex(fg), _qcolor_hex(bg)) >= _PALETTE_HIGH_CONTRAST_RATIO


def prefers_reduce_motion() -> bool:
    """True when motion should be minimized (Qt ≥ 6.12 API, else QSettings)."""
    hints = _accessibility_hints()
    if hints is not None:
        motion_pref = getattr(hints, "motionPreference", None)
        if callable(motion_pref):
            try:
                value = motion_pref()
            except (AttributeError, TypeError):
                value = None
            reduce_enum = getattr(Qt, "MotionPreference", None)
            if value is not None and reduce_enum is not None:
                for name in ("Reduce", "ReduceMotion"):
                    member = getattr(reduce_enum, name, None)
                    if member is not None and value == member:
                        return True
    return app_settings.reduce_motion()


def apply_app_stylesheet(app: QApplication | None = None) -> None:
    target = app or QApplication.instance()
    if target is None:
        return
    target.setStyleSheet(
        app_stylesheet(
            high_contrast=prefers_high_contrast(),
            light=app_settings.light_theme(),
        )
    )


def refresh_themed_widgets(app: QApplication | None = None) -> None:
    """Re-apply app stylesheet after a theme preference change.

    Card/tile chrome uses dynamic properties + shared app QSS, so a single
    stylesheet swap restyles selection/hover/focus without per-card rebuilds.
    Also clears Phosphor icon tint cache so toolbar glyphs match light/dark.
    """
    apply_app_stylesheet(app or QApplication.instance())
    from pagedrop.ui.icons import refresh_icons

    refresh_icons()

class _AccessibilityWatcher(QObject):
    """Re-apply chrome when the system palette changes (Qt < 6.10 fallback path)."""

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            apply_app_stylesheet()
        return False


def install_accessibility(app: QApplication) -> None:
    """Apply theme for current prefs and watch for contrast / palette changes."""
    apply_app_stylesheet(app)

    hints = _accessibility_hints()
    if hints is not None:
        # PyQt6 currently exposes this as a plain method, not a bound signal.
        # Connect when the binding provides .connect; else palette watcher covers it.
        changed = getattr(hints, "contrastPreferenceChanged", None)
        connect = getattr(changed, "connect", None)
        if callable(connect):
            connect(lambda *_: apply_app_stylesheet(app))

    if app.property("_pagedrop_a11y_watcher") is None:
        watcher = _AccessibilityWatcher(app)
        app.installEventFilter(watcher)
        app.setProperty("_pagedrop_a11y_watcher", watcher)
