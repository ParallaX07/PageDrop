"""Platform contrast / motion preferences and app chrome application."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from pagedrop.ui import settings as app_settings
from pagedrop.ui.theme import app_stylesheet, relative_luminance


def contrast_ratio(hex_fg: str, hex_bg: str) -> float:
    """WCAG 2.x contrast ratio between two #RRGGBB colors."""
    lighter = max(relative_luminance(hex_fg), relative_luminance(hex_bg))
    darker = min(relative_luminance(hex_fg), relative_luminance(hex_bg))
    return (lighter + 0.05) / (darker + 0.05)


def _accessibility_hints():
    style_hints = QGuiApplication.styleHints()
    getter = getattr(style_hints, "accessibility", None)
    if getter is None:
        return None
    return getter()


def prefers_high_contrast() -> bool:
    """True when the platform's contrast preference is High (Qt >= 6.10)."""
    hints = _accessibility_hints()
    if hints is None:
        return False
    return hints.contrastPreference() == Qt.ContrastPreference.HighContrast


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

def install_accessibility(app: QApplication) -> None:
    """Apply theme for current prefs and re-apply it when the platform appearance changes."""
    apply_app_stylesheet(app)

    if app.property("_pagedrop_a11y_watcher") is not None:
        return
    app.setProperty("_pagedrop_a11y_watcher", True)
    # PyQt6 exposes contrastPreferenceChanged as a plain method, not a signal, so a
    # color scheme change and re-activation pick up a platform contrast change.
    applied = {"high_contrast": prefers_high_contrast()}

    def reapply() -> None:
        applied["high_contrast"] = prefers_high_contrast()
        apply_app_stylesheet(app)

    def on_state(state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationState.ApplicationActive and prefers_high_contrast() != applied["high_contrast"]:
            reapply()

    QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: reapply())
    app.applicationStateChanged.connect(on_state)
