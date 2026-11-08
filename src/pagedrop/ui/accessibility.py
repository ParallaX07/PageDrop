"""Platform contrast / motion preferences and app chrome application."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QWidget

from pagedrop.ui import icons
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


def set_field_error_state(widget: QWidget, on: bool) -> None:
    """Mark *widget* as invalid (or clear it) for the shared ``error`` QSS rule.

    Repolishes only when the state changes; widgets without a matching rule
    are left visually untouched.
    """
    if bool(widget.property("error")) == on:
        return
    widget.setProperty("error", on)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_appearance(value: str) -> None:
    """Store the appearance choice, re-theme, and sync every window's menu."""
    app_settings.set_appearance(value)
    refresh_themed_widgets()
    for widget in QApplication.topLevelWidgets():
        try:
            action = getattr(widget, "_appearance_actions", {}).get(value)
            if action is not None:
                # The group's ``triggered`` only fires on user triggers, so
                # this keeps its exclusivity without re-entering the handler.
                action.setChecked(True)
            relayout = getattr(widget, "_update_responsive_shell", None)
            if relayout is not None:
                QTimer.singleShot(0, relayout)
        except RuntimeError:  # window already deleted
            continue


def _on_color_scheme_changed(*_: object) -> None:
    """Follow an OS light/dark switch, unless a theme was chosen explicitly."""
    if app_settings.appearance() == "system":
        refresh_themed_widgets()


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
        # Icons tinted for the bar follow the contrast preference too.
        refresh_themed_widgets(app)

    def on_state(state: Qt.ApplicationState) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            return
        # Check both so a lost indicator file is forgotten even alongside a contrast change.
        icon_files_lost = not icons.indicator_files_present()
        if prefers_high_contrast() != applied["high_contrast"] or icon_files_lost:
            reapply()

    def on_scheme(*_: object) -> None:
        # Follow the OS under the system appearance (icons too); otherwise only
        # pick up a contrast change that rode along with the scheme change.
        if app_settings.appearance() == "system":
            applied["high_contrast"] = prefers_high_contrast()
            _on_color_scheme_changed()
        else:
            reapply()

    QGuiApplication.styleHints().colorSchemeChanged.connect(on_scheme)
    app.applicationStateChanged.connect(on_state)
